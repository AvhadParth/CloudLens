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
    """A browser that has signed up and is logged in."""
    browser = TestClient(app)
    assert browser.post("/api/auth/register", json=USER).status_code == 201
    return browser
