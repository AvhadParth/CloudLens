import pytest

from app import data


def test_a_new_account_starts_with_no_data(newcomer):
    assert all(not provider["connected"] for provider in newcomer.get("/api/connections").json())
    for path in ("/api/summary", "/api/resources", "/api/recommendations", "/api/forecast", "/api/evaluation"):
        assert newcomer.get(path).status_code == 409
    assert newcomer.post("/api/assistant", json={"question": "how much can we save?"}).status_code == 409


def test_connecting_one_cloud_shows_only_that_cloud(newcomer):
    providers = newcomer.post("/api/connections", json={"provider": "aws"}).json()
    aws = next(p for p in providers if p["id"] == "aws")
    assert aws["connected"] and aws["connected_at"]

    resources = newcomer.get("/api/resources").json()
    assert {r["provider"] for r in resources} == {"aws"}
    assert len(resources) == aws["resource_count"] < len(data.all_resources())

    summary = newcomer.get("/api/summary").json()
    assert summary["last_30_days_cost"] == pytest.approx(aws["monthly_cost"], abs=0.05)
    assert {r["provider"] for r in newcomer.get("/api/recommendations").json()} == {"aws"}
    assert newcomer.get("/api/forecast").status_code == 200
    assert newcomer.get("/api/evaluation").json()["rules"]["resources"] == aws["resource_count"]


def test_every_cloud_works_on_its_own(newcomer):
    for provider in data.PROVIDERS:
        newcomer.post("/api/connections", json={"provider": provider})
        summary = newcomer.get("/api/summary").json()
        assert summary["recommendation_count"] > 0
        assert summary["forecast_next_30_days"] > 0
        newcomer.delete(f"/api/connections/{provider}")


def test_adding_a_second_cloud_adds_its_bill(newcomer):
    newcomer.post("/api/connections", json={"provider": "aws"})
    one = newcomer.get("/api/summary").json()["last_30_days_cost"]
    newcomer.post("/api/connections", json={"provider": "gcp"})
    two = newcomer.get("/api/summary").json()["last_30_days_cost"]
    assert two > one
    # Connecting the same cloud twice changes nothing.
    newcomer.post("/api/connections", json={"provider": "gcp"})
    assert newcomer.get("/api/summary").json()["last_30_days_cost"] == two


def test_disconnecting_the_last_cloud_empties_the_dashboard(newcomer):
    newcomer.post("/api/connections", json={"provider": "azure"})
    assert newcomer.get("/api/summary").status_code == 200
    newcomer.delete("/api/connections/azure")
    assert newcomer.get("/api/summary").status_code == 409


def test_connections_do_not_leak_between_users(client, newcomer):
    newcomer.post("/api/connections", json={"provider": "azure"})
    assert {r["provider"] for r in newcomer.get("/api/resources").json()} == {"azure"}
    assert {r["provider"] for r in client.get("/api/resources").json()} == set(data.PROVIDERS)
    assert {r["provider"] for r in newcomer.get("/api/resources").json()} == {"azure"}


def test_unknown_cloud_is_rejected(newcomer):
    assert newcomer.post("/api/connections", json={"provider": "oracle"}).status_code == 422
