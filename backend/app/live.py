"""Connecting real cloud accounts and syncing their data.

  connect()  checks the keys with the provider, then stores them encrypted
  sync()     reads the account (see app/cloud/*) and turns what it finds into the same
             resources + daily-usage tables the sample data uses, so the waste checks,
             forecast and assistant work on real accounts without any changes.

Costs: the whole-account bill comes from the provider. Per-server costs come from the
provider when it reports them (Azure), otherwise from list prices (AWS, Google Cloud).
Any part of the real bill not matched to a server or disk is kept as one "Other charges"
line, so the totals always add up to the real bill.
"""

import hashlib
import json
import logging
from datetime import date, timedelta

import httpx

from . import cloud, store, vault
from .cloud import CloudError, aws, azure, gcp

CONNECTORS = {"aws": aws, "azure": azure, "gcp": gcp}
PROVIDER_NAMES = {"aws": "Amazon Web Services", "azure": "Microsoft Azure", "gcp": "Google Cloud"}
log = logging.getLogger("cloudlens.live")

# Fields that are safe to send to the browser (never the encrypted keys).
PUBLIC_FIELDS = ("id", "provider", "label", "account_ref", "hint", "status", "created_at", "last_synced_at",
                 "last_error", "warnings", "resource_count", "monthly_cost", "currency")


def public(account: dict) -> dict:
    return {field: account.get(field) for field in PUBLIC_FIELDS} | {"provider_name": PROVIDER_NAMES[account["provider"]]}


def connect(user_id: str, provider: str, label: str, credentials: dict) -> dict:
    connector = CONNECTORS[provider]
    cleaned = connector.check_credentials(credentials)
    with cloud.client() as http:
        info = connector.validate(cleaned, http)
    account = store.create_cloud_account(user_id, {
        "provider": provider,
        "label": (label or "").strip()[:60] or info.display_name,
        "account_ref": info.account_ref,
        "hint": connector.hint(cleaned),
        "secret": vault.encrypt(json.dumps(cleaned)),
    })
    if account is None:
        raise CloudError(f"You have already connected {info.display_name}.")
    return public(account)


def sync(user_id: str, account_id: str) -> dict | None:
    account = store.get_cloud_account(user_id, account_id)
    if account is None:
        return None
    store.update_cloud_account(account_id, {"status": "syncing", "last_error": None})
    try:
        credentials = json.loads(vault.decrypt(account["secret"]))
        with cloud.client() as http:
            collected = CONNECTORS[account["provider"]].collect(credentials, http)
        snapshot = build_snapshot(account, collected)
        store.save_snapshot(account_id, user_id, snapshot)
        update = {
            "status": "ready", "last_error": None, "last_synced_at": snapshot["synced_at"], "warnings": snapshot["warnings"],
            "resource_count": snapshot["resource_count"], "monthly_cost": snapshot["monthly_cost"],
            "currency": snapshot["currency"],
        }
    except CloudError as error:
        update = {"status": "error", "last_error": str(error)}
    except httpx.HTTPError:
        update = {"status": "error", "last_error": f"We could not reach {PROVIDER_NAMES[account['provider']]}. Try again in a minute."}
    except Exception:  # never show internals (or keys) to the user, but keep them in the server log
        log.exception("sync failed for cloud account %s", account_id)
        update = {"status": "error", "last_error": "Something went wrong while reading this account. Try syncing again."}
    store.update_cloud_account(account_id, update)
    return public({**account, **update})


# --- turning what the connector found into analysis tables ------------------------


def _resource_id(provider: str, account_id: str, native_id: str) -> str:
    return f"{provider}-{account_id[-6:]}-{hashlib.sha1(native_id.encode()).hexdigest()[:10]}"


