import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app

USER = {"name": "Test User", "email": "test@example.com", "password": "correct-horse-battery"}


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    """Every test gets its own empty in-memory database; a real MongoDB is never touched."""
    monkeypatch.delenv("MONGODB_URI", raising=False)
    store.database.cache_clear()
    yield
    store.database.cache_clear()


@pytest.fixture
def anonymous():
    """A browser that has not logged in."""
    return TestClient(app)


@pytest.fixture
def client():
    """A browser that has signed up, is logged in, and has connected all three clouds."""
    browser = TestClient(app)
    assert browser.post("/api/auth/register", json=USER).status_code == 201
    for provider in ("aws", "azure", "gcp"):
        assert browser.post("/api/connections", json={"provider": provider}).status_code == 200
    return browser


@pytest.fixture
def newcomer():
    """A browser that has signed up but not connected any cloud account yet."""
    browser = TestClient(app)
    assert browser.post("/api/auth/register", json={**USER, "email": "new@example.com"}).status_code == 201
    return browser
