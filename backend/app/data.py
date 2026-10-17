"""Loads the simulated cloud dataset and answers the basic questions the dashboard asks."""

from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import store

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RECENT_DAYS = 30
GROUP_COLUMNS = ("type", "team", "environment", "region", "provider")
PROVIDERS = {"aws": "Amazon Web Services", "azure": "Microsoft Azure", "gcp": "Google Cloud"}

@dataclass(frozen=True)
class Scope:
    """What the current request may see: sample providers, plus real accounts by (id, last sync)."""

    sample: frozenset = frozenset()
    live: tuple = ()


# Set once per request from the user's connections (see main.py). Defaults to the whole
# sample company, which is what the tests and the public homepage use.
_active = ContextVar("scope", default=Scope(sample=frozenset(PROVIDERS)))


def set_scope(scope: Scope) -> None:
    _active.set(scope)


def active() -> Scope:
    return _active.get()


@lru_cache
def all_resources() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "resources.csv", parse_dates=["created_date"])


@lru_cache
def all_usage() -> pd.DataFrame:
    """Daily usage joined with the resource attributes used for grouping."""
    usage = pd.read_csv(DATA_DIR / "daily_usage.csv", parse_dates=["date"])
    attributes = all_resources()[["resource_id", *GROUP_COLUMNS]]
    return usage.merge(attributes, on="resource_id", how="left", validate="many_to_one")


@lru_cache(maxsize=64)
def _live_frames(account_id: str, synced_at: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The tables saved by a real account's latest sync. Cached until the next sync."""
    snapshot = store.get_snapshot(account_id) or {"resources": [], "usage": []}
    resources = pd.DataFrame(snapshot["resources"], columns=list(all_resources().columns))
    resources["created_date"] = pd.to_datetime(resources["created_date"], errors="coerce")
    usage = pd.DataFrame(snapshot["usage"], columns=[c for c in all_usage().columns if c not in GROUP_COLUMNS])
    usage["date"] = pd.to_datetime(usage["date"])
    usage = usage.merge(resources[["resource_id", *GROUP_COLUMNS]], on="resource_id", how="left")
    return resources, usage


def _combine(sample: pd.DataFrame, live: list[pd.DataFrame]) -> pd.DataFrame:
    parts = [sample, *[frame for frame in live if not frame.empty]]
    return pd.concat(parts, ignore_index=True) if len(parts) > 1 else sample


def load_resources() -> pd.DataFrame:
    """Resources from the connected sample providers and real accounts."""
    resources = all_resources()
    sample = resources[resources["provider"].isin(active().sample)]
    return _combine(sample, [_live_frames(*key)[0] for key in active().live])


def load_usage() -> pd.DataFrame:
    """Daily usage from the connected sample providers and real accounts."""
    usage = all_usage()
    sample = usage[usage["provider"].isin(active().sample)]
    return _combine(sample, [_live_frames(*key)[1] for key in active().live])


def provider_overview() -> list[dict]:
    """What each provider's sample account contains, whether or not it is connected."""
    resources, last_30 = all_resources(), recent(all_usage())
    return [
        {
            "id": provider,
            "name": name,
            "resource_count": int((resources["provider"] == provider).sum()),
            "monthly_cost": round(float(last_30.loc[last_30["provider"] == provider, "cost"].sum()), 2),
        }
        for provider, name in PROVIDERS.items()
    ]


def to_records(frame: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame to JSON-safe dicts (NaN becomes null, dates become ISO strings)."""
    frame = frame.copy()
    for column in frame.select_dtypes(include="datetime").columns:
        frame[column] = frame[column].dt.strftime("%Y-%m-%d")
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def recent(usage: pd.DataFrame, days: int = RECENT_DAYS, offset: int = 0) -> pd.DataFrame:
    """Rows from a `days`-long window ending `offset` days before the last date in the data."""
    end = usage["date"].max() - pd.Timedelta(days=offset)
    start = end - pd.Timedelta(days=days)
    return usage[(usage["date"] > start) & (usage["date"] <= end)]


def summary() -> dict:
    usage = load_usage()
    current = recent(usage)["cost"].sum()
    previous = recent(usage, offset=RECENT_DAYS)["cost"].sum()
    last_30 = recent(usage)
    return {
        "period_start": usage["date"].min().strftime("%Y-%m-%d"),
        "period_end": usage["date"].max().strftime("%Y-%m-%d"),
        "currency": "USD",
        "total_cost": round(usage["cost"].sum(), 2),
        "resource_count": int((load_resources()["type"] != "other").sum()),
        "last_30_days_cost": round(current, 2),
        "previous_30_days_cost": round(previous, 2),
        "change_pct": round((current - previous) / previous * 100, 2) if previous else 0.0,
        "last_30_days_by": {
            column: last_30.groupby(column)["cost"].sum().round(2).sort_values(ascending=False).to_dict()
            for column in GROUP_COLUMNS
        },
    }


def resources_with_usage() -> list[dict]:
    """Every resource with its average utilization and cost over the last 30 days."""
    stats = (
        recent(load_usage())
        .groupby("resource_id")
        .agg(
            cpu_avg=("cpu_avg", "mean"),
            cpu_p95=("cpu_p95", "max"),
            memory_avg=("memory_avg", "mean"),
            last_30_days_cost=("cost", "sum"),
        )
        .round(2)
        .reset_index()
    )
    resources = load_resources()
    merged = resources[resources["type"] != "other"].merge(stats, on="resource_id", how="left")
    return to_records(merged.sort_values("last_30_days_cost", ascending=False))


def cost_series(granularity: str = "daily", group_by: str | None = None) -> list[dict]:
    """Cost over time, optionally split by a resource attribute."""
    usage = load_usage()
    if granularity == "monthly":
        period = usage["date"].dt.to_period("M").dt.strftime("%Y-%m")
    else:
        period = usage["date"].dt.strftime("%Y-%m-%d")
    keys = [period.rename("period")] + ([group_by] if group_by else [])
    return to_records(usage.groupby(keys)["cost"].sum().round(2).reset_index())
