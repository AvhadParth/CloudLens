from tests.conftest import USER


def test_private_pages_need_a_login(anonymous):
    for path in ("/api/summary", "/api/resources", "/api/recommendations", "/api/actions", "/api/forecast"):
        assert anonymous.get(path).status_code == 401
    assert anonymous.post("/api/assistant", json={"question": "hello"}).status_code == 401


def test_homepage_preview_is_public(anonymous):
    body = anonymous.get("/api/public/preview").json()
    assert 0 < body["monthly_waste"] < body["monthly_bill"]


def test_register_logs_you_in_and_hides_the_password(anonymous):
    created = anonymous.post("/api/auth/register", json=USER)
    assert created.status_code == 201
    assert "password" not in created.text
    assert anonymous.get("/api/auth/me").json()["email"] == USER["email"]


def test_email_can_only_register_once(client, anonymous):
    again = anonymous.post("/api/auth/register", json={**USER, "email": USER["email"].upper()})
    assert again.status_code == 409


def test_login_and_logout(client, anonymous):
    assert anonymous.post("/api/auth/login", json={"email": USER["email"], "password": "wrong-password"}).status_code == 401
    assert anonymous.post("/api/auth/login", json={"email": "nobody@example.com", "password": USER["password"]}).status_code == 401

    ok = anonymous.post("/api/auth/login", json={"email": USER["email"], "password": USER["password"]})
    assert ok.status_code == 200 and ok.json()["name"] == USER["name"]
    assert anonymous.get("/api/summary").status_code == 200

    anonymous.post("/api/auth/logout")
    assert anonymous.get("/api/summary").status_code == 401


def test_weak_or_malformed_sign_ups_are_rejected(anonymous):
    assert anonymous.post("/api/auth/register", json={**USER, "password": "short"}).status_code == 422
    assert anonymous.post("/api/auth/register", json={**USER, "email": "not-an-email"}).status_code == 422
    assert anonymous.post("/api/auth/register", json={**USER, "name": ""}).status_code == 422


def test_a_tampered_cookie_is_refused(anonymous):
    anonymous.cookies.set("cloudlens_session", "not.a.real.token")
    assert anonymous.get("/api/auth/me").json() is None
    assert anonymous.get("/api/summary").status_code == 401


def test_each_user_has_their_own_decisions(client, anonymous):
    rid = client.get("/api/recommendations").json()[0]["resource_id"]
    saved = client.post(f"/api/recommendations/{rid}/approve").json()

    anonymous.post("/api/auth/register", json={**USER, "email": "second@example.com"})
    for provider in ("aws", "azure", "gcp"):
        anonymous.post("/api/connections", json={"provider": provider})
    assert anonymous.get("/api/actions").json() == []
    assert anonymous.get("/api/recommendations").json()[0]["status"] == "open"
    # The second user cannot undo the first user's decision.
    assert anonymous.delete(f"/api/actions/{saved['id']}").status_code == 404
    assert len(client.get("/api/actions").json()) == 1
