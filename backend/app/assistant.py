"""A small question-answering assistant that needs no paid AI API.

How it works:
  1. Each intent below has a few example phrasings.
  2. TF-IDF turns every example, and the user's question, into a vector of word weights.
  3. Cosine similarity finds the closest example; its intent is the answer to give.
  4. The answer text is filled in from the live data, so the numbers are never hard-coded.

If nothing is similar enough, the assistant says so and suggests questions it can answer.
"""

from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import data, engine, forecast, store

MIN_SIMILARITY = 0.3


def money(value: float) -> str:
    return f"${value:,.0f}"


def _recs(kind: str | None = None) -> list[dict]:
    return [r for r in engine.recommendations() if kind is None or r["kind"] == kind]


def _rec_items(recs: list[dict]) -> list[dict]:
    return [{"label": r["name"], "detail": r["action"], "value": money(r["estimated_monthly_saving"])} for r in recs]


def _kind_answer(kind: str, found: str, none: str):
    recs = _recs(kind)
    if not recs:
        return none, []
    total = sum(r["estimated_monthly_saving"] for r in recs)
    return f"{len(recs)} {found} Fixing all of them would save about {money(total)} a month.", _rec_items(recs)


def answer_spend():
    s = data.summary()
    direction = "up" if s["change_pct"] >= 0 else "down"
    return (
        f"You spent {money(s['last_30_days_cost'])} in the last 30 days, {direction} {abs(s['change_pct']):.1f}% "
        f"on the 30 days before. Over the whole year the total is {money(s['total_cost'])}.",
        [],
    )


def answer_top_resources():
    top = data.resources_with_usage()[:5]
    return (
        "These five cost the most over the last 30 days.",
        [{"label": r["name"], "detail": f"{r['team']}, {r['environment']}", "value": money(r["last_30_days_cost"])} for r in top],
    )


def answer_teams():
    teams = data.summary()["last_30_days_by"]["team"]
    leader, cost = next(iter(teams.items()))
    return (
        f"The {leader} team spends the most: {money(cost)} in the last 30 days.",
        [{"label": team, "detail": "last 30 days", "value": money(value)} for team, value in teams.items()],
    )


def answer_savings():
    recs = _recs()
    total = sum(r["estimated_monthly_saving"] for r in recs)
    spend = data.summary()["last_30_days_cost"]
    by_kind = {}
    for r in recs:
        by_kind.setdefault(r["kind_label"], []).append(r["estimated_monthly_saving"])
    return (
        f"I found {len(recs)} places where money is being wasted. Fixing all of them would save about "
        f"{money(total)} a month, which is {total / spend * 100:.0f}% of your bill.",
        [{"label": kind, "detail": f"{len(v)} resources", "value": money(sum(v))} for kind, v in by_kind.items()],
    )


def answer_idle():
    return _kind_answer("idle", "are switched on and being paid for, but doing almost nothing.", "Everything that is switched on is being used.")


def answer_oversized():
    return _kind_answer(
        "oversized", "are much bigger than the work they do needs.", "Nothing is bigger than it needs to be."
    )


def answer_schedule():
    return _kind_answer(
        "always_on_dev",
        "test machines stay on all night and all weekend with nobody using them.",
        "Every test machine is already switched off outside working hours.",
    )


def answer_storage():
    return _kind_answer(
        "unattached_storage", "storage disks are connected to nothing and nobody touches them.", "All your storage is in use."
    )


def answer_forecast():
    f = forecast.forecast()
    model = next(r for r in forecast.backtest()["results"] if r["is_model"])
    return (
        f"The next 30 days should cost about {money(f['next_30_days_cost'])} if nothing changes. When this "
        f"prediction was tested on past months it was off by {model['mape']:.1f}% a day on average.",
        [{"label": m["month"], "detail": f"{m['days']} days", "value": money(m["cost"])} for m in f["monthly"]],
    )


def answer_method():
    t = engine.THRESHOLDS
    return (
        "Every saving is an estimate, worked out from the last 30 days. "
        f"If something used under {t['idle_cpu_avg']:.0f}% of its processor, it counts as not used, and switching it off "
        "saves its whole cost. "
        f"If its busiest moment stayed under {t['oversized_cpu_peak']:.0f}% of its processor and "
        f"{t['oversized_memory_peak']:.0f}% of its memory, it is bigger than it needs to be, and the next size down "
        "costs half as much. "
        "Test machines left on overnight save the hours outside 8am to 8pm on weekdays. "
        "Storage nobody uses saves its full cost.",
        [],
    )


