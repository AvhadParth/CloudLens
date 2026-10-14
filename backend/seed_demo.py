"""Create (or refresh) the showcase account used to demo CloudLens to faculty.

The account gets all three sample clouds connected and a short history of decisions,
so the dashboard, Ways to save, Next bills and History pages are all full the moment
it logs in. Every other account still starts empty and connects clouds itself.

Run from the backend folder (it uses MONGODB_URI from backend/.env):

    .venv/bin/python seed_demo.py --email demo@example.com --password "a-strong-password"

Running it again resets the account's connections and decisions to the showcase state.
The password is only needed the first time; later runs keep the existing one.
"""

import argparse
import sys

from app import auth, engine, store

CONNECTED_AT = {
    "aws": "2026-08-18T09:30:00+00:00",
    "gcp": "2026-08-18T09:42:00+00:00",
    "azure": "2026-09-02T11:05:00+00:00",
}

# (resource name, decision, when it was made). The rest stay open in Ways to save.
DECISIONS = [
    ("payments-migration-tmp", "approved", "2026-09-04T10:12:00+00:00"),
    ("old-etl-scratch-disk", "approved", "2026-09-04T10:20:00+00:00"),
    ("payments-dev-01", "approved", "2026-09-11T14:03:00+00:00"),
    ("analytics-dashboard-01", "approved", "2026-09-19T08:47:00+00:00"),
    ("platform-test-db", "approved", "2026-09-26T16:31:00+00:00"),
    ("reporting-db-replica", "dismissed", "2026-09-26T16:35:00+00:00"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", help="needed only when the account does not exist yet")
    parser.add_argument("--name", default="Parth Avhad")
    args = parser.parse_args()
    email = args.email.strip().lower()

    if not store.using_real_database():
        print("MONGODB_URI is not set in backend/.env, so there is nowhere to save the account.")
        return 1

    user = store.find_user_by_email(email)
    if user is None:
        if not args.password or len(args.password) < 8:
            print("This account does not exist yet: pass --password (at least 8 characters) to create it.")
            return 1
        user = store.create_user(args.name, email, auth.hash_password(args.password))
        print(f"Created account {email}")
    else:
        print(f"Found existing account {email}; keeping its password")

    store.set_connections(user["id"], [{"provider": p, "connected_at": t} for p, t in CONNECTED_AT.items()])

    findings = {rec["name"]: rec for rec in engine.recommendations()}
    db = store.database()
    db.actions.delete_many({"user_id": user["id"]})
    for name, status, decided_at in DECISIONS:
        store.record(user["id"], findings[name], status)
        db.actions.update_one(
            {"user_id": user["id"], "resource_id": findings[name]["resource_id"]},
            {"$set": {"decided_at": decided_at}},
        )

    approved = [findings[n] for n, s, _ in DECISIONS if s == "approved"]
    print(f"Connected: {', '.join(CONNECTED_AT)}")
    print(
        f"Decisions: {len(approved)} approved (about ${sum(r['estimated_monthly_saving'] for r in approved):,.0f} a month), "
        f"{len(DECISIONS) - len(approved)} skipped, {len(findings) - len(DECISIONS)} left to decide"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
