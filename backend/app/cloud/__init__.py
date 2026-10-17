"""Connectors that read real cloud accounts (AWS, Azure, Google Cloud).

Every connector does the same two jobs, using only read-only permissions:

  validate(credentials, http) -> AccountInfo
      Prove the keys work and say which account they belong to.

  collect(credentials, http) -> Collected
      Read the last year of daily costs, the current servers and disks, and 30 days of
      hourly processor use, and return them in one provider-neutral shape.

The connectors talk to each provider's REST API directly with httpx instead of the
official SDKs. That keeps the deployed bundle small (the SDKs together are several
hundred MB) and makes every request easy to read and explain.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

USAGE_DAYS = 30  # how much hourly utilization each sync reads
COST_DAYS = 365  # how much daily billing history each sync reads
WORK_TIMEZONE = ZoneInfo("Asia/Kolkata")  # "working hours" means 08:00-20:00 in this zone
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class CloudError(Exception):
    """A problem worth showing to the user as-is (bad keys, missing permission, ...)."""


@dataclass
class AccountInfo:
    account_ref: str  # e.g. AWS account id, Azure subscription id, GCP project id
    display_name: str


@dataclass
class Machine:
    native_id: str
    name: str
    region: str
    size: str
    running: bool
    tags: dict
    hourly_rate: float | None = None  # list price; None when unknown
    vcpus: int | None = None
    memory_gb: float | None = None
    created: str | None = None
    # (UTC datetime, average %, maximum %) for each hour the machine reported in the window
    cpu_hours: list = field(default_factory=list)
    # optional real daily cost by ISO date (Azure reports it per resource)
    daily_cost: dict = field(default_factory=dict)


@dataclass
class Disk:
    native_id: str
    name: str
    region: str
    size_gb: float
    attached_to: str | None
    tags: dict
    monthly_rate_per_gb: float = 0.10
    created: str | None = None
    daily_cost: dict = field(default_factory=dict)


@dataclass
class Collected:
    currency: str
    daily_total: dict  # ISO date -> whole-account cost that day
    machines: list
    disks: list
    warnings: list = field(default_factory=list)


def client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "CloudLens/1.0"})


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def usage_window() -> tuple[datetime, datetime]:
    end = utc_now()
    return end - timedelta(days=USAGE_DAYS), end


def cost_window() -> tuple[date, date]:
    """[start, end) for billing queries: the last COST_DAYS whole days, ending today."""
    end = utc_now().date()
    return end - timedelta(days=COST_DAYS), end


def raise_for_status(response: httpx.Response, what: str) -> None:
    """Turn provider HTTP errors into messages a person can act on."""
    if response.is_success:
        return
    if response.status_code in (401, 403):
        raise CloudError(f"The provider refused the keys while {what}. Check they were copied correctly and have the read-only permissions listed in the guide.")
    if response.status_code == 429:
        raise CloudError(f"The provider asked us to slow down while {what}. Try syncing again in a minute.")
    raise CloudError(f"The provider returned an error while {what} (HTTP {response.status_code}).")


# --- tags --------------------------------------------------------------------

ENVIRONMENT_WORDS = {
    "prod": "prod", "production": "prod", "live": "prod", "prd": "prod",
    "dev": "dev", "development": "dev", "sandbox": "dev",
    "test": "test", "testing": "test", "qa": "test", "uat": "test",
    "staging": "staging", "stage": "staging", "stg": "staging", "preprod": "staging",
}


def environment_from_tags(tags: dict) -> str:
    """Read an environment tag such as env=dev or Environment=Production. Untagged = unknown."""
    lowered = {k.lower(): str(v).lower() for k, v in (tags or {}).items()}
    for key in ("environment", "env", "stage", "tier"):
        if key in lowered:
            return ENVIRONMENT_WORDS.get(lowered[key], "unknown")
    return "unknown"


def team_from_tags(tags: dict) -> str:
    lowered = {k.lower(): str(v) for k, v in (tags or {}).items()}
    for key in ("team", "owner", "department", "project", "cost-center", "costcenter"):
        if lowered.get(key):
            return lowered[key].strip().lower()[:40]
    return "untagged"


# --- hourly utilization -> the daily rows the analysis expects ---------------


def daily_usage(cpu_hours: list, start: datetime, end: datetime) -> dict:
    """Summarise hourly processor readings into one row per day (in WORK_TIMEZONE).

    A missing hour means the machine was switched off, which counts as 0% and 0 hours.
    """
    days = {}
    day = start.astimezone(WORK_TIMEZONE).date()
    last = (end - timedelta(seconds=1)).astimezone(WORK_TIMEZONE).date()
    while day <= last:
        days[day] = {"busy": [0.0] * 24, "peak": 0.0, "hours": 0}
        day += timedelta(days=1)

    for when, average, maximum in cpu_hours:
        local = when.astimezone(WORK_TIMEZONE)
        slot = days.get(local.date())
        if slot is None:
            continue
        slot["busy"][local.hour] = float(average or 0.0)
        slot["peak"] = max(slot["peak"], float(maximum if maximum is not None else average or 0.0))
        slot["hours"] += 1

    rows = {}
    for day, slot in days.items():
        busy = slot["busy"]
        rows[day.isoformat()] = {
            "cpu_avg": round(sum(busy) / 24, 2),
            "cpu_p95": round(slot["peak"], 2),
            "cpu_business_hours": round(sum(busy[8:20]) / 12, 2),
            "cpu_off_hours": round((sum(busy[:8]) + sum(busy[20:])) / 12, 2),
            "hours_running": slot["hours"],
        }
    return rows


# --- rough list prices (USD, Linux, on-demand) for estimating per-server cost -----
# Used only when the provider does not report a per-resource cost. Shown as estimates.

AWS_HOURLY = {
    "t2.nano": 0.0058, "t2.micro": 0.0116, "t2.small": 0.023, "t2.medium": 0.0464, "t2.large": 0.0928, "t2.xlarge": 0.1856, "t2.2xlarge": 0.3712,
    "t3.nano": 0.0052, "t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416, "t3.large": 0.0832, "t3.xlarge": 0.1664, "t3.2xlarge": 0.3328,
    "t3a.nano": 0.0047, "t3a.micro": 0.0094, "t3a.small": 0.0188, "t3a.medium": 0.0376, "t3a.large": 0.0752, "t3a.xlarge": 0.1504, "t3a.2xlarge": 0.3008,
    "t4g.nano": 0.0042, "t4g.micro": 0.0084, "t4g.small": 0.0168, "t4g.medium": 0.0336, "t4g.large": 0.0672, "t4g.xlarge": 0.1344, "t4g.2xlarge": 0.2688,
    "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384, "m5.4xlarge": 0.768, "m5.8xlarge": 1.536,
    "m6i.large": 0.096, "m6i.xlarge": 0.192, "m6i.2xlarge": 0.384, "m6i.4xlarge": 0.768, "m6i.8xlarge": 1.536,
    "m7i.large": 0.1008, "m7i.xlarge": 0.2016, "m7i.2xlarge": 0.4032, "m7i.4xlarge": 0.8064,
    "c5.large": 0.085, "c5.xlarge": 0.17, "c5.2xlarge": 0.34, "c5.4xlarge": 0.68,
    "c6i.large": 0.085, "c6i.xlarge": 0.17, "c6i.2xlarge": 0.34, "c6i.4xlarge": 0.68,
    "r5.large": 0.126, "r5.xlarge": 0.252, "r5.2xlarge": 0.504, "r5.4xlarge": 1.008,
    "r6i.large": 0.126, "r6i.xlarge": 0.252, "r6i.2xlarge": 0.504, "r6i.4xlarge": 1.008,
}
AWS_PER_VCPU_HOUR = 0.048  # fallback for instance types not in the table

AZURE_HOURLY = {
    "Standard_B1ls": 0.0052, "Standard_B1s": 0.0104, "Standard_B1ms": 0.0207, "Standard_B2s": 0.0416, "Standard_B2ms": 0.0832,
    "Standard_B4ms": 0.166, "Standard_B8ms": 0.333,
    "Standard_D2s_v3": 0.096, "Standard_D4s_v3": 0.192, "Standard_D8s_v3": 0.384,
    "Standard_D2s_v5": 0.096, "Standard_D4s_v5": 0.192, "Standard_D8s_v5": 0.384, "Standard_D16s_v5": 0.768,
    "Standard_D2as_v5": 0.086, "Standard_D4as_v5": 0.172, "Standard_D8as_v5": 0.344,
    "Standard_E2s_v5": 0.126, "Standard_E4s_v5": 0.252, "Standard_E8s_v5": 0.504,
    "Standard_F2s_v2": 0.085, "Standard_F4s_v2": 0.169, "Standard_F8s_v2": 0.338,
}

GCP_HOURLY = {
    "e2-micro": 0.0084, "e2-small": 0.0168, "e2-medium": 0.0335,
    "e2-standard-2": 0.067, "e2-standard-4": 0.134, "e2-standard-8": 0.268, "e2-standard-16": 0.536,
    "n1-standard-1": 0.0475, "n1-standard-2": 0.095, "n1-standard-4": 0.19, "n1-standard-8": 0.38,
    "n2-standard-2": 0.0971, "n2-standard-4": 0.1942, "n2-standard-8": 0.3885, "n2-standard-16": 0.777,
    "n2d-standard-2": 0.0845, "n2d-standard-4": 0.169, "n2d-standard-8": 0.338,
    "c3-standard-4": 0.2094, "c3-standard-8": 0.4188,
}
GCP_PER_VCPU_HOUR = 0.0335


def list_price(provider: str, size: str) -> float | None:
    return {"aws": AWS_HOURLY, "azure": AZURE_HOURLY, "gcp": GCP_HOURLY}[provider].get(size)
