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
    db.cloud_accounts.create_index([("user_id", ASCENDING), ("provider", ASCENDING), ("account_ref", ASCENDING)], unique=True)
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


def set_connections(user_id: str, connections: list[dict]) -> None:
    database().users.update_one({"_id": ObjectId(user_id)}, {"$set": {"connections": connections}})


def now() -> str:
    return _now()


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


# --- real cloud accounts ---------------------------------------------------------
# cloud_accounts holds one document per connected account, with its keys encrypted.
# cloud_snapshots holds the data read by the latest sync, keyed by the account's id.


def create_cloud_account(user_id: str, fields: dict) -> dict | None:
    """Returns the new account, or None if this user already connected that exact account."""
    document = {"user_id": user_id, "status": "new", "created_at": _now(), **fields}
    try:
        database().cloud_accounts.insert_one(document)
    except DuplicateKeyError:
        return None
    return _public(document)


def list_cloud_accounts(user_id: str) -> list[dict]:
    return [_public(row) for row in database().cloud_accounts.find({"user_id": user_id}).sort("created_at", 1)]


def get_cloud_account(user_id: str, account_id: str) -> dict | None:
    try:
        return _public(database().cloud_accounts.find_one({"_id": ObjectId(account_id), "user_id": user_id}))
    except InvalidId:
        return None


def update_cloud_account(account_id: str, fields: dict) -> None:
    database().cloud_accounts.update_one({"_id": ObjectId(account_id)}, {"$set": fields})


def delete_cloud_account(user_id: str, account_id: str) -> bool:
    try:
        result = database().cloud_accounts.delete_one({"_id": ObjectId(account_id), "user_id": user_id})
    except InvalidId:
        return False
    if result.deleted_count:
        database().cloud_snapshots.delete_one({"_id": account_id})
    return result.deleted_count > 0


def save_snapshot(account_id: str, user_id: str, snapshot: dict) -> None:
    database().cloud_snapshots.replace_one({"_id": account_id}, {"_id": account_id, "user_id": user_id, **snapshot}, upsert=True)


def get_snapshot(account_id: str) -> dict | None:
    return database().cloud_snapshots.find_one({"_id": account_id})
