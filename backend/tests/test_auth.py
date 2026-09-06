def _register(client, email="user@example.com", password="supersecret123"):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def test_register_login_me_roundtrip(client):
    register_response = _register(client)
    assert register_response.status_code == 201
    token = register_response.json()["access_token"]

    me_response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "user@example.com"

    login_response = client.post(
        "/api/auth/login",
        data={"username": "user@example.com", "password": "supersecret123"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["access_token"]


def test_login_rejects_wrong_password(client):
    _register(client, email="user2@example.com")

    login_response = client.post(
        "/api/auth/login",
        data={"username": "user2@example.com", "password": "wrong-password"},
    )
    assert login_response.status_code == 401


def test_only_first_registered_user_becomes_admin(client):
    """Regression guard: verhindert, dass ein künftiger Bootstrap-Bugfix
    (z.B. Phase 1 der Verbesserungs-Roadmap) versehentlich jeden Nutzer zum
    Admin macht oder den Erstnutzer-Bootstrap ganz entfernt, ohne dass es
    auffällt."""
    first = _register(client, email="admin@example.com")
    assert first.json()["user"]["role"] == "admin"

    second = _register(client, email="second@example.com")
    assert second.json()["user"]["role"] == "user"
