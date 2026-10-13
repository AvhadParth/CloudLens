import pandas as pd
import pytest

from app import assistant, data, engine, forecast


# --- optimization engine ---------------------------------------------------


def test_engine_finds_planted_waste_without_false_alarms():
    result = engine.evaluate()
    assert result["overall"]["recall"] >= 0.9
    assert result["overall"]["precision"] >= 0.9


def test_near_miss_resources_are_not_flagged():
    flagged = {rec["name"] for rec in engine.recommendations()}
    # Low average CPU, but high memory or high peaks: resizing these would be wrong.
    assert flagged.isdisjoint({"search-cache-01", "analytics-cache-01", "search-indexer-01", "mobile-ci-runner"})


def test_saving_never_exceeds_current_cost():
    for rec in engine.recommendations():
        assert 0 < rec["estimated_monthly_saving"] <= rec["current_monthly_cost"]


# --- forecasting -----------------------------------------------------------


def test_backtest_never_trains_on_the_test_period():
    result = forecast.backtest()
    assert pd.Timestamp(result["train_end"]) < pd.Timestamp(result["test_start"])
    assert len(result["holdout"]) == forecast.HOLDOUT_DAYS


def test_forecast_starts_the_day_after_the_data_ends(client):
    body = client.get("/api/forecast", params={"days": 30}).json()
    last = pd.Timestamp(body["history"][-1]["date"])
    assert pd.Timestamp(body["forecast"][0]["date"]) == last + pd.Timedelta(days=1)
    assert len(body["forecast"]) == 30
    assert all(day["low"] <= day["cost"] <= day["high"] for day in body["forecast"])


def test_forecast_rejects_silly_horizons(client):
    assert client.get("/api/forecast", params={"days": 5000}).status_code == 422


# --- assistant -------------------------------------------------------------


@pytest.mark.parametrize("intent", assistant.INTENTS, ids=lambda i: i["id"])
def test_every_suggested_question_reaches_its_own_intent(intent):
    assert assistant.ask(intent["question"])["intent"] == intent["id"]


@pytest.mark.parametrize(
    "question, intent",
    [
        ("what's our bill looking like?", "spend"),
        ("any servers we could shut down?", "idle"),
        ("predict the costs for next quarter", "forecast"),
        ("are there orphaned disks", "storage"),
    ],
)
def test_reworded_questions_still_match(question, intent):
    assert assistant.ask(question)["intent"] == intent


def test_unrelated_question_gets_a_fallback(client):
    body = client.post("/api/assistant", json={"question": "who won the cricket match yesterday"}).json()
    assert body["intent"] is None
    assert body["suggestions"]


# --- simulated actions -----------------------------------------------------


def test_approve_then_undo_round_trip(client):
    target = client.get("/api/recommendations").json()[0]
    assert target["status"] == "open"

    saved = client.post(f"/api/recommendations/{target['resource_id']}/approve").json()
    assert saved["status"] == "approved"

    summary = client.get("/api/summary").json()
    assert summary["approved_monthly_saving"] == pytest.approx(target["estimated_monthly_saving"])
    assert summary["open_monthly_saving"] + summary["approved_monthly_saving"] == pytest.approx(
        summary["potential_monthly_saving"], abs=0.02
    )

    assert client.delete(f"/api/actions/{saved['id']}").status_code == 200
    assert client.get("/api/actions").json() == []


def test_deciding_twice_keeps_one_row(client):
    rid = client.get("/api/recommendations").json()[0]["resource_id"]
    client.post(f"/api/recommendations/{rid}/approve")
    client.post(f"/api/recommendations/{rid}/dismiss")
    actions = client.get("/api/actions").json()
    assert len(actions) == 1 and actions[0]["status"] == "dismissed"


def test_cannot_approve_a_healthy_resource(client):
    healthy = next(r for r in data.resources_with_usage() if r["name"] == "web-frontend-01")
    assert client.post(f"/api/recommendations/{healthy['resource_id']}/approve").status_code == 404
