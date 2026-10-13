"""Optimization engine: simple, explainable rules that flag wasteful resources.

Each rule looks at the last LOOKBACK_DAYS of usage for one resource. A resource gets at
most one recommendation; rules are checked in order, so "idle" wins over "oversized".

All savings are estimates for a 30-day month and nothing here touches real infrastructure.
"""

import pandas as pd

from . import data

LOOKBACK_DAYS = 30
HOURS_PER_MONTH = 24 * 30

# Every threshold lives here so it can be explained (and tuned) in one place.
THRESHOLDS = {
    "idle_cpu_avg": 5.0,  # % average CPU below which a resource counts as idle
    "idle_cpu_peak": 15.0,  # % and it must never have peaked above this
    "idle_memory_avg": 20.0,  # % average memory
    "oversized_cpu_peak": 40.0,  # % highest daily p95 CPU in the window
    "oversized_memory_peak": 50.0,  # % highest daily memory average in the window
    "schedule_off_hours_cpu": 5.0,  # % average CPU outside 08:00-20:00
    "schedule_business_cpu": 10.0,  # % weekday working-hours CPU that proves it is in use
    "schedule_min_hours": 20.0,  # average hours/day running to count as "always on"
}
NON_PRODUCTION = {"dev", "test", "staging"}
SIZE_ORDER = ["small", "medium", "large", "xlarge", "2xlarge"]
DOWNSIZE_PRICE_FACTOR = 0.5  # in the sample price list each size costs half the next one up
SCHEDULE_HOURS_PER_WEEK = 12 * 5  # 08:00-20:00, Monday to Friday

KIND_LABELS = {
    "idle": "Switched on but not used",
    "oversized": "Bigger than it needs to be",
    "always_on_dev": "Left on when nobody is working",
    "unattached_storage": "Storage nobody uses",
}


def resource_stats() -> pd.DataFrame:
    """One row per resource with the usage figures the rules need."""
    window = data.recent(data.load_usage(), LOOKBACK_DAYS)
    stats = window.groupby("resource_id").agg(
        cpu_avg=("cpu_avg", "mean"),
        cpu_peak=("cpu_p95", "max"),
        memory_avg=("memory_avg", "mean"),
        memory_peak=("memory_avg", "max"),
        cpu_off_hours=("cpu_off_hours", "mean"),
        hours_running=("hours_running", "mean"),
        io_ops=("io_ops", "sum"),
        cost=("cost", "sum"),
    )
    weekdays = window[window["date"].dt.weekday < 5]
    stats["cpu_business_weekdays"] = weekdays.groupby("resource_id")["cpu_business_hours"].mean()
    return data.load_resources().merge(stats, left_on="resource_id", right_index=True)


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _check(r) -> dict | None:
    """Apply the rules to one resource. Returns the recommendation fields, or None."""
    t = THRESHOLDS

    if r.type == "storage":
        if pd.isna(r.attached_to) and r.io_ops == 0:
            return {
                "kind": "unattached_storage",
                "action": "Back it up, then delete it",
                "reason": f"It is not connected to anything, and nothing has read or written to it in {LOOKBACK_DAYS} days.",
                "evidence": [
                    {"label": "Connected to", "value": "Nothing"},
                    {"label": "Times it was used", "value": "0"},
                    {"label": "Size", "value": f"{int(r.storage_gb):,} GB"},
                ],
                "saving": r.cost,
            }
        return None

    if r.cpu_avg < t["idle_cpu_avg"] and r.cpu_peak < t["idle_cpu_peak"] and r.memory_avg < t["idle_memory_avg"]:
        return {
            "kind": "idle",
            "action": "Switch it off",
            "reason": f"It has been switched on for {LOOKBACK_DAYS} days but has done almost no work.",
            "evidence": [
                {"label": "Processor used, on average", "value": _pct(r.cpu_avg)},
                {"label": "Processor used, busiest moment", "value": _pct(r.cpu_peak)},
                {"label": "Memory used, on average", "value": _pct(r.memory_avg)},
            ],
            "saving": r.cost,
        }

    if (
        r.environment in NON_PRODUCTION
        and r.hours_running >= t["schedule_min_hours"]
        and r.cpu_off_hours < t["schedule_off_hours_cpu"]
        and r.cpu_business_weekdays >= t["schedule_business_cpu"]
    ):
        off_share = 1 - SCHEDULE_HOURS_PER_WEEK / (24 * 7)
        return {
            "kind": "always_on_dev",
            "action": "Switch it off at night and on weekends",
            "reason": "It is used during working hours, then sits switched on all night and all weekend doing nothing.",
            "evidence": [
                {"label": "Processor used, working hours", "value": _pct(r.cpu_business_weekdays)},
                {"label": "Processor used, nights and weekends", "value": _pct(r.cpu_off_hours)},
                {"label": "Hours switched on each day", "value": f"{r.hours_running:.0f}"},
            ],
            "saving": r.hourly_rate * HOURS_PER_MONTH * off_share,
        }

    if (
        r.cpu_peak < t["oversized_cpu_peak"]
        and r.memory_peak < t["oversized_memory_peak"]
        and SIZE_ORDER.index(r["size"]) > 0
    ):
        smaller = SIZE_ORDER[SIZE_ORDER.index(r["size"]) - 1]
        return {
            "kind": "oversized",
            "action": f"Move it to a smaller size ({r['size']} to {smaller})",
            "reason": "Even on its busiest day it used less than half of what you are paying for.",
            "evidence": [
                {"label": "Processor used, busiest moment", "value": _pct(r.cpu_peak)},
                {"label": "Memory used, busiest day", "value": _pct(r.memory_peak)},
                {"label": "Processor used, on average", "value": _pct(r.cpu_avg)},
            ],
            "saving": r.hourly_rate * HOURS_PER_MONTH * (1 - DOWNSIZE_PRICE_FACTOR),
        }

    return None


