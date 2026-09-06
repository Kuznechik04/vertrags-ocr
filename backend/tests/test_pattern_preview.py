from pathlib import Path

SAMPLE_PDF = Path(__file__).resolve().parents[2] / "test_samples" / "vertrag_vorlage.pdf"


def _admin_headers(client, email="pattern-admin@example.com"):
    # Erster registrierter Nutzer wird automatisch Admin.
    response = client.post("/api/auth/register", json={"email": email, "password": "supersecret123"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_preview_pattern_matches_against_sample_file(client):
    headers = _admin_headers(client)

    with SAMPLE_PDF.open("rb") as sample:
        response = client.post(
            "/api/templates/preview-pattern",
            headers=headers,
            data={"patterns": [r"versicherungsnehmer(?:in)?\s*:?\s*([^\n\.]{3,60})"]},
            files={"file": ("vertrag.pdf", sample, "application/pdf")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["match_status"] == "matched"
    assert body["value"]


def test_preview_pattern_reports_field_not_found(client):
    headers = _admin_headers(client)

    with SAMPLE_PDF.open("rb") as sample:
        response = client.post(
            "/api/templates/preview-pattern",
            headers=headers,
            data={"patterns": [r"ein-begriff-der-garantiert-nicht-vorkommt\s*:?\s*([^\n\.]{3,60})"]},
            files={"file": ("vertrag.pdf", sample, "application/pdf")},
        )

    assert response.status_code == 200
    assert response.json()["match_status"] == "field_not_found"


def test_preview_pattern_requires_admin(client):
    response = client.post("/api/auth/register", json={"email": "admin1@example.com", "password": "supersecret123"})
    admin_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    _ = admin_headers  # first user is admin; register a second, non-admin user for this test
    second = client.post("/api/auth/register", json={"email": "user2@example.com", "password": "supersecret123"})
    user_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}

    with SAMPLE_PDF.open("rb") as sample:
        response = client.post(
            "/api/templates/preview-pattern",
            headers=user_headers,
            data={"patterns": [r"foo\s*:?\s*([^\n\.]{3,60})"]},
            files={"file": ("vertrag.pdf", sample, "application/pdf")},
        )

    assert response.status_code == 403


def test_preview_pattern_does_not_persist_the_file(client):
    from app.core.config import settings

    headers = _admin_headers(client)
    before = set(settings.upload_dir.glob("*"))

    with SAMPLE_PDF.open("rb") as sample:
        client.post(
            "/api/templates/preview-pattern",
            headers=headers,
            data={"patterns": [r"vertragspartner\s*:?\s*([^\n\.]{3,60})"]},
            files={"file": ("vertrag.pdf", sample, "application/pdf")},
        )

    after = set(settings.upload_dir.glob("*"))
    assert before == after
