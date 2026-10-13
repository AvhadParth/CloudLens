"""Loads the simulated cloud dataset and answers the basic questions the dashboard asks."""

from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RECENT_DAYS = 30
GROUP_COLUMNS = ("type", "team", "environment", "region")


@lru_cache
def load_resources() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "resources.csv", parse_dates=["created_date"])


@lru_cache
def load_usage() -> pd.DataFrame:
    """Daily usage joined with the resource attributes used for grouping."""
    usage = pd.read_csv(DATA_DIR / "daily_usage.csv", parse_dates=["date"])
    attributes = load_resources()[["resource_id", *GROUP_COLUMNS]]
    return usage.merge(attributes, on="resource_id", how="left", validate="many_to_one")


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
        "resource_count": int(load_resources().shape[0]),
        "last_30_days_cost": round(current, 2),
        "previous_30_days_cost": round(previous, 2),
        "change_pct": round((current - previous) / previous * 100, 2),
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
    merged = load_resources().merge(stats, on="resource_id", how="left")
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
