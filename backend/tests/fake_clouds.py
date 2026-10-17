"""Stand-ins for the AWS, Azure and Google Cloud APIs, so the connectors can be tested
without real accounts. Each fake answers the same requests, in the same formats, that the
real services do (as documented), with a small made-up account:

  old-report  switched on, almost no processor use            -> "not used"
  web-main    busy all day                                    -> healthy
  dev-box     tagged env=dev, busy 08-20 IST on weekdays only -> "left on overnight"
  big-batch   large machine that never passes 25%             -> "too big"
  orphan-disk 500 GB disk attached to nothing                  -> "storage nobody uses"
"""

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import httpx

IST = ZoneInfo("Asia/Kolkata")
DAILY_BILL = 30.0  # what each fake provider says the whole account cost per day


def cpu(profile: str, when: datetime) -> tuple[float, float]:
    """(average, maximum) processor % for one hour."""
    local = when.astimezone(IST)
    working = local.weekday() < 5 and 8 <= local.hour < 20
    return {
        "idle": (1.0, 3.0),
        "busy": (60.0, 90.0),
        "dev": (40.0, 70.0) if working else (1.0, 2.0),
        "big": (15.0, 25.0),
    }[profile]


def hours(start: datetime, end: datetime):
    when = start.replace(minute=0, second=0, microsecond=0)
    while when < end:
        yield when
        when += timedelta(hours=1)


def days(start: str, end: str):
    day = datetime.fromisoformat(start).date()
    last = datetime.fromisoformat(end).date()
    while day < last:
        yield day
        day += timedelta(days=1)


def bill(day) -> float:
    return DAILY_BILL - (4.0 if day.weekday() >= 5 else 0.0)


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


# --- AWS --------------------------------------------------------------------------

AWS_KEYS = {"access_key_id": "AKIAABCDEFGHIJKLMNOP", "secret_access_key": "s" * 40}
AWS_MACHINES = {
    "i-0idle": ("old-report", "t3.large", "idle", {"env": "prod"}),
    "i-0busy": ("web-main", "m5.xlarge", "busy", {"env": "prod", "team": "web"}),
    "i-0dev": ("dev-box", "t3.medium", "dev", {"env": "dev", "team": "web"}),
    "i-0big": ("big-batch", "m5.2xlarge", "big", {"Environment": "Production"}),
}


def _xml(root: str, body: str, ns: str) -> httpx.Response:
    return httpx.Response(200, text=f'<{root} xmlns="{ns}">{body}</{root}>')


def _tags(tags: dict) -> str:
    return "<tagSet>" + "".join(f"<item><key>{k}</key><value>{v}</value></item>" for k, v in tags.items()) + "</tagSet>"


def aws_handler(refuse: bool = False):
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIAABCDEFGHIJKLMNOP/")
        host = request.url.host
        if refuse:
            return httpx.Response(403, text="<Error><Code>InvalidClientTokenId</Code></Error>")
        if host == "ce.us-east-1.amazonaws.com":
            assert request.headers["x-amz-target"] == "AWSInsightsIndexService.GetCostAndUsage"
            period = json.loads(request.content)["TimePeriod"]
            results = [
                {"TimePeriod": {"Start": d.isoformat(), "End": (d + timedelta(days=1)).isoformat()},
                 "Total": {"UnblendedCost": {"Amount": str(bill(d)), "Unit": "USD"}}}
                for d in days(period["Start"], period["End"])
            ]
            return httpx.Response(200, json={"ResultsByTime": results})

        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        action = form["Action"]
        if action == "GetCallerIdentity":
            return _xml("GetCallerIdentityResponse", "<GetCallerIdentityResult><Account>123456789012</Account></GetCallerIdentityResult>",
                        "https://sts.amazonaws.com/doc/2011-06-15/")
        ns = "http://ec2.amazonaws.com/doc/2016-11-15/"
        region = host.split(".")[1]
        if action == "DescribeRegions":
            items = "".join(f"<item><regionName>{r}</regionName></item>" for r in ("us-east-1", "ap-south-1"))
            return _xml("DescribeRegionsResponse", f"<regionInfo>{items}</regionInfo>", ns)
        if action == "DescribeInstances":
            items = "" if region != "us-east-1" else "".join(
                f"<item><instanceId>{iid}</instanceId><instanceType>{size}</instanceType>"
                f"<instanceState><name>running</name></instanceState><launchTime>2026-01-05T10:00:00.000Z</launchTime>"
                f"<cpuOptions><coreCount>2</coreCount><threadsPerCore>2</threadsPerCore></cpuOptions>{_tags({'Name': name, **tags})}</item>"
                for iid, (name, size, _, tags) in AWS_MACHINES.items()
            )
            return _xml("DescribeInstancesResponse", f"<reservationSet><item><instancesSet>{items}</instancesSet></item></reservationSet>", ns)
        if action == "DescribeVolumes":
            items = "" if region != "us-east-1" else (
                f"<item><volumeId>vol-orphan</volumeId><size>500</size><volumeType>gp3</volumeType>"
                f"<createTime>2025-12-01T00:00:00.000Z</createTime><attachmentSet/>{_tags({'Name': 'orphan-disk'})}</item>"
                f"<item><volumeId>vol-root</volumeId><size>8</size><volumeType>gp3</volumeType>"
                f"<attachmentSet><item><instanceId>i-0busy</instanceId></item></attachmentSet></item>"
            )
            return _xml("DescribeVolumesResponse", f"<volumeSet>{items}</volumeSet>", ns)
        if action == "GetMetricStatistics":
            profile = AWS_MACHINES[form["Dimensions.member.1.Value"]][2]
            points = "".join(
                f"<member><Timestamp>{h.strftime('%Y-%m-%dT%H:%M:%SZ')}</Timestamp><Average>{cpu(profile, h)[0]}</Average>"
                f"<Maximum>{cpu(profile, h)[1]}</Maximum><Unit>Percent</Unit></member>"
                for h in hours(_parse(form["StartTime"]), _parse(form["EndTime"]))
            )
            return _xml("GetMetricStatisticsResponse", f"<GetMetricStatisticsResult><Datapoints>{points}</Datapoints></GetMetricStatisticsResult>",
                        "http://monitoring.amazonaws.com/doc/2010-08-01/")
        raise AssertionError(f"unexpected AWS call {action}")

    return handle


