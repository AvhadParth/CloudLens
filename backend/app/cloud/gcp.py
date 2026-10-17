"""Google Cloud connector.

Credentials: a service account key (JSON) with these read-only roles on the project:
Compute Viewer, Monitoring Viewer, and (for the real bill) BigQuery Data Viewer plus
BigQuery Job User. Google Cloud only exposes daily costs through the "billing export to
BigQuery", so the bill is read from that table when its name is given; otherwise costs
are estimated from list prices.

  POST oauth2.googleapis.com/token                  swap a signed JWT for an access token
  GET  cloudresourcemanager .../projects/{id}       prove access, read the project name
  GET  compute .../aggregated/instances             servers, size, state, labels
  GET  compute .../aggregated/disks                 disks, attached or not
  GET  monitoring .../timeSeries                    hourly processor use for every server
  POST bigquery .../queries                         daily cost from the billing export
"""

import json
import re
import time
from datetime import datetime

import httpx
import jwt

from . import (
    GCP_PER_VCPU_HOUR,
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

TOKEN_URL = "https://oauth2.googleapis.com/token"  # fixed; never taken from the uploaded key file
PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
BILLING_TABLE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]\.[A-Za-z0-9_]{1,1024}\.[A-Za-z0-9_]{1,1024}$")
DISK_PER_GB_MONTH = {"pd-standard": 0.04, "pd-balanced": 0.10, "pd-ssd": 0.17, "pd-extreme": 0.125}


def check_credentials(credentials: dict) -> dict:
    raw = credentials.get("service_account_json") or ""
    if len(raw) > 10_000:
        raise CloudError("That key file is too large to be a service account key.")
    try:
        key = json.loads(raw)
    except ValueError:
        raise CloudError("Paste the whole service account key file. It is JSON that starts with {.") from None
    if key.get("type") != "service_account" or not key.get("private_key") or not key.get("client_email"):
        raise CloudError("That JSON is not a service account key. Download a new key for the service account and paste it.")
    project = (credentials.get("project_id") or key.get("project_id") or "").strip()
    if not PROJECT.match(project):
        raise CloudError("That project ID does not look right, e.g. my-project-123456.")
    table = (credentials.get("billing_table") or "").strip().strip("`")
    if table and not BILLING_TABLE.match(table):
        raise CloudError("The billing export table should look like project.dataset.gcp_billing_export_v1_XXXXXX.")
    return {
        "service_account_json": json.dumps({k: key[k] for k in ("type", "client_email", "private_key", "private_key_id") if k in key}),
        "project_id": project,
        "billing_table": table,
    }


def hint(credentials: dict) -> str:
    return json.loads(credentials["service_account_json"])["client_email"]


