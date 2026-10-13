"""Sign-up, login and "who is logged in".

Passwords are never stored: only a bcrypt hash is. After login the browser holds a signed
token (JWT) in an httpOnly cookie, which JavaScript on the page cannot read.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from . import store

COOKIE = "cloudlens_session"
SESSION_DAYS = 7
# Without JWT_SECRET in .env a random one is made at start-up, so logins end when the server restarts.
SECRET = os.environ.get("JWT_SECRET") or secrets.token_hex(32)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=72)  # bcrypt only reads the first 72 bytes

    @field_validator("email")
    @classmethod
    def normalise(cls, value: str) -> str:
        return value.strip().lower()


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def tidy(cls, value: str) -> str:
        return value.strip()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def password_matches(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def _profile(user: dict) -> dict:
    """The parts of a user that are safe to send to the browser."""
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


def _start_session(response: Response, user: dict) -> dict:
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    token = jwt.encode({"sub": user["id"], "exp": expires}, SECRET, algorithm="HS256")
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE") == "1",  # turn on when served over HTTPS
    )
    return _profile(user)


def current_user(request: Request) -> dict:
    """FastAPI dependency: the logged-in user, or a 401 error."""
    try:
        payload = jwt.decode(request.cookies.get(COOKIE, ""), SECRET, algorithms=["HS256"])
        user = store.find_user_by_id(payload["sub"])
    except (jwt.InvalidTokenError, KeyError):
        user = None
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    return user


@router.post("/register", status_code=201)
def register(body: Registration, response: Response):
    user = store.create_user(body.name, body.email, hash_password(body.password))
    if user is None:
        raise HTTPException(status_code=409, detail="An account with this email already exists. Try logging in.")
    return _start_session(response, user)


@router.post("/login")
def login(body: Credentials, response: Response):
    user = store.find_user_by_email(body.email)
    # Same message for "no such email" and "wrong password", so nobody can probe which emails exist.
    if user is None or not password_matches(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="That email and password do not match.")
    return _start_session(response, user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"logged_out": True}


@router.get("/me")
def me(request: Request):
    """The logged-in user, or null for a visitor (so the homepage can ask without causing an error)."""
    try:
        return _profile(current_user(request))
    except HTTPException:
        return None
