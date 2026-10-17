"""Connecting real cloud accounts, tested against the fake providers in fake_clouds.py."""

import json

import pytest

from app import cloud, live, store
from tests import fake_clouds as fake

PROVIDERS = {
    "aws": (fake.AWS_KEYS, fake.aws_handler),
    "azure": (fake.AZURE_KEYS, fake.azure_handler),
    "gcp": (fake.gcp_keys(), fake.gcp_handler),
}


def use_fake(monkeypatch, handler):
    monkeypatch.setattr(cloud, "client", fake.http_client(handler))


def connect_and_sync(browser, monkeypatch, provider) -> dict:
    keys, handler = PROVIDERS[provider]
    use_fake(monkeypatch, handler())
    created = browser.post("/api/cloud-accounts", json={"provider": provider, "credentials": keys})
    assert created.status_code == 201, created.text
    synced = browser.post(f"/api/cloud-accounts/{created.json()['id']}/sync").json()
    assert synced["status"] == "ready", synced
    return synced


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_real_account_finds_the_waste_in_it(newcomer, monkeypatch, provider):
    synced = connect_and_sync(newcomer, monkeypatch, provider)
    assert synced["resource_count"] == 6  # 4 servers + 2 disks

    findings = {r["name"]: r["kind"] for r in newcomer.get("/api/recommendations").json()}
    assert findings == {
        "old-report": "idle",
        "dev-box": "always_on_dev",
        "big-batch": "oversized",
        "orphan-disk": "unattached_storage",
    }  # and the busy web server is left alone

    resources = newcomer.get("/api/resources").json()
    assert {r["provider"] for r in resources} == {provider}
    assert "Other charges" not in {r["name"] for r in resources}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_totals_match_the_real_bill(newcomer, monkeypatch, provider):
    connect_and_sync(newcomer, monkeypatch, provider)
    summary = newcomer.get("/api/summary").json()
    # Every day in the fake bill is 30 (weekdays) or 26 (weekends).
    assert 26 * 30 <= summary["last_30_days_cost"] <= 30 * 30
    costs = newcomer.get("/api/costs", params={"granularity": "daily"}).json()
    assert {round(day["cost"], 2) for day in costs[-60:-2]} <= {26.0, 30.0}


def test_real_accounts_get_a_tested_forecast(newcomer, monkeypatch):
    connect_and_sync(newcomer, monkeypatch, "aws")
    forecast = newcomer.get("/api/forecast").json()
    assert forecast["model"] == "Linear regression (trend + weekday)"
    assert all(25 <= day["cost"] <= 31 for day in forecast["forecast"])
    evaluation = newcomer.get("/api/evaluation").json()
    assert evaluation["rules"] is None  # no answer key exists for a real account
    assert evaluation["forecast"]["results"][0]["is_model"]


def test_keys_are_stored_encrypted_and_never_sent_back(newcomer, monkeypatch):
    created = connect_and_sync(newcomer, monkeypatch, "aws")
    listed = newcomer.get("/api/cloud-accounts").json()
    text = json.dumps(listed)
    assert fake.AWS_KEYS["secret_access_key"] not in text and "secret" not in listed["accounts"][0]
    assert listed["accounts"][0]["hint"] == "AKIA…MNOP"

    saved = store.database().cloud_accounts.find_one({})
    assert fake.AWS_KEYS["secret_access_key"] not in saved["secret"]
    assert json.loads(live.vault.decrypt(saved["secret"]))["access_key_id"] == fake.AWS_KEYS["access_key_id"]
    assert created["account_ref"] == "123456789012"


def test_wrong_or_refused_keys_get_a_clear_message(newcomer, monkeypatch):
    use_fake(monkeypatch, fake.aws_handler(refuse=True))
    refused = newcomer.post("/api/cloud-accounts", json={"provider": "aws", "credentials": fake.AWS_KEYS})
    assert refused.status_code == 400 and "refused" in refused.json()["detail"]

    malformed = newcomer.post("/api/cloud-accounts", json={"provider": "aws", "credentials": {"access_key_id": "nope", "secret_access_key": "x"}})
    assert malformed.status_code == 400 and "AKIA" in malformed.json()["detail"]
    assert newcomer.get("/api/cloud-accounts").json()["accounts"] == []


def test_the_same_account_cannot_be_connected_twice(newcomer, monkeypatch):
    connect_and_sync(newcomer, monkeypatch, "aws")
    again = newcomer.post("/api/cloud-accounts", json={"provider": "aws", "credentials": fake.AWS_KEYS})
    assert again.status_code == 400 and "already connected" in again.json()["detail"]


