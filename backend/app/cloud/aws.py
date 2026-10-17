"""Amazon Web Services connector.

Credentials: an access key for an IAM user that only has the read-only permissions in
POLICY below. Calls used:

  sts:GetCallerIdentity          prove the keys work, learn the account id (free)
  ec2:DescribeRegions            which regions to look in
  ec2:DescribeInstances          servers, their size, state and tags
  ec2:DescribeVolumes            disks, and whether each is attached to anything
  cloudwatch:GetMetricStatistics hourly processor use for each running server
  ce:GetCostAndUsage             the real daily bill (AWS charges $0.01 per call; one per sync)

Requests are signed with AWS Signature Version 4, implemented below in a few lines.
"""

import hashlib
import hmac
import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from . import (
    AWS_PER_VCPU_HOUR,
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

POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "CloudLensReadOnly",
            "Effect": "Allow",
            "Action": [
                "ce:GetCostAndUsage",
                "ec2:DescribeRegions",
                "ec2:DescribeInstances",
                "ec2:DescribeVolumes",
                "cloudwatch:GetMetricStatistics",
            ],
            "Resource": "*",
        }
    ],
}

ACCESS_KEY = re.compile(r"^(AKIA|ASIA)[A-Z0-9]{16}$")
EBS_PER_GB_MONTH = {"gp2": 0.10, "gp3": 0.08, "io1": 0.125, "io2": 0.125, "st1": 0.045, "sc1": 0.015, "standard": 0.05}


def check_credentials(credentials: dict) -> dict:
    key = (credentials.get("access_key_id") or "").strip()
    secret = (credentials.get("secret_access_key") or "").strip()
    if not ACCESS_KEY.match(key):
        raise CloudError("That access key ID does not look right. It starts with AKIA and is 20 characters long.")
    if len(secret) != 40:
        raise CloudError("That secret access key does not look right. It is 40 characters long.")
    return {"access_key_id": key, "secret_access_key": secret}


def hint(credentials: dict) -> str:
    key = credentials["access_key_id"]
    return f"{key[:4]}…{key[-4:]}"


# --- Signature Version 4 ------------------------------------------------------


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def signed_request(http: httpx.Client, credentials: dict, *, service: str, region: str, host: str,
                   method: str = "POST", body: str = "", headers: dict | None = None) -> httpx.Response:
    """Send one request signed with AWS Signature Version 4."""
    now = datetime.now(timezone.utc)
    amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    headers = {"host": host, "x-amz-date": amz_date, **{k.lower(): v for k, v in (headers or {}).items()}}
    payload_hash = hashlib.sha256(body.encode()).hexdigest()
    signed_names = ";".join(sorted(headers))
    canonical = "\n".join([
        method, "/", "",
        "".join(f"{name}:{headers[name].strip()}\n" for name in sorted(headers)),
        signed_names, payload_hash,
    ])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _sign(_sign(_sign(_sign(("AWS4" + credentials["secret_access_key"]).encode(), day), region), service), "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={credentials['access_key_id']}/{scope}, "
        f"SignedHeaders={signed_names}, Signature={signature}"
    )
    return http.request(method, f"https://{host}/", content=body.encode(), headers=headers)


class Blocked(CloudError):
    """AWS refused one permission. `who` says what denied it: the organization, a boundary, or the IAM policy."""

    def __init__(self, action: str, who: str):
        self.action, self.who = action, who
        super().__init__(explain(who, [action]))


def explain(who: str, actions: list) -> str:
    names = " and ".join(sorted(set(actions)))
    if who == "organization":
        return (f"your AWS organization blocks {names} with a service control policy. This is common for college, "
                "AWS Academy and other managed accounts, and only the organization's admin can change it")
    if who == "boundary":
        return f"a permissions boundary on the IAM user blocks {names}"
    return f"the IAM user is missing {names} from the policy in the guide"


def _check(response: httpx.Response, action: str, what: str) -> None:
    """Like raise_for_status, but tells a missing permission apart from bad keys, and says who denied it."""
    denied = re.search(r"UnauthorizedOperation|AccessDenied|not authorized to perform", response.text)
    if response.status_code in (400, 403) and denied:
        if "service control policy" in response.text:
            raise Blocked(action, "organization")
        if "permissions boundary" in response.text:
            raise Blocked(action, "boundary")
        raise Blocked(action, "policy")
    raise_for_status(response, what)


