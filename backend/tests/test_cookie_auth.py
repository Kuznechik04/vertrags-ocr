def _register(client, email="cookie@example.com", password="supersecret123"):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def test_register_sets_httponly_session_and_csrf_cookies(client):
    response = _register(client)

    assert response.status_code == 201
    assert "access_token" in response.cookies
    assert "csrf_token" in response.cookies


def test_me_works_via_cookie_without_authorization_header(client):
    _register(client, email="cookie2@example.com")

    # Kein Authorization-Header nötig - der TestClient trägt das vom Register
    # gesetzte Session-Cookie wie ein Browser automatisch weiter.
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "cookie2@example.com"


def test_mutating_request_via_cookie_without_csrf_header_is_rejected(client):
    _register(client, email="csrf@example.com")

    response = client.delete("/api/documents/does-not-exist")
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


def test_mutating_request_via_cookie_with_valid_csrf_header_passes_csrf_check(client):
    _register(client, email="csrf2@example.com")
    csrf_token = client.cookies.get("csrf_token")

    response = client.delete("/api/documents/does-not-exist", headers={"X-CSRF-Token": csrf_token})
    # CSRF-Check ist bestanden - der 404 kommt aus dem Ownership-Check dahinter.
    assert response.status_code == 404


def test_mutating_request_via_authorization_header_is_exempt_from_csrf(client):
    """Bearer-Token-Clients (z.B. training/prepare_dataset.py) senden keine
    Cookies und sind gegen CSRF nicht anfällig - für sie gilt die
    CSRF-Prüfung nicht."""
    response = _register(client, email="bearer@example.com")
    token = response.json()["access_token"]

    delete_response = client.delete(
        "/api/documents/does-not-exist", headers={"Authorization": f"Bearer {token}"}
    )
    assert delete_response.status_code == 404


def test_logout_clears_cookies_and_ends_the_cookie_session(client):
    _register(client, email="logout@example.com")
    csrf_token = client.cookies.get("csrf_token")

    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 204

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 401