def test_a_failed_sync_keeps_the_last_good_data(newcomer, monkeypatch):
    synced = connect_and_sync(newcomer, monkeypatch, "aws")
    use_fake(monkeypatch, fake.aws_handler(refuse=True))
    failed = newcomer.post(f"/api/cloud-accounts/{synced['id']}/sync").json()
    assert failed["status"] == "error" and failed["last_error"]
    assert newcomer.get("/api/summary").status_code == 200


def test_removing_the_account_deletes_its_keys_and_data(newcomer, monkeypatch):
    synced = connect_and_sync(newcomer, monkeypatch, "aws")
    assert newcomer.delete(f"/api/cloud-accounts/{synced['id']}").status_code == 200
    assert store.database().cloud_accounts.count_documents({}) == 0
    assert store.database().cloud_snapshots.count_documents({}) == 0
    assert newcomer.get("/api/summary").status_code == 409


def test_other_people_cannot_touch_your_account(client, newcomer, monkeypatch):
    synced = connect_and_sync(newcomer, monkeypatch, "aws")
    assert client.post(f"/api/cloud-accounts/{synced['id']}/sync").status_code == 404
    assert client.delete(f"/api/cloud-accounts/{synced['id']}").status_code == 404
    assert client.get("/api/cloud-accounts").json()["accounts"] == []
    assert "old-report" not in {r["name"] for r in client.get("/api/resources").json()}


def test_real_and_sample_accounts_can_be_combined(newcomer, monkeypatch):
    connect_and_sync(newcomer, monkeypatch, "azure")
    newcomer.post("/api/connections", json={"provider": "aws"})
    names = {r["name"] for r in newcomer.get("/api/resources").json()}
    assert {"old-report", "web-frontend-01"} <= names


def test_without_an_encryption_key_live_accounts_are_switched_off(newcomer, monkeypatch):
    monkeypatch.delenv("CREDENTIALS_KEY")
    use_fake(monkeypatch, fake.aws_handler())
    assert newcomer.get("/api/cloud-accounts").json()["enabled"] is False
    response = newcomer.post("/api/cloud-accounts", json={"provider": "aws", "credentials": fake.AWS_KEYS})
    assert response.status_code == 400 and "CREDENTIALS_KEY" in response.json()["detail"]


def test_an_organization_blocking_servers_still_imports_the_bill(newcomer, monkeypatch):
    use_fake(monkeypatch, fake.aws_handler(block=("ec2:DescribeInstances", "ec2:DescribeVolumes")))
    created = newcomer.post("/api/cloud-accounts", json={"provider": "aws", "credentials": fake.AWS_KEYS}).json()
    synced = newcomer.post(f"/api/cloud-accounts/{created['id']}/sync").json()
    assert synced["status"] == "ready" and synced["resource_count"] == 0
    assert not any("No full day of processor readings" in w for w in synced["warnings"])
    assert any("service control policy" in w and "organization" in w for w in synced["warnings"])
    assert 26 * 30 <= newcomer.get("/api/summary").json()["last_30_days_cost"] <= 30 * 30
    assert newcomer.get("/api/recommendations").json() == []


def test_blocked_usage_metrics_never_look_like_idle_servers(newcomer, monkeypatch):
    use_fake(monkeypatch, fake.aws_handler(block=("cloudwatch:GetMetricStatistics",)))
    created = newcomer.post("/api/cloud-accounts", json={"provider": "aws", "credentials": fake.AWS_KEYS}).json()
    synced = newcomer.post(f"/api/cloud-accounts/{created['id']}/sync").json()
    assert synced["status"] == "ready"
    assert any("Processor use could not be read" in w for w in synced["warnings"])
    # Only the disk check works without processor readings; no server is wrongly called idle.
    assert {r["kind"] for r in newcomer.get("/api/recommendations").json()} == {"unattached_storage"}


def test_an_account_that_blocks_everything_fails_with_the_reason(newcomer, monkeypatch):
    use_fake(monkeypatch, fake.aws_handler(block=("ec2:DescribeInstances", "ec2:DescribeVolumes", "ce:GetCostAndUsage")))
    created = newcomer.post("/api/cloud-accounts", json={"provider": "aws", "credentials": fake.AWS_KEYS}).json()
    synced = newcomer.post(f"/api/cloud-accounts/{created['id']}/sync").json()
    assert synced["status"] == "error" and "service control policy" in synced["last_error"]