def _summarise(blocks: list) -> str:
    """One sentence per kind of denial, naming every blocked permission once."""
    by_who = {}
    for block in blocks:
        by_who.setdefault(block.who, []).append(block.action)
    return "; ".join(explain(who, actions) for who, actions in by_who.items())


SERVICE_PREFIX = {"ec2": "ec2", "monitoring": "cloudwatch", "sts": "sts"}


def _query(http, credentials, service, region, host, params: dict, what: str) -> ET.Element:
    """Call an AWS "Query" API (form-encoded request, XML response) and return the XML root."""
    body = "&".join(f"{quote(str(k), safe='')}={quote(str(v), safe='')}" for k, v in sorted(params.items()))
    response = signed_request(http, credentials, service=service, region=region, host=host, body=body,
                              headers={"content-type": "application/x-www-form-urlencoded; charset=utf-8"})
    _check(response, f"{SERVICE_PREFIX[service]}:{params['Action']}", what)
    root = ET.fromstring(response.text)
    for element in root.iter():  # drop XML namespaces so paths stay readable
        element.tag = element.tag.split("}", 1)[-1]
    return root


def _ec2(http, credentials, region, params, what):
    return _query(http, credentials, "ec2", region, f"ec2.{region}.amazonaws.com", {"Version": "2016-11-15", **params}, what)


# --- validate -----------------------------------------------------------------


def validate(credentials: dict, http: httpx.Client) -> AccountInfo:
    root = _query(http, credentials, "sts", "us-east-1", "sts.amazonaws.com",
                  {"Action": "GetCallerIdentity", "Version": "2011-06-15"}, "opening the account")
    account = root.findtext(".//Account")
    if not account:
        raise CloudError("AWS did not say which account these keys belong to.")
    return AccountInfo(account_ref=account, display_name=f"AWS account {account}")


# --- collect ------------------------------------------------------------------


def _tags(item: ET.Element) -> dict:
    return {t.findtext("key"): t.findtext("value") or "" for t in item.findall("./tagSet/item")}


def _regions(http, credentials) -> list[str]:
    root = _ec2(http, credentials, "us-east-1", {"Action": "DescribeRegions"}, "listing regions")
    return sorted(r.findtext("regionName") for r in root.findall(".//regionInfo/item"))


def _all_pages(http, credentials, region, action, what):
    token, pages = None, []
    while True:
        params = {"Action": action, "MaxResults": 500}
        if token:
            params["NextToken"] = token
        root = _ec2(http, credentials, region, params, what)
        pages.append(root)
        token = root.findtext("nextToken")
        if not token:
            return pages


def _machines_and_disks(http, credentials, region):
    """Servers and disks in one region, plus the reasons for anything AWS refused to list."""
    machines, disks, blocked = [], [], []
    try:
        machines = _machines(http, credentials, region)
    except Blocked as block:
        blocked.append(block)
    try:
        disks = _disks(http, credentials, region)
    except Blocked as block:
        blocked.append(block)
    return machines, disks, blocked


def _machines(http, credentials, region) -> list:
    machines = []
    for page in _all_pages(http, credentials, region, "DescribeInstances", f"listing servers in {region}"):
        for item in page.findall("./reservationSet/item/instancesSet/item"):
            state = item.findtext("./instanceState/name")
            if state in ("terminated", "shutting-down"):
                continue
            size = item.findtext("instanceType") or ""
            cores = item.findtext("./cpuOptions/coreCount")
            threads = item.findtext("./cpuOptions/threadsPerCore") or "1"
            vcpus = int(cores) * int(threads) if cores else None
            tags = _tags(item)
            rate = list_price("aws", size) or (vcpus * AWS_PER_VCPU_HOUR if vcpus else None)
            machines.append(Machine(
                native_id=item.findtext("instanceId"), name=tags.get("Name") or item.findtext("instanceId"),
                region=region, size=size, running=state == "running", tags=tags, hourly_rate=rate, vcpus=vcpus,
                created=(item.findtext("launchTime") or "")[:10] or None,
            ))
    return machines


def _disks(http, credentials, region) -> list:
    disks = []
    for page in _all_pages(http, credentials, region, "DescribeVolumes", f"listing disks in {region}"):
        for item in page.findall("./volumeSet/item"):
            tags = _tags(item)
            attached = item.findtext("./attachmentSet/item/instanceId")
            disks.append(Disk(
                native_id=item.findtext("volumeId"), name=tags.get("Name") or item.findtext("volumeId"), region=region,
                size_gb=float(item.findtext("size") or 0), attached_to=attached, tags=tags,
                monthly_rate_per_gb=EBS_PER_GB_MONTH.get(item.findtext("volumeType") or "", 0.10),
                created=(item.findtext("createTime") or "")[:10] or None,
            ))
    return disks