class _Session:
    def __init__(self, credentials: dict, http: httpx.Client):
        self.http, self.project = http, credentials["project_id"]
        key = json.loads(credentials["service_account_json"])
        now = int(time.time())
        try:
            assertion = jwt.encode(
                {"iss": key["client_email"], "scope": "https://www.googleapis.com/auth/cloud-platform",
                 "aud": TOKEN_URL, "iat": now, "exp": now + 3600},
                key["private_key"], algorithm="RS256", headers={"kid": key.get("private_key_id")},
            )
        except (ValueError, TypeError):
            raise CloudError("The private key in that file could not be read. Download a fresh key and try again.") from None
        response = http.post(TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
        if response.status_code in (400, 401):
            raise CloudError("Google refused the key. It may have been deleted or disabled.")
        raise_for_status(response, "signing in to Google Cloud")
        self.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    def get(self, url: str, what: str, params=None) -> dict:
        response = self.http.get(url, headers=self.headers, params=params)
        raise_for_status(response, what)
        return response.json()


def validate(credentials: dict, http: httpx.Client) -> AccountInfo:
    session = _Session(credentials, http)
    body = session.get(f"https://cloudresourcemanager.googleapis.com/v1/projects/{session.project}", "opening the project")
    return AccountInfo(account_ref=session.project, display_name=body.get("name") or session.project)


def _aggregated(session: _Session, kind: str, what: str) -> list:
    url = f"https://compute.googleapis.com/compute/v1/projects/{session.project}/aggregated/{kind}"
    items, token = [], None
    while True:
        body = session.get(url, what, params={"maxResults": 500, **({"pageToken": token} if token else {})})
        for scope in body.get("items", {}).values():
            items.extend(scope.get(kind, []))
        token = body.get("nextPageToken")
        if not token:
            return items


def _cpu_series(session: _Session, start: datetime, end: datetime, aligner: str) -> dict:
    """instance id -> {hour: value %} for every server in the project, in one paginated call."""
    url = f"https://monitoring.googleapis.com/v3/projects/{session.project}/timeSeries"
    params = {
        "filter": 'metric.type="compute.googleapis.com/instance/cpu/utilization"',
        "interval.startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interval.endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aggregation.alignmentPeriod": "3600s", "aggregation.perSeriesAligner": aligner, "pageSize": 100000,
    }
    series, token = {}, None
    while True:
        body = session.get(url, "reading processor use", params={**params, **({"pageToken": token} if token else {})})
        for item in body.get("timeSeries", []):
            values = series.setdefault(item["resource"]["labels"]["instance_id"], {})
            for point in item.get("points", []):
                when = datetime.fromisoformat(point["interval"]["endTime"].replace("Z", "+00:00"))
                values[when] = float(point["value"].get("doubleValue", 0)) * 100
        token = body.get("nextPageToken")
        if not token:
            return series


def _billing_export(session: _Session, table: str) -> tuple[dict, str]:
    start, end = cost_window()
    query = (
        "SELECT FORMAT_DATE('%Y-%m-%d', DATE(usage_start_time)) AS day, "
        "SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS cost, "
        f"ANY_VALUE(currency) AS currency FROM `{table}` "
        "WHERE project.id = @project AND usage_start_time >= TIMESTAMP(@start) AND usage_start_time < TIMESTAMP(@end) "
        "GROUP BY day ORDER BY day"
    )
    payload = {
        "query": query, "useLegacySql": False, "timeoutMs": 25000, "parameterMode": "NAMED",
        "queryParameters": [
            {"name": name, "parameterType": {"type": "STRING"}, "parameterValue": {"value": value}}
            for name, value in (("project", session.project), ("start", start.isoformat()), ("end", end.isoformat()))
        ],
    }
    response = session.http.post(f"https://bigquery.googleapis.com/bigquery/v2/projects/{session.project}/queries",
                                 headers=session.headers, json=payload)
    raise_for_status(response, "reading the bill from the BigQuery billing export")
    body = response.json()
    if not body.get("jobComplete", True):
        raise CloudError("The billing export query took too long. Try syncing again.")
    totals, currency = {}, "USD"
    for row in body.get("rows", []):
        day, cost, unit = (cell.get("v") for cell in row["f"])
        totals[day] = float(cost or 0)
        currency = unit or currency
    return totals, currency


def collect(credentials: dict, http: httpx.Client) -> Collected:
    session = _Session(credentials, http)
    start, end = usage_window()
    averages = _cpu_series(session, start, end, "ALIGN_MEAN")
    peaks = _cpu_series(session, start, end, "ALIGN_MAX")

    machines = []
    for item in _aggregated(session, "instances", "listing servers"):
        size = item.get("machineType", "").rsplit("/", 1)[-1]
        vcpus = int(size.rsplit("-", 1)[-1]) if size.rsplit("-", 1)[-1].isdigit() else None
        hours = averages.get(str(item["id"]), {})
        machines.append(Machine(
            native_id=str(item["id"]), name=item["name"], region=item.get("zone", "").rsplit("/", 1)[-1], size=size,
            running=item.get("status") == "RUNNING", tags=item.get("labels") or {},
            hourly_rate=list_price("gcp", size) or (vcpus * GCP_PER_VCPU_HOUR if vcpus else None), vcpus=vcpus,
            created=(item.get("creationTimestamp") or "")[:10] or None,
            cpu_hours=[(when, value, peaks.get(str(item["id"]), {}).get(when, value)) for when, value in sorted(hours.items())],
        ))

    disks = []
    for item in _aggregated(session, "disks", "listing disks"):
        users = item.get("users") or []
        kind = item.get("type", "").rsplit("/", 1)[-1]
        disks.append(Disk(
            native_id=str(item["id"]), name=item["name"], region=item.get("zone", "").rsplit("/", 1)[-1],
            size_gb=float(item.get("sizeGb") or 0), attached_to=users[0].rsplit("/", 1)[-1] if users else None,
            tags=item.get("labels") or {}, monthly_rate_per_gb=DISK_PER_GB_MONTH.get(kind, 0.10),
            created=(item.get("creationTimestamp") or "")[:10] or None,
        ))

    warnings = ["Memory use is not read from Google Cloud yet, so the memory checks are skipped."]
    if credentials.get("billing_table"):
        totals, currency = _billing_export(session, credentials["billing_table"])
    else:
        totals, currency = {}, "USD"
        warnings.append("No billing export table was given, so costs are estimated from list prices for the last 30 days only.")
    return Collected(currency=currency, daily_total=totals, machines=machines, disks=disks, warnings=warnings)
