"""Microsoft Azure connector.

Credentials: a service principal (an app identity) with the built-in "Reader" role on one
subscription. Reader can see resources, metrics and cost data, and cannot change anything.

  POST login.microsoftonline.com/{tenant}/oauth2/v2.0/token   get an access token
  GET  /subscriptions/{id}                                    prove access, read the name
  GET  .../Microsoft.Compute/virtualMachines                  servers, size, tags
  GET  .../Microsoft.Compute/disks                            disks, attached or not
  GET  {vm}/providers/Microsoft.Insights/metrics              hourly processor use
  POST .../Microsoft.CostManagement/query                     the real daily bill, per resource
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import httpx

from . import (
    USAGE_DAYS,
    AccountInfo,
    CloudError,
    Collected,
    Disk,
    Machine,
    cost_window,
    list_price,
    raise_for_status,
    usage_window,
)

ARM = "https://management.azure.com"
GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
COST_CHUNK_DAYS = 90  # Cost Management limits how much one query may cover
MANAGED_DISK_PER_GB_MONTH = 0.10


def check_credentials(credentials: dict) -> dict:
    cleaned = {k: (credentials.get(k) or "").strip() for k in ("tenant_id", "client_id", "client_secret", "subscription_id")}
    for field, label in (("tenant_id", "Tenant ID"), ("client_id", "Client ID"), ("subscription_id", "Subscription ID")):
        if not GUID.match(cleaned[field]):
            raise CloudError(f"That {label} does not look right. It is a GUID like 1a2b3c4d-1111-2222-3333-444455556666.")
    if not 8 <= len(cleaned["client_secret"]) <= 200:
        raise CloudError("That client secret does not look right.")
    return cleaned


def hint(credentials: dict) -> str:
    return f"app {credentials['client_id'][:8]}…"


class _Session:
    """Holds the access token and sends authorised requests to Azure Resource Manager."""

    def __init__(self, credentials: dict, http: httpx.Client):
        self.http, self.subscription = http, credentials["subscription_id"]
        response = http.post(
            f"https://login.microsoftonline.com/{credentials['tenant_id']}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": credentials["client_id"],
                  "client_secret": credentials["client_secret"], "scope": f"{ARM}/.default"},
        )
        if response.status_code in (400, 401):
            raise CloudError("Azure refused the sign-in. Check the tenant ID, client ID and client secret.")
        raise_for_status(response, "signing in to Azure")
        self.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    def get(self, url: str, what: str, **params) -> dict:
        response = self.http.get(url if url.startswith("http") else ARM + url, headers=self.headers, params=params or None)
        raise_for_status(response, what)
        return response.json()

    def pages(self, path: str, api_version: str, what: str) -> list:
        items, body = [], self.get(path, what, **{"api-version": api_version})
        while True:
            items.extend(body.get("value", []))
            if not body.get("nextLink"):
                return items
            body = self.get(body["nextLink"], what)

    def post(self, path: str, api_version: str, payload: dict, what: str) -> dict:
        for _ in range(2):
            response = self.http.post(ARM + path, params={"api-version": api_version}, json=payload, headers=self.headers)
            if response.status_code == 429:  # Cost Management is strict about rate; wait once, then retry
                time.sleep(min(int(response.headers.get("retry-after", "10")), 20))
                continue
            break
        raise_for_status(response, what)
        return response.json()


def validate(credentials: dict, http: httpx.Client) -> AccountInfo:
    session = _Session(credentials, http)
    body = session.get(f"/subscriptions/{session.subscription}", "opening the subscription", **{"api-version": "2022-12-01"})
    return AccountInfo(account_ref=session.subscription, display_name=body.get("displayName") or "Azure subscription")


def _cost_rows(session: _Session, start: date, end: date, by_resource: bool) -> tuple[list, str]:
    """Daily ActualCost for [start, end), optionally split by resource id."""
    rows, currency, chunk_start = [], "USD", start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=COST_CHUNK_DAYS), end)
        dataset = {"granularity": "Daily", "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}}
        if by_resource:
            dataset["grouping"] = [{"type": "Dimension", "name": "ResourceId"}]
        body = session.post(
            f"/subscriptions/{session.subscription}/providers/Microsoft.CostManagement/query", "2023-11-01",
            {"type": "ActualCost", "timeframe": "Custom", "dataset": dataset,
             "timePeriod": {"from": f"{chunk_start.isoformat()}T00:00:00Z", "to": f"{(chunk_end - timedelta(days=1)).isoformat()}T23:59:59Z"}},
            "reading the bill from Cost Management",
        )
        properties = body.get("properties", {})
        names = [c["name"] for c in properties.get("columns", [])]
        for row in properties.get("rows", []):
            record = dict(zip(names, row))
            day = str(record.get("UsageDate"))
            record["day"] = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
            currency = record.get("Currency") or currency
            rows.append(record)
        chunk_start = chunk_end
    return rows, currency


def _cpu_hours(session: _Session, vm_id: str, start: datetime, end: datetime) -> list:
    body = session.get(
        f"{vm_id}/providers/Microsoft.Insights/metrics", "reading processor use",
        **{"api-version": "2023-10-01", "metricnames": "Percentage CPU", "interval": "PT1H",
           "aggregation": "Average,Maximum",
           "timespan": f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}"},
    )
    points = []
    for series in (body.get("value") or [{}])[0].get("timeseries", []):
        for point in series.get("data", []):
            if point.get("average") is None:
                continue  # no reading: the machine was off that hour
            when = datetime.fromisoformat(point["timeStamp"].replace("Z", "+00:00"))
            points.append((when, point["average"], point.get("maximum")))
    return points


def collect(credentials: dict, http: httpx.Client) -> Collected:
    session = _Session(credentials, http)
    sub = f"/subscriptions/{session.subscription}"
    start, end = usage_window()

    vms = session.pages(f"{sub}/providers/Microsoft.Compute/virtualMachines", "2024-07-01", "listing servers")
    raw_disks = session.pages(f"{sub}/providers/Microsoft.Compute/disks", "2024-03-02", "listing disks")

    cost_start, cost_end = cost_window()
    totals, currency = _cost_rows(session, cost_start, cost_end, by_resource=False)
    per_resource, _ = _cost_rows(session, cost_end - timedelta(days=USAGE_DAYS + 1), cost_end, by_resource=True)
    resource_cost = {}
    for row in per_resource:
        resource_cost.setdefault(str(row.get("ResourceId", "")).lower(), {})[row["day"]] = float(row["Cost"])

    machines = []
    for vm in vms:
        size = vm.get("properties", {}).get("hardwareProfile", {}).get("vmSize", "")
        machines.append(Machine(
            native_id=vm["id"], name=vm["name"], region=vm.get("location", ""), size=size, running=True,
            tags=vm.get("tags") or {}, hourly_rate=list_price("azure", size),
            created=(vm.get("properties", {}).get("timeCreated") or "")[:10] or None,
            daily_cost=resource_cost.get(vm["id"].lower(), {}),
        ))
    with ThreadPoolExecutor(max_workers=8) as pool:
        for machine, hours in zip(machines, pool.map(lambda m: _cpu_hours(session, m.native_id, start, end), machines)):
            machine.cpu_hours = hours
            machine.running = bool(hours)

    disks = []
    for disk in raw_disks:
        props = disk.get("properties", {})
        unattached = props.get("diskState") == "Unattached"
        disks.append(Disk(
            native_id=disk["id"], name=disk["name"], region=disk.get("location", ""),
            size_gb=float(props.get("diskSizeGB") or 0),
            attached_to=None if unattached else (disk.get("managedBy") or "attached"), tags=disk.get("tags") or {},
            monthly_rate_per_gb=MANAGED_DISK_PER_GB_MONTH, created=(props.get("timeCreated") or "")[:10] or None,
            daily_cost=resource_cost.get(disk["id"].lower(), {}),
        ))

    daily_total = {}
    for row in totals:
        daily_total[row["day"]] = daily_total.get(row["day"], 0.0) + float(row["Cost"])
    warnings = ["Memory use is not read from Azure yet, so the memory checks are skipped."]
    return Collected(currency=currency, daily_total=daily_total, machines=machines, disks=disks, warnings=warnings)