def build_snapshot(account: dict, collected: cloud.Collected) -> dict:
    provider, account_id = account["provider"], account["id"]
    start, end = cloud.usage_window()
    today = cloud.utc_now().date().isoformat()  # today is still running, so it is left out
    resources, usage = [], []
    ids = {m.native_id: _resource_id(provider, account_id, m.native_id) for m in collected.machines}

    for machine in collected.machines:
        if machine.cpu_hours is None:  # the provider refused to share processor use
            unknown = {"cpu_avg": None, "cpu_p95": None, "cpu_business_hours": None, "cpu_off_hours": None,
                       "hours_running": 24 if machine.running else 0}
            days = {d: dict(unknown) for d in cloud.daily_usage([], start, end) if d < today}
        else:
            days = {d: row for d, row in cloud.daily_usage(machine.cpu_hours, start, end).items() if d < today}
        hours = sum(row["hours_running"] for row in days.values())
        rate = machine.hourly_rate
        if machine.daily_cost and hours:
            rate = rate or sum(machine.daily_cost.values()) / hours
        rid = ids[machine.native_id]
        resources.append({
            "resource_id": rid, "name": machine.name[:80], "type": "vm",
            "team": cloud.team_from_tags(machine.tags), "environment": cloud.environment_from_tags(machine.tags),
            "provider": provider, "region": machine.region, "size": machine.size, "vcpus": machine.vcpus,
            "memory_gb": machine.memory_gb, "storage_gb": None, "hourly_rate": rate,
            "created_date": machine.created, "attached_to": None,
        })
        for day, row in days.items():
            cost = machine.daily_cost.get(day) if machine.daily_cost else (rate or 0) * row["hours_running"]
            usage.append({"date": day, "resource_id": rid, **row, "memory_avg": None, "io_ops": None, "cost": cost or 0.0})

    window_days = sorted(d for d in cloud.daily_usage([], start, end) if d < today)
    for disk in collected.disks:
        rid = _resource_id(provider, account_id, disk.native_id)
        resources.append({
            "resource_id": rid, "name": disk.name[:80], "type": "storage",
            "team": cloud.team_from_tags(disk.tags), "environment": cloud.environment_from_tags(disk.tags),
            "provider": provider, "region": disk.region, "size": None, "vcpus": None, "memory_gb": None,
            "storage_gb": disk.size_gb, "hourly_rate": None, "created_date": disk.created,
            "attached_to": ids.get(disk.attached_to, disk.attached_to),
        })
        flat = disk.size_gb * disk.monthly_rate_per_gb * 12 / 365
        for day in window_days:
            usage.append({
                "date": day, "resource_id": rid, "cpu_avg": None, "cpu_p95": None, "cpu_business_hours": None,
                "cpu_off_hours": None, "memory_avg": None, "hours_running": 24, "io_ops": 0 if disk.attached_to is None else None,
                "cost": disk.daily_cost.get(day, flat) if disk.daily_cost else flat,
            })

    _match_real_bill(provider, account_id, collected.daily_total, resources, usage)

    warnings = list(collected.warnings)
    quiet = [m for m in collected.machines if m.cpu_hours is not None and not any(
        row["hours_running"] for d, row in cloud.daily_usage(m.cpu_hours, start, end).items() if d < today)]
    if quiet:
        names = ", ".join(m.name for m in quiet[:3]) + (" and others" if len(quiet) > 3 else "")
        warnings.append(f"No full day of processor readings yet for {names} (new or switched off). "
                        "CloudLens checks for waste once a server has been running for at least a day, so sync again tomorrow.")
    if collected.daily_total and not any(collected.daily_total.values()):
        warnings.append("The provider reports no spending on this account in the period read, so there is nothing to save yet.")
    if collected.currency != "USD":
        warnings.append(f"This account is billed in {collected.currency}; amounts are shown without conversion.")
    cutoff = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    last_30 = [row["cost"] for row in usage if row["date"] >= cutoff]
    return {
        "synced_at": store.now(),
        "provider": provider,
        "currency": collected.currency,
        "warnings": warnings,
        "resources": resources,
        "usage": usage,
        "resource_count": sum(1 for r in resources if r["type"] != "other"),
        "monthly_cost": round(sum(last_30), 2),
    }


def _match_real_bill(provider, account_id, daily_total, resources, usage) -> None:
    """Make each day's costs add up to the provider's real bill for that day.

    Whatever the bill shows beyond our per-resource estimates becomes "Other charges".
    If our estimates are higher than the bill (free tier, discounts), they are scaled down.
    """
    if not daily_total:
        return
    by_day = {}
    for row in usage:
        by_day.setdefault(row["date"], []).append(row)
    other_id = f"{provider}-{account_id[-6:]}-other"
    resources.append({
        "resource_id": other_id, "name": "Other charges", "type": "other", "team": "other charges",
        "environment": "unknown", "provider": provider, "region": "", "size": None, "vcpus": None,
        "memory_gb": None, "storage_gb": None, "hourly_rate": None, "created_date": None, "attached_to": None,
    })
    for day, total in sorted(daily_total.items()):
        rows = by_day.get(day, [])
        attributed = sum(row["cost"] for row in rows)
        if attributed > total > 0:
            for row in rows:
                row["cost"] *= total / attributed
        elif total == 0:
            for row in rows:
                row["cost"] = 0.0
        usage.append({
            "date": day, "resource_id": other_id, "cpu_avg": None, "cpu_p95": None, "cpu_business_hours": None,
            "cpu_off_hours": None, "memory_avg": None, "hours_running": None, "io_ops": None,
            "cost": max(total - attributed, 0.0),
        })
