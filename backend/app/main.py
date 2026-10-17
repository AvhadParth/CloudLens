"""CloudLens AI backend. Run from the backend folder with: uvicorn app.main:app --reload"""

import os

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from . import assistant, auth, data, engine, forecast, live, store
from .cloud import CloudError, aws

app = FastAPI(
    title="CloudLens AI",
    description="Cloud cost optimization prototype running on simulated data.",
    version="0.5.0",
)

# The Vite dev server runs on a different port, so the browser needs CORS permission.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)


@app.exception_handler(PyMongoError)
def database_unreachable(request, error):
    """Say clearly when MongoDB cannot be reached (wrong address, or this server's IP is not allowed in Atlas)."""
    return JSONResponse(
        status_code=503,
        content={"detail": "We could not reach the database. Please try again in a moment."},
    )

def _scope_for(user: dict) -> data.Scope:
    """Sample accounts picked on the Connections page, plus real accounts that have
    finished at least one sync. A new account has neither, so it sees no data yet."""
    sample = frozenset(c["provider"] for c in user.get("connections", []))
    live = tuple(
        (account["id"], account["last_synced_at"])
        for account in store.list_cloud_accounts(user["id"])
        if account.get("last_synced_at")
    )
    if not sample and not live:
        raise HTTPException(status_code=409, detail="Connect a cloud account first.")
    scope = data.Scope(sample=sample, live=live)
    data.set_scope(scope)
    if data.load_usage().empty:
        raise HTTPException(status_code=409, detail="Your connected accounts have no costs or servers to show yet.")
    return scope


async def connected_scope(user: dict = Depends(auth.current_user)) -> dict:
    """Limit this request to the user's connected accounts.

    The database work runs in a worker thread; the scope is then set here, in the request's
    own context, so the endpoint (which runs in another worker thread) inherits it.
    """
    data.set_scope(await run_in_threadpool(_scope_for, user))
    return user


# Needs a logged-in user.
account = APIRouter(prefix="/api", dependencies=[Depends(auth.current_user)])
# Needs a logged-in user with at least one connected cloud account.
private = APIRouter(prefix="/api", dependencies=[Depends(connected_scope)])


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=300)


class NewConnection(BaseModel):
    provider: Literal["aws", "azure", "gcp"]


class NewCloudAccount(BaseModel):
    provider: Literal["aws", "azure", "gcp"]
    label: str = Field(default="", max_length=60)
    # Provider-specific keys; each connector checks the fields it needs.
    credentials: dict[str, str] = Field(max_length=6)


def connections_view(connections: list[dict]) -> list[dict]:
    """Every provider CloudLens supports, marked with whether this user has connected it."""
    connected = {c["provider"]: c for c in connections}
    return [
        {
            **provider,
            "connected": provider["id"] in connected,
            "connected_at": connected.get(provider["id"], {}).get("connected_at"),
        }
        for provider in data.provider_overview()
    ]


def recommendations_with_status(user: dict) -> list[dict]:
    """Engine findings joined with this user's decision (open / approved / dismissed)."""
    decisions = {a["resource_id"]: a for a in store.list_actions(user["id"])}
    result = []
    for rec in engine.recommendations():
        decision = decisions.get(rec["resource_id"])
        result.append(
            {
                **rec,
                "status": decision["status"] if decision else "open",
                "action_id": decision["id"] if decision else None,
            }
        )
    return result


def find_recommendation(resource_id: str) -> dict:
    for rec in engine.recommendations():
        if rec["resource_id"] == resource_id:
            return rec
    raise HTTPException(status_code=404, detail="No recommendation for this resource")


def waste_by_kind(recs: list[dict]) -> dict:
    kinds = {}
    for rec in recs:
        entry = kinds.setdefault(rec["kind"], {"label": rec["kind_label"], "count": 0, "saving": 0.0})
        entry["count"] += 1
        entry["saving"] = round(entry["saving"] + rec["estimated_monthly_saving"], 2)
    return kinds


@app.get("/api/health")
def health():
    return {"status": "ok", "data_source": "simulated", "database": "mongodb" if store.using_real_database() else "in-memory"}


@app.get("/api/public/preview")
def public_preview():
    """Headline numbers from the sample data, shown on the homepage before anyone logs in."""
    recs = engine.recommendations()
    return {
        "monthly_bill": data.summary()["last_30_days_cost"],
        "monthly_waste": round(sum(r["estimated_monthly_saving"] for r in recs), 2),
        "resource_count": data.summary()["resource_count"],
        "finding_count": len(recs),
        "waste_by_kind": waste_by_kind(recs),
    }


@account.get("/connections")
def get_connections(user: dict = Depends(auth.current_user)):
    return connections_view(user.get("connections", []))