# --- Azure ------------------------------------------------------------------------

AZURE_KEYS = {
    "tenant_id": "11111111-2222-3333-4444-555555555555",
    "client_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "client_secret": "a-very-secret-value",
    "subscription_id": "99999999-8888-7777-6666-555555555555",
}
SUB = f"/subscriptions/{AZURE_KEYS['subscription_id']}"
AZURE_MACHINES = {
    "old-report": ("Standard_D2s_v5", "idle", {}),
    "web-main": ("Standard_D4s_v5", "busy", {"env": "prod"}),
    "dev-box": ("Standard_B2ms", "dev", {"environment": "dev"}),
    "big-batch": ("Standard_D8s_v5", "big", {"env": "prod"}),
}


def _vm_id(name: str) -> str:
    return f"{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/{name}"


def azure_handler():
    def handle(request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "token", "token_type": "Bearer", "expires_in": 3599})
        assert request.headers["authorization"] == "Bearer token"
        path = url.path
        if path == SUB:
            return httpx.Response(200, json={"subscriptionId": AZURE_KEYS["subscription_id"], "displayName": "Student subscription"})
        if path.endswith("/providers/Microsoft.Compute/virtualMachines"):
            return httpx.Response(200, json={"value": [
                {"id": _vm_id(n), "name": n, "location": "centralindia", "tags": t,
                 "properties": {"hardwareProfile": {"vmSize": size}, "timeCreated": "2026-02-01T00:00:00Z"}}
                for n, (size, _, t) in AZURE_MACHINES.items()
            ]})
        if path.endswith("/providers/Microsoft.Compute/disks"):
            return httpx.Response(200, json={"value": [
                {"id": f"{SUB}/resourceGroups/rg/providers/Microsoft.Compute/disks/orphan-disk", "name": "orphan-disk",
                 "location": "centralindia", "properties": {"diskSizeGB": 500, "diskState": "Unattached"}},
                {"id": f"{SUB}/resourceGroups/rg/providers/Microsoft.Compute/disks/web-os", "name": "web-os",
                 "location": "centralindia", "managedBy": _vm_id("web-main"), "properties": {"diskSizeGB": 64, "diskState": "Attached"}},
            ]})
        if path.endswith("/providers/Microsoft.Insights/metrics"):
            assert url.params["metricnames"] == "Percentage CPU"
            name = path.split("/virtualMachines/")[1].split("/")[0]
            profile = AZURE_MACHINES[name][1]
            start, end = (_parse(x) for x in url.params["timespan"].split("/"))
            data = [{"timeStamp": h.strftime("%Y-%m-%dT%H:%M:%SZ"), "average": cpu(profile, h)[0], "maximum": cpu(profile, h)[1]}
                    for h in hours(start, end)]
            return httpx.Response(200, json={"value": [{"name": {"value": "Percentage CPU"}, "timeseries": [{"data": data}]}]})
        if path.endswith("/providers/Microsoft.CostManagement/query"):
            body = json.loads(request.content)
            period = body["timePeriod"]
            first, last = period["from"][:10], (_parse(period["to"]) + timedelta(seconds=1)).date().isoformat()
            grouped = "grouping" in body["dataset"]
            rows = []
            for d in days(first, last):
                stamp = int(d.strftime("%Y%m%d"))
                if grouped:  # real per-resource cost: 3/day per VM, 1.5/day for the orphan disk
                    rows += [[3.0, stamp, _vm_id(n).lower(), "USD"] for n in AZURE_MACHINES]
                    rows.append([1.5, stamp, f"{SUB}/resourceGroups/rg/providers/Microsoft.Compute/disks/orphan-disk".lower(), "USD"])
                else:
                    rows.append([bill(d), stamp, "USD"])
            columns = [{"name": "Cost"}, {"name": "UsageDate"}] + ([{"name": "ResourceId"}] if grouped else []) + [{"name": "Currency"}]
            return httpx.Response(200, json={"properties": {"columns": columns, "rows": rows}})
        raise AssertionError(f"unexpected Azure call {path}")

    return handle


