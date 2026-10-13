"""Generate the simulated cloud dataset used by CloudLens AI.

Produces four CSV files next to this script:

  resources.csv       one row per cloud resource (what a cloud inventory API would return)
  daily_usage.csv     one row per resource per day (utilization and cost)
  ground_truth.csv    which resources were deliberately created as waste, and of what kind
  cost_anomalies.csv  the days on which a cost spike was deliberately injected

The optimization engine and the forecasting model only ever read the first two files.
The last two are the "answer key": they let us measure how many of the planted problems
the engine finds (precision / recall) instead of just claiming that it works.

The output is fully reproducible: the same seed always gives the same files.

Usage:
    python data/generate_data.py
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
START_DATE = "2025-10-01"
END_DATE = "2026-09-30"

# Sample price list (USD). Loosely modelled on public on-demand prices, not real quotes.
SIZES = {  # size: (vcpus, memory_gb, hourly_rate)
    "small": (2, 4, 0.046),
    "medium": (2, 8, 0.092),
    "large": (4, 16, 0.184),
    "xlarge": (8, 32, 0.368),
    "2xlarge": (16, 64, 0.736),
}
DATABASE_PRICE_MULTIPLIER = 1.9  # managed databases cost more than a plain VM of the same size
STORAGE_RATE_PER_GB_MONTH = 0.10
# Usage-based charges (data transfer etc.) as a share of compute cost when CPU averages 50%.
VARIABLE_COST_SHARE = 0.25

# Each team runs on one cloud provider: (provider, region).
TEAM_CLOUD = {
    "platform": ("aws", "ap-south-1"),
    "payments": ("aws", "ap-south-1"),
    "search": ("gcp", "asia-south1"),
    "analytics": ("gcp", "us-central1"),
    "mobile": ("azure", "centralindia"),
}

# Compute resources: (name, type, team, environment, size, profile, created_day, idle_from_day)
#   created_day    day index (0 = START_DATE) on which the resource first appears
#   idle_from_day  if set, the resource follows `profile` until that day and is idle afterwards
#
# Healthy profiles: web, steady, batch, memory_heavy, dev_scheduled
# Waste profiles:   idle, oversized, dev_always_on
#
# batch and memory_heavy are deliberate "near misses": their average CPU is low, but
# resizing them would be wrong (high peaks / high memory). A good rule must not flag them.
COMPUTE = [
    ("web-frontend-01", "vm", "platform", "prod", "large", "web", 0, None),
    ("web-frontend-02", "vm", "platform", "prod", "large", "web", 0, None),
    ("api-gateway-01", "vm", "platform", "prod", "xlarge", "web", 0, None),
    ("platform-monitoring", "vm", "platform", "prod", "medium", "steady", 0, None),
    ("users-db-primary", "database", "platform", "prod", "large", "steady", 0, None),
    ("staging-web-01", "vm", "platform", "staging", "medium", "dev_scheduled", 0, None),
    ("payments-api-01", "vm", "payments", "prod", "large", "web", 0, None),
    ("payments-api-02", "vm", "payments", "prod", "large", "web", 120, None),
    ("payments-db-primary", "database", "payments", "prod", "xlarge", "steady", 0, None),
    ("payments-staging-api", "vm", "payments", "staging", "medium", "dev_scheduled", 30, None),
    ("search-api-01", "vm", "search", "prod", "large", "web", 0, None),
    ("search-indexer-01", "vm", "search", "prod", "xlarge", "batch", 0, None),
    ("search-cache-01", "vm", "search", "prod", "large", "memory_heavy", 0, None),
    ("search-dev-01", "vm", "search", "dev", "medium", "dev_scheduled", 0, None),
    ("recommendations-api-01", "vm", "search", "prod", "large", "web", 250, None),
    ("analytics-etl-01", "vm", "analytics", "prod", "2xlarge", "batch", 0, None),
    ("analytics-warehouse-db", "database", "analytics", "prod", "2xlarge", "steady", 60, None),
    ("analytics-cache-01", "vm", "analytics", "prod", "xlarge", "memory_heavy", 150, None),
    ("mobile-backend-01", "vm", "mobile", "prod", "large", "web", 0, None),
    ("mobile-backend-02", "vm", "mobile", "prod", "large", "web", 200, None),
    ("mobile-push-worker", "vm", "mobile", "prod", "medium", "steady", 90, None),
    ("mobile-ci-runner", "vm", "mobile", "dev", "large", "batch", 0, None),
    # --- idle: running and billed, but doing almost nothing ---
    ("legacy-report-server", "vm", "analytics", "prod", "large", "idle", 0, None),
    ("payments-migration-tmp", "vm", "payments", "prod", "xlarge", "steady", 0, 150),
    ("old-campaign-landing", "vm", "mobile", "prod", "medium", "web", 0, 200),
    ("search-poc-db", "database", "search", "dev", "large", "idle", 40, None),
    ("platform-test-db", "database", "platform", "test", "medium", "idle", 0, None),
    # --- oversized: used, but far below what the instance size provides ---
    ("analytics-dashboard-01", "vm", "analytics", "prod", "2xlarge", "oversized", 0, None),
    ("payments-batch-recon", "vm", "payments", "prod", "xlarge", "oversized", 0, None),
    ("platform-auth-service", "vm", "platform", "prod", "xlarge", "oversized", 0, None),
    ("mobile-config-service", "vm", "mobile", "prod", "large", "oversized", 0, None),
    ("search-suggest-api", "vm", "search", "prod", "2xlarge", "oversized", 100, None),
    ("reporting-db-replica", "database", "analytics", "prod", "xlarge", "oversized", 0, None),
    # --- dev_always_on: only used in working hours, but left running nights and weekends ---
    ("payments-dev-01", "vm", "payments", "dev", "large", "dev_always_on", 0, None),
    ("mobile-dev-01", "vm", "mobile", "dev", "large", "dev_always_on", 0, None),
    ("analytics-notebook-dev", "vm", "analytics", "dev", "xlarge", "dev_always_on", 80, None),
    ("platform-qa-env", "vm", "platform", "test", "large", "dev_always_on", 0, None),
    ("mobile-qa-db", "database", "mobile", "test", "medium", "dev_always_on", 0, None),
]

# Storage volumes: (name, team, environment, size_gb, attached_to, created_day, detached_from_day)
#   attached_to = None means the volume is not attached to anything today (waste).
STORAGE = [
    ("web-assets-volume", "platform", "prod", 500, "web-frontend-01", 0, None),
    ("payments-db-volume", "payments", "prod", 1000, "payments-db-primary", 0, None),
    ("analytics-data-lake-vol", "analytics", "prod", 4000, "analytics-etl-01", 0, None),
    ("search-index-volume", "search", "prod", 800, "search-indexer-01", 0, None),
    ("old-etl-scratch-disk", "analytics", "prod", 2000, None, 0, 90),
    ("payments-migration-backup", "payments", "prod", 1500, None, 150, 150),
    ("mobile-build-cache-old", "mobile", "dev", 600, None, 0, 0),
    ("legacy-report-data", "analytics", "prod", 900, None, 0, 0),
]

# Injected one-day cost spikes: (resource name, day index, multiplier)
ANOMALIES = [
    ("api-gateway-01", 133, 3.5),
    ("analytics-etl-01", 251, 3.0),
    ("mobile-backend-01", 318, 4.0),
]

WASTE_NOTES = {
    "idle": "Running and billed but CPU and memory are near zero",
    "oversized": "Peak usage is far below the capacity of the instance size",
    "always_on_dev": "Non-production resource used in working hours but running 24x7",
    "unattached_storage": "Volume is not attached to any resource and has no I/O",
    "none": "",
}
PROFILE_WASTE = {"idle": "idle", "oversized": "oversized", "dev_always_on": "always_on_dev"}


def simulate_compute(profile, weekday, progress, rng):
    """Return per-day (business_cpu, off_hours_cpu, p95_cpu, memory, hours_running).

    Business hours are 08:00-20:00, off hours are the remaining 12 hours.
    `progress` runs from 0 to 1 across the year and drives gradual traffic growth.
    """
    n = len(weekday)
    weekend = weekday >= 5
    hours = np.full(n, 24.0)

    if profile == "web":
        load = (1 + 0.25 * progress) * np.where(weekend, 0.6, 1.0)
        business = rng.normal(52, 4, n) * load
        off = business * 0.45
        p95 = business * 1.35
        memory = rng.normal(58, 3, n)
    elif profile == "steady":
        business = rng.normal(50, 4, n)
        off = rng.normal(40, 4, n)
        p95 = business + rng.normal(15, 3, n)
        memory = rng.normal(65, 3, n)
    elif profile == "batch":
        business = rng.normal(12, 3, n)
        off = rng.normal(45, 6, n)
        p95 = rng.normal(90, 4, n)
        memory = rng.normal(50, 5, n)
    elif profile == "memory_heavy":
        business = rng.normal(12, 2, n)
        off = rng.normal(8, 2, n)
        p95 = rng.normal(25, 3, n)
        memory = rng.normal(82, 3, n)
    elif profile == "dev_scheduled":
        hours = np.where(weekend, 0.0, 12.0)
        business = np.where(weekend, 0.0, rng.normal(40, 5, n))
        off = np.zeros(n)
        p95 = np.where(weekend, 0.0, rng.normal(70, 6, n))
        memory = np.where(weekend, 0.0, rng.normal(45, 4, n))
    elif profile == "idle":
        business = rng.normal(2.0, 0.5, n)
        off = rng.normal(1.5, 0.4, n)
        p95 = rng.normal(5, 1, n)
        memory = rng.normal(10, 2, n)
    elif profile == "oversized":
        business = rng.normal(13, 2, n)
        off = rng.normal(7, 1.5, n)
        p95 = rng.normal(28, 3, n)
        memory = rng.normal(28, 3, n)
    elif profile == "dev_always_on":
        business = np.where(weekend, rng.normal(1.5, 0.4, n), rng.normal(38, 5, n))
        off = rng.normal(1.5, 0.4, n)
        p95 = np.where(weekend, rng.normal(4, 1, n), rng.normal(65, 6, n))
        memory = rng.normal(30, 3, n)
    else:
        raise ValueError(f"Unknown profile: {profile}")

    return business, off, p95, memory, hours


def generate(seed=SEED):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(START_DATE, END_DATE, freq="D")
    n_days = len(dates)
    day_index = np.arange(n_days)
    weekday = dates.weekday.to_numpy()
    progress = day_index / (n_days - 1)

    resources, usage, truth = [], [], []
    ids_by_name = {}
    next_id = 1

    for name, rtype, team, env, size, profile, created_day, idle_from in COMPUTE:
        rid = f"res-{next_id:03d}"
        next_id += 1
        ids_by_name[name] = rid
        vcpus, memory_gb, rate = SIZES[size]
        if rtype == "database":
            rate = round(rate * DATABASE_PRICE_MULTIPLIER, 4)

        business, off, p95, memory, hours = simulate_compute(profile, weekday, progress, rng)
        if idle_from is not None:
            idle = simulate_compute("idle", weekday, progress, rng)
            went_idle = day_index >= idle_from
            business, off, p95, memory, hours = (
                np.where(went_idle, i, a) for i, a in zip(idle, (business, off, p95, memory, hours))
            )

        business, off, p95, memory = (np.clip(x, 0, 100) for x in (business, off, p95, memory))
        cpu_avg = (business + off) / 2  # average over the whole day; 0 while switched off
        p95 = np.maximum(p95, np.maximum(business, off))

        compute_cost = rate * hours
        variable_cost = rate * 24 * VARIABLE_COST_SHARE * (cpu_avg / 50) * rng.normal(1, 0.08, n_days)
        cost = compute_cost + np.clip(variable_cost, 0, None)

        active = day_index >= created_day
        frame = pd.DataFrame(
            {
                "date": dates,
                "resource_id": rid,
                "cpu_avg": cpu_avg.round(2),
                "cpu_p95": p95.round(2),
                "cpu_business_hours": business.round(2),
                "cpu_off_hours": off.round(2),
                "memory_avg": memory.round(2),
                "hours_running": hours,
                "io_ops": np.nan,
                "cost": cost,
            }
        )
        usage.append(frame[active])

        resources.append(
            {
                "resource_id": rid,
                "name": name,
                "type": rtype,
                "team": team,
                "environment": env,
                "provider": TEAM_CLOUD[team][0],
                "region": TEAM_CLOUD[team][1],
                "size": size,
                "vcpus": vcpus,
                "memory_gb": memory_gb,
                "storage_gb": np.nan,
                "hourly_rate": rate,
                "created_date": dates[created_day].date(),
                "attached_to": "",
            }
        )
        waste = "idle" if idle_from is not None else PROFILE_WASTE.get(profile, "none")
        truth.append({"resource_id": rid, "name": name, "waste_type": waste, "note": WASTE_NOTES[waste]})

    for name, team, env, size_gb, attached_to, created_day, detached_from in STORAGE:
        rid = f"res-{next_id:03d}"
        next_id += 1
        ids_by_name[name] = rid

        io_ops = rng.poisson(40 * size_gb, n_days).astype(float)
        if detached_from is not None:
            io_ops[day_index >= detached_from] = 0
        daily_cost = size_gb * STORAGE_RATE_PER_GB_MONTH * 12 / 365

        active = day_index >= created_day
        frame = pd.DataFrame(
            {
                "date": dates,
                "resource_id": rid,
                "cpu_avg": np.nan,
                "cpu_p95": np.nan,
                "cpu_business_hours": np.nan,
                "cpu_off_hours": np.nan,
                "memory_avg": np.nan,
                "hours_running": 24.0,
                "io_ops": io_ops,
                "cost": daily_cost,
            }
        )
        usage.append(frame[active])

        resources.append(
            {
                "resource_id": rid,
                "name": name,
                "type": "storage",
                "team": team,
                "environment": env,
                "provider": TEAM_CLOUD[team][0],
                "region": TEAM_CLOUD[team][1],
                "size": "",
                "vcpus": np.nan,
                "memory_gb": np.nan,
                "storage_gb": size_gb,
                "hourly_rate": np.nan,
                "created_date": dates[created_day].date(),
                "attached_to": ids_by_name[attached_to] if attached_to else "",
            }
        )
        waste = "none" if attached_to else "unattached_storage"
        truth.append({"resource_id": rid, "name": name, "waste_type": waste, "note": WASTE_NOTES[waste]})

    usage = pd.concat(usage, ignore_index=True)

    anomalies = []
    for name, day, multiplier in ANOMALIES:
        rid = ids_by_name[name]
        row = (usage["resource_id"] == rid) & (usage["date"] == dates[day])
        usage.loc[row, "cost"] *= multiplier
        anomalies.append({"date": dates[day].date(), "resource_id": rid, "name": name, "multiplier": multiplier})

    usage["cost"] = usage["cost"].round(4)
    usage = usage.sort_values(["date", "resource_id"], ignore_index=True)

    resources = pd.DataFrame(resources).astype({"vcpus": "Int64", "memory_gb": "Int64", "storage_gb": "Int64"})
    usage["io_ops"] = usage["io_ops"].astype("Int64")
    return resources, usage, pd.DataFrame(truth), pd.DataFrame(anomalies)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()

    resources, usage, truth, anomalies = generate(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    resources.to_csv(args.out / "resources.csv", index=False)
    usage.to_csv(args.out / "daily_usage.csv", index=False, date_format="%Y-%m-%d")
    truth.to_csv(args.out / "ground_truth.csv", index=False)
    anomalies.to_csv(args.out / "cost_anomalies.csv", index=False)

    monthly = usage.groupby(usage["date"].dt.to_period("M"))["cost"].sum().round(0)
    print(f"Resources:  {len(resources)}")
    print(f"Usage rows: {len(usage)}  ({usage['date'].min().date()} to {usage['date'].max().date()})")
    print(f"Total cost: ${usage['cost'].sum():,.0f}")
    print("Planted waste:")
    print(truth["waste_type"].value_counts().to_string())
    print("Monthly cost (USD):")
    print(monthly.to_string())


if __name__ == "__main__":
    main()