def recommendations() -> list[dict]:
    """All open findings, largest estimated saving first."""
    found = []
    for _, r in resource_stats().iterrows():
        result = _check(r)
        if result is None:
            continue
        saving = result.pop("saving")
        found.append(
            {
                "resource_id": r.resource_id,
                "name": r["name"],
                "type": r.type,
                "team": r.team,
                "environment": r.environment,
                "size": None if pd.isna(r["size"]) else r["size"],
                "kind_label": KIND_LABELS[result["kind"]],
                **result,
                "current_monthly_cost": round(float(r.cost), 2),
                "estimated_monthly_saving": round(float(min(saving, r.cost)), 2),
            }
        )
    return sorted(found, key=lambda rec: rec["estimated_monthly_saving"], reverse=True)


def evaluate() -> dict:
    """Score the rules against the answer key written by the data generator."""
    truth = pd.read_csv(data.DATA_DIR / "ground_truth.csv")
    predicted = {rec["resource_id"]: rec["kind"] for rec in recommendations()}
    truth["predicted"] = truth["resource_id"].map(predicted).fillna("none")

    def score(actual: pd.Series, flagged: pd.Series) -> dict:
        tp = int((actual & flagged).sum())
        fp = int((~actual & flagged).sum())
        fn = int((actual & ~flagged).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }

    return {
        "resources": len(truth),
        "planted_waste": int((truth["waste_type"] != "none").sum()),
        "overall": score(truth["waste_type"] != "none", truth["predicted"] != "none"),
        "by_kind": {
            kind: {"label": label, **score(truth["waste_type"] == kind, truth["predicted"] == kind)}
            for kind, label in KIND_LABELS.items()
        },
        "mistakes": data.to_records(
            truth[truth["waste_type"] != truth["predicted"]][["resource_id", "name", "waste_type", "predicted"]]
        ),
    }