def _cpu_hours(http, credentials, machine: Machine, start, end) -> list:
    region = machine.region
    root = _query(http, credentials, "monitoring", region, f"monitoring.{region}.amazonaws.com", {
        "Action": "GetMetricStatistics", "Version": "2010-08-01", "Namespace": "AWS/EC2",
        "MetricName": "CPUUtilization", "Dimensions.member.1.Name": "InstanceId",
        "Dimensions.member.1.Value": machine.native_id, "StartTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "EndTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "Period": 3600,
        "Statistics.member.1": "Average", "Statistics.member.2": "Maximum",
    }, f"reading processor use for {machine.name}")
    points = []
    for point in root.findall(".//Datapoints/member"):
        when = datetime.fromisoformat(point.findtext("Timestamp").replace("Z", "+00:00"))
        points.append((when, float(point.findtext("Average") or 0), float(point.findtext("Maximum") or 0)))
    return points


def _daily_bill(http, credentials) -> tuple[dict, str]:
    start, end = cost_window()
    try:
        return _cost_explorer(http, credentials, start, end)
    except Blocked:
        raise
    except CloudError:
        # Accounts without a full year of history (or that just enabled Cost Explorer) can
        # reject a 12-month range; fall back to the last 90 days rather than failing the sync.
        return _cost_explorer(http, credentials, end - timedelta(days=90), end)


def _cost_explorer(http, credentials, start, end) -> tuple[dict, str]:
    body = json.dumps({
        "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
        "Granularity": "DAILY", "Metrics": ["UnblendedCost"],
    })
    response = signed_request(http, credentials, service="ce", region="us-east-1", host="ce.us-east-1.amazonaws.com",
                              body=body, headers={"content-type": "application/x-amz-json-1.1",
                                                  "x-amz-target": "AWSInsightsIndexService.GetCostAndUsage"})
    _check(response, "ce:GetCostAndUsage", "reading the bill from Cost Explorer")
    totals, currency = {}, "USD"
    for day in response.json().get("ResultsByTime", []):
        cost = day["Total"]["UnblendedCost"]
        totals[day["TimePeriod"]["Start"]] = float(cost["Amount"])
        currency = cost.get("Unit") or currency
    return totals, currency


def collect(credentials: dict, http: httpx.Client) -> Collected:
    """Read everything CloudLens can. Anything AWS refuses is skipped and explained in a warning,
    so an account with some permissions blocked still shows what is allowed."""
    start, end = usage_window()
    warnings = ["Memory use is not measured on AWS unless the CloudWatch agent is installed, so the memory checks are skipped."]
    regions = _regions(http, credentials)

    def cpu_or_none(machine):
        try:
            return _cpu_hours(http, credentials, machine, start, end), None
        except Blocked as block:
            return None, block  # None = unknown, which is not the same as "switched off"

    with ThreadPoolExecutor(max_workers=12) as pool:
        found = list(pool.map(lambda region: _machines_and_disks(http, credentials, region), regions))
        machines = [m for ms, _, _ in found for m in ms]
        disks = [d for _, ds, _ in found for d in ds]
        cpu_blocked = []
        for machine, (hours, block) in zip(machines, pool.map(cpu_or_none, machines)):
            machine.cpu_hours = hours
            if block:
                cpu_blocked.append(block)

    listing_blocked = [block for _, _, blocks in found for block in blocks]
    if listing_blocked:
        where = "in any region" if all(blocks for _, _, blocks in found) else "in some regions"
        warnings.append(f"CloudLens could not list servers or disks {where} because {_summarise(listing_blocked)}. "
                        "The bill and forecast still work, but the waste checks need the list of servers.")
    if cpu_blocked:
        warnings.append(f"Processor use could not be read because {_summarise(cpu_blocked)}. Those servers are not checked for waste.")

    try:
        totals, currency = _daily_bill(http, credentials)
    except Blocked as block:
        totals, currency = {}, "USD"
        warnings.append(f"The bill could not be read because {block}. Costs are estimated from list prices instead.")
        if not machines and not disks:
            raise CloudError(f"AWS would not let CloudLens read anything in this account because {_summarise([*listing_blocked, block])}.") from None
    return Collected(currency=currency, daily_total=totals, machines=machines, disks=disks, warnings=warnings)
