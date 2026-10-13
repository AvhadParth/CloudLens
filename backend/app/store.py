"""MongoDB storage: user accounts, and the decisions each user makes on recommendations.

Set MONGODB_URI in backend/.env to use a real MongoDB server (for example MongoDB Atlas).
Without it the app falls back to an in-memory stand-in so it can still run and be tested,
but everything stored is lost when the server restarts.

Approving an action only writes a document here. No cloud resource is ever changed.
"""

import os
from datetime import datetime, timezone
from functools import lru_cache

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError


def using_real_database() -> bool:
    return bool(os.environ.get("MONGODB_URI"))


@lru_cache
def database():
    if using_real_database():
        client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=5000)
    else:
        import mongomock

        client = mongomock.MongoClient()
    db = client[os.environ.get("MONGODB_DB", "cloudlens")]
    db.users.create_index("email", unique=True)
    db.actions.create_index([("user_id", ASCENDING), ("resource_id", ASCENDING)], unique=True)
    return db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _public(document: dict | None) -> dict | None:
    """Replace Mongo's ObjectId `_id` with a plain string `id`."""
    if document is None:
        return None
    document = dict(document)
    document["id"] = str(document.pop("_id"))
    return document


# --- users -----------------------------------------------------------------


def create_user(name: str, email: str, password_hash: str) -> dict | None:
    """Returns the new user, or None if the email is already registered."""
    user = {"name": name, "email": email, "password_hash": password_hash, "created_at": _now()}
    try:
        database().users.insert_one(user)
    except DuplicateKeyError:
        return None
    return _public(user)


def find_user_by_email(email: str) -> dict | None:
    return _public(database().users.find_one({"email": email}))


def find_user_by_id(user_id: str) -> dict | None:
    try:
        return _public(database().users.find_one({"_id": ObjectId(user_id)}))
    except InvalidId:
        return None


# --- decisions on recommendations -------------------------------------------


def list_actions(user_id: str) -> list[dict]:
    rows = database().actions.find({"user_id": user_id}).sort("decided_at", -1)
    return [_public(row) for row in rows]


def record(user_id: str, recommendation: dict, status: str) -> dict:
    """Store (or replace) this user's decision for one resource and return the saved document."""
    key = {"user_id": user_id, "resource_id": recommendation["resource_id"]}
    database().actions.update_one(
        key,
        {
            "$set": {
                "resource_name": recommendation["name"],
                "kind": recommendation["kind"],
                "action": recommendation["action"],
                "estimated_monthly_saving": recommendation["estimated_monthly_saving"],
                "status": status,
                "decided_at": _now(),
            }
        },
        upsert=True,
    )
    return _public(database().actions.find_one(key))


def delete(user_id: str, action_id: str) -> bool:
    try:
        result = database().actions.delete_one({"_id": ObjectId(action_id), "user_id": user_id})
    except InvalidId:
        return False
    return result.deleted_count > 0
