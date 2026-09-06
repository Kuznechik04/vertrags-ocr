def test_login_is_rate_limited_after_too_many_attempts(client):
    client.post("/api/auth/register", json={"email": "victim@example.com", "password": "supersecret123"})

    for _ in range(10):
        response = client.post(
            "/api/auth/login", data={"username": "victim@example.com", "password": "wrong-password"}
        )
        assert response.status_code == 401

    blocked_response = client.post(
        "/api/auth/login", data={"username": "victim@example.com", "password": "wrong-password"}
    )
    assert blocked_response.status_code == 429


def test_register_is_rate_limited_after_too_many_attempts(client):
    for i in range(10):
        response = client.post(
            "/api/auth/register", json={"email": f"spam{i}@example.com", "password": "supersecret123"}
        )
        assert response.status_code == 201

    blocked_response = client.post(
        "/api/auth/register", json={"email": "one-more@example.com", "password": "supersecret123"}
    )
    assert blocked_response.status_code == 429