# --- Google Cloud -----------------------------------------------------------------

GCP_MACHINES = {
    "101": ("old-report", "e2-standard-2", "idle", {}),
    "102": ("web-main", "n2-standard-4", "busy", {"env": "prod"}),
    "103": ("dev-box", "e2-standard-2", "dev", {"env": "dev"}),
    "104": ("big-batch", "n2-standard-8", "big", {"env": "prod"}),
}


def gcp_keys() -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return {
        "service_account_json": json.dumps({
            "type": "service_account", "project_id": "student-project-1", "private_key_id": "abc",
            "private_key": pem, "client_email": "cloudlens@student-project-1.iam.gserviceaccount.com",
            "token_uri": "https://evil.example.com/token",  # must be ignored
        }),
        "billing_table": "student-project-1.billing.gcp_billing_export_v1_0000",
    }


def gcp_handler():
    def handle(request: httpx.Request) -> httpx.Response:
        url = request.url
        assert url.host != "evil.example.com"
        if url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3599})
        assert request.headers["authorization"] == "Bearer token"
        if url.host == "cloudresourcemanager.googleapis.com":
            return httpx.Response(200, json={"projectId": "student-project-1", "name": "Student Project"})
        if url.path.endswith("/aggregated/instances"):
            items = [{"id": iid, "name": n, "machineType": f"zones/asia-south1-a/machineTypes/{size}", "status": "RUNNING",
                      "zone": "zones/asia-south1-a", "labels": labels, "creationTimestamp": "2026-03-01T00:00:00.000-07:00"}
                     for iid, (n, size, _, labels) in GCP_MACHINES.items()]
            return httpx.Response(200, json={"items": {"zones/asia-south1-a": {"instances": items}}})
        if url.path.endswith("/aggregated/disks"):
            disks = [{"id": "201", "name": "orphan-disk", "sizeGb": "500", "type": "zones/x/diskTypes/pd-balanced", "zone": "zones/asia-south1-a"},
                     {"id": "202", "name": "web-boot", "sizeGb": "20", "type": "zones/x/diskTypes/pd-balanced", "zone": "zones/asia-south1-a",
                      "users": ["projects/p/zones/z/instances/web-main"]}]
            return httpx.Response(200, json={"items": {"zones/asia-south1-a": {"disks": disks}}})
        if url.host == "monitoring.googleapis.com":
            column = 0 if url.params["aggregation.perSeriesAligner"] == "ALIGN_MEAN" else 1
            start, end = _parse(url.params["interval.startTime"]), _parse(url.params["interval.endTime"])
            series = [{"resource": {"labels": {"instance_id": iid}},
                       "points": [{"interval": {"endTime": h.strftime("%Y-%m-%dT%H:%M:%SZ")}, "value": {"doubleValue": cpu(p, h)[column] / 100}}
                                  for h in hours(start, end)]}
                      for iid, (_, _, p, _) in GCP_MACHINES.items()]
            return httpx.Response(200, json={"timeSeries": series})
        if url.host == "bigquery.googleapis.com":
            body = json.loads(request.content)
            assert "`student-project-1.billing.gcp_billing_export_v1_0000`" in body["query"]
            params = {p["name"]: p["parameterValue"]["value"] for p in body["queryParameters"]}
            rows = [{"f": [{"v": d.isoformat()}, {"v": str(bill(d))}, {"v": "USD"}]} for d in days(params["start"], params["end"])]
            return httpx.Response(200, json={"jobComplete": True, "rows": rows})
        raise AssertionError(f"unexpected Google Cloud call {url}")

    return handle


def http_client(handler):
    return lambda: httpx.Client(transport=httpx.MockTransport(handler))