def answer_actions(user_id: str | None = None):
    approved = [a for a in store.list_actions(user_id) if a["status"] == "approved"] if user_id else []
    if not approved:
        return "You have not approved any fixes yet. Open Ways to save to pick some.", []
    total = sum(a["estimated_monthly_saving"] for a in approved)
    return (
        f"You have approved {len(approved)} fixes, worth about {money(total)} a month.",
        [{"label": a["resource_name"], "detail": a["action"], "value": money(a["estimated_monthly_saving"])} for a in approved],
    )


def answer_about_data():
    s = data.summary()
    return (
        f"All of it is simulated. The data set has {s['resource_count']} made-up resources with daily usage "
        f"from {s['period_start']} to {s['period_end']}. No real cloud account is connected, savings are "
        "estimates, and approving an action only records it in a log.",
        [],
    )


INTENTS = [
    {
        "id": "spend",
        "question": "How much did we spend in the last 30 days?",
        "examples": ["how much did we spend", "what is our cloud bill", "total cost last month", "current monthly spending"],
        "answer": answer_spend,
    },
    {
        "id": "savings",
        "question": "How much can we save?",
        "examples": ["how much can we save", "total potential savings", "where is money being wasted", "how do we reduce the bill"],
        "answer": answer_savings,
    },
    {
        "id": "top_resources",
        "question": "Which resources cost the most?",
        "examples": ["which resources cost the most", "most expensive servers", "top costs", "biggest resources by cost"],
        "answer": answer_top_resources,
    },
    {
        "id": "teams",
        "question": "Which team spends the most?",
        "examples": ["which team spends the most", "cost by team", "spending per department", "team breakdown"],
        "answer": answer_teams,
    },
    {
        "id": "idle",
        "question": "Which servers are not being used?",
        "examples": ["which servers are idle", "unused resources", "servers doing nothing", "what can we shut down or stop"],
        "answer": answer_idle,
    },
    {
        "id": "oversized",
        "question": "Which servers are bigger than they need to be?",
        "examples": ["which servers are oversized", "overprovisioned instances", "what can we downsize or resize", "too big for the workload"],
        "answer": answer_oversized,
    },
    {
        "id": "schedule",
        "question": "Which machines are left on all night?",
        "examples": ["which dev machines run all night", "development servers running on weekends", "what can we schedule to stop at night", "test environment always on"],
        "answer": answer_schedule,
    },
    {
        "id": "storage",
        "question": "Is there storage nobody is using?",
        "examples": ["is there storage nobody is using", "unattached disks", "orphaned volumes", "unused storage volumes"],
        "answer": answer_storage,
    },
    {
        "id": "forecast",
        "question": "What will we spend next month?",
        "examples": ["what will we spend next month", "forecast future costs", "predicted bill", "expected spending next quarter"],
        "answer": answer_forecast,
    },
    {
        "id": "method",
        "question": "How are savings calculated?",
        "examples": ["how are savings calculated", "explain the recommendation rules", "why was this flagged", "what thresholds do you use"],
        "answer": answer_method,
    },
    {
        "id": "actions",
        "question": "Which fixes have I approved?",
        "examples": ["what actions have been approved", "show the action log", "savings approved so far", "what did we already decide"],
        "answer": answer_actions,
    },
    {
        "id": "about_data",
        "question": "Is this real data?",
        "examples": ["is this real cloud data", "where does the data come from", "is this connected to aws azure or gcp", "is the data simulated"],
        "answer": answer_about_data,
    },
]


@lru_cache
def _index():
    phrases = [(intent, phrase) for intent in INTENTS for phrase in [intent["question"], *intent["examples"]]]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
    matrix = vectorizer.fit_transform(phrase for _, phrase in phrases)
    return vectorizer, matrix, [intent for intent, _ in phrases]


def suggestions() -> list[str]:
    return [intent["question"] for intent in INTENTS]


def ask(question: str, user_id: str | None = None) -> dict:
    vectorizer, matrix, owners = _index()
    scores = cosine_similarity(vectorizer.transform([question]), matrix)[0]
    best = int(scores.argmax())
    confidence = round(float(scores[best]), 2)

    if confidence < MIN_SIMILARITY:
        return {
            "intent": None,
            "confidence": confidence,
            "answer": "I can't answer that one. I only know about your bill, where money is being wasted, next month's bill and the fixes you approved.",
            "items": [],
            "suggestions": suggestions()[:4],
        }

    intent = owners[best]
    text, items = intent["answer"](user_id) if intent["id"] == "actions" else intent["answer"]()
    return {"intent": intent["id"], "confidence": confidence, "answer": text, "items": items, "suggestions": []}
