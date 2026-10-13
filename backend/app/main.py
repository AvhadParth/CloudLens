"""CloudLens AI backend. Run from the backend folder with: uvicorn app.main:app --reload"""

from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from . import assistant, auth, data, engine, forecast, store

app = FastAPI(
    title="CloudLens AI",
    description="Cloud cost optimization prototype running on simulated data.",
    version="0.3.0",
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

# Everything on this router needs a logged-in user.
private = APIRouter(prefix="/api", dependencies=[Depends(auth.current_user)])


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=300)


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
        "forecast_next_30_days": forecast.forecast()["next_30_days_cost"],
    }


@private.get("/resources")
def get_resources():
    flagged = {rec["resource_id"]: rec["kind_label"] for rec in engine.recommendations()}
    return [{**row, "finding": flagged.get(row["resource_id"])} for row in data.resources_with_usage()]


@private.get("/costs")
def get_costs(
    granularity: Literal["daily", "monthly"] = "daily",
    group_by: Literal["type", "team", "environment", "region"] | None = None,
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
    return forecast.forecast(days)


@private.get("/assistant/suggestions")
def get_suggestions():
    return assistant.suggestions()


@private.post("/assistant")
def ask_assistant(body: Question, user: dict = Depends(auth.current_user)):
    return assistant.ask(body.question, user["id"])


app.include_router(private)