@account.post("/connections")
def add_connection(body: NewConnection, user: dict = Depends(auth.current_user)):
    """Connect a cloud account. In this prototype that links the provider's sample account;
    no real cloud credentials are asked for or stored."""
    connections = user.get("connections", [])
    if body.provider not in {c["provider"] for c in connections}:
        connections = [*connections, {"provider": body.provider, "connected_at": store.now()}]
        store.set_connections(user["id"], connections)
    return connections_view(connections)


@account.delete("/connections/{provider}")
def remove_connection(provider: Literal["aws", "azure", "gcp"], user: dict = Depends(auth.current_user)):
    connections = [c for c in user.get("connections", []) if c["provider"] != provider]
    store.set_connections(user["id"], connections)
    return connections_view(connections)


# --- real cloud accounts ------------------------------------------------------------


@account.get("/cloud-accounts")
def get_cloud_accounts(user: dict = Depends(auth.current_user)):
    return {
        "enabled": bool(os.environ.get("CREDENTIALS_KEY")),
        "accounts": [live.public(a) for a in store.list_cloud_accounts(user["id"])],
        "aws_policy": aws.POLICY,
    }


@account.post("/cloud-accounts", status_code=201)
def add_cloud_account(body: NewCloudAccount, user: dict = Depends(auth.current_user)):
    """Check the keys with the provider and save them encrypted. Call /sync next to read the data."""
    try:
        return live.connect(user["id"], body.provider, body.label, body.credentials)
    except CloudError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="We could not reach the cloud provider. Try again in a minute.") from None


@account.post("/cloud-accounts/{account_id}/sync")
def sync_cloud_account(account_id: str, user: dict = Depends(auth.current_user)):
    """Read the account's bill, servers, disks and usage now. Takes a few seconds to a minute."""
    result = live.sync(user["id"], account_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Cloud account not found")
    return result


@account.delete("/cloud-accounts/{account_id}")
def remove_cloud_account(account_id: str, user: dict = Depends(auth.current_user)):
    """Forget the account: its encrypted keys and all data read from it are deleted."""
    if not store.delete_cloud_account(user["id"], account_id):
        raise HTTPException(status_code=404, detail="Cloud account not found")
    return {"deleted": account_id}


def _next_30_days() -> float | None:
    try:
        return forecast.forecast()["next_30_days_cost"]
    except forecast.NotEnoughHistory:
        return None


@private.get("/summary")
def get_summary(user: dict = Depends(auth.current_user)):
    recs = recommendations_with_status(user)

    def total(status: str) -> float:
        return round(sum(r["estimated_monthly_saving"] for r in recs if r["status"] == status), 2)

    return {
        **data.summary(),
        "recommendation_count": len(recs),
        "potential_monthly_saving": round(sum(r["estimated_monthly_saving"] for r in recs), 2),
        "open_monthly_saving": total("open"),
        "approved_monthly_saving": total("approved"),
        "waste_by_kind": waste_by_kind(recs),
        "forecast_next_30_days": _next_30_days(),
    }


@private.get("/resources")
def get_resources():
    flagged = {rec["resource_id"]: rec["kind_label"] for rec in engine.recommendations()}
    return [{**row, "finding": flagged.get(row["resource_id"])} for row in data.resources_with_usage()]


@private.get("/costs")
def get_costs(
    granularity: Literal["daily", "monthly"] = "daily",
    group_by: Literal["type", "team", "environment", "region", "provider"] | None = None,
):
    return data.cost_series(granularity, group_by)


@private.get("/recommendations")
def get_recommendations(user: dict = Depends(auth.current_user)):
    return recommendations_with_status(user)


@private.post("/recommendations/{resource_id}/{decision}")
def decide(resource_id: str, decision: Literal["approve", "dismiss"], user: dict = Depends(auth.current_user)):
    """Record a simulated decision. Nothing outside the database is changed."""
    status = "approved" if decision == "approve" else "dismissed"
    return store.record(user["id"], find_recommendation(resource_id), status)


@private.get("/actions")
def get_actions(user: dict = Depends(auth.current_user)):
    return store.list_actions(user["id"])


@private.delete("/actions/{action_id}")
def undo_action(action_id: str, user: dict = Depends(auth.current_user)):
    if not store.delete(user["id"], action_id):
        raise HTTPException(status_code=404, detail="Action not found")
    return {"deleted": action_id}


@private.get("/evaluation")
def get_evaluation():
    return {"rules": engine.evaluate(), "thresholds": engine.THRESHOLDS, "forecast": forecast.backtest()}


@private.get("/forecast")
def get_forecast(days: int = forecast.DEFAULT_HORIZON):
    if not 7 <= days <= 365:
        raise HTTPException(status_code=422, detail="days must be between 7 and 365")
    try:
        return forecast.forecast(days)
    except forecast.NotEnoughHistory as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@private.get("/assistant/suggestions")
def get_suggestions():
    return assistant.suggestions()


@private.post("/assistant")
def ask_assistant(body: Question, user: dict = Depends(auth.current_user)):
    return assistant.ask(body.question, user["id"])


app.include_router(account)
app.include_router(private)
