import pytest

from app import data


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_summary_totals_match_the_raw_data(client):
    body = client.get("/api/summary").json()
    usage = data.load_usage()
    assert body["total_cost"] == pytest.approx(usage["cost"].sum(), abs=0.01)
    assert body["resource_count"] == len(data.load_resources())
    # Every breakdown must add up to the same 30-day total.
    for breakdown in body["last_30_days_by"].values():
        assert sum(breakdown.values()) == pytest.approx(body["last_30_days_cost"], abs=0.05)


def test_resources_lists_every_resource_once(client):
    rows = client.get("/api/resources").json()
    ids = [row["resource_id"] for row in rows]
    assert len(ids) == len(set(ids)) == len(data.load_resources())
    storage = next(row for row in rows if row["type"] == "storage")
    assert storage["cpu_avg"] is None  # storage has no CPU; must be null, not NaN


def test_monthly_costs_add_up_to_total(client):
    rows = client.get("/api/costs", params={"granularity": "monthly"}).json()
    assert len(rows) == 12
    assert sum(row["cost"] for row in rows) == pytest.approx(data.load_usage()["cost"].sum(), abs=0.1)


def test_grouped_costs_match_ungrouped(client):
    grouped = client.get("/api/costs", params={"granularity": "monthly", "group_by": "team"}).json()
    plain = client.get("/api/costs", params={"granularity": "monthly"}).json()
    assert sum(r["cost"] for r in grouped) == pytest.approx(sum(r["cost"] for r in plain), abs=0.5)
    assert {r["team"] for r in grouped} == set(data.load_resources()["team"])


def test_invalid_group_by_is_rejected(client):
    assert client.get("/api/costs", params={"group_by": "password"}).status_code == 422
