from pathlib import Path

SAMPLE_PDF = Path(__file__).resolve().parents[2] / "test_samples" / "vertrag_vorlage.pdf"


def _auth_headers(client, email="previewer@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "supersecret123"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _generic_template_id(client, headers):
    templates = client.get("/api/templates", headers=headers).json()
    return next(t["id"] for t in templates if t["key"] == "generisch")


def _upload_sample(client, headers, template_id):
    with SAMPLE_PDF.open("rb") as sample:
        response = client.post(
            "/api/documents/upload",
            headers=headers,
            data={"template_id": template_id},
            files={"file": ("vertrag.pdf", sample, "application/pdf")},
        )
    return response.json()["id"]


def test_preview_token_grants_access_to_its_own_document(client):
    headers = _auth_headers(client)
    template_id = _generic_template_id(client, headers)
    doc_id = _upload_sample(client, headers, template_id)

    token_response = client.get(f"/api/documents/{doc_id}/preview-token", headers=headers)
    assert token_response.status_code == 200
    preview_token = token_response.json()["preview_token"]

    # Kein Authorization-Header nötig - der Preview-Token allein genügt für
    # die Dateivorschau (so wie es <img>/<iframe> im Frontend nutzen).
    file_response = client.get(f"/api/documents/{doc_id}/file?preview_token={preview_token}")
    assert file_response.status_code == 200


def test_preview_token_does_not_grant_access_to_a_different_document(client):
    headers = _auth_headers(client)
    template_id = _generic_template_id(client, headers)
    doc_id_a = _upload_sample(client, headers, template_id)
    doc_id_b = _upload_sample(client, headers, template_id)

    token_response = client.get(f"/api/documents/{doc_id_a}/preview-token", headers=headers)
    preview_token = token_response.json()["preview_token"]

    response = client.get(f"/api/documents/{doc_id_b}/file?preview_token={preview_token}")
    assert response.status_code == 401


def test_preview_token_cannot_be_used_as_a_regular_bearer_token(client):
    """Ein Preview-Token trägt eine "aud"-Claim und darf deshalb nicht als
    normaler Session-Token akzeptiert werden (siehe
    app.core.security.decode_access_token)."""
    headers = _auth_headers(client)
    template_id = _generic_template_id(client, headers)
    doc_id = _upload_sample(client, headers, template_id)

    token_response = client.get(f"/api/documents/{doc_id}/preview-token", headers=headers)
    preview_token = token_response.json()["preview_token"]

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {preview_token}"})
    assert response.status_code == 401


def test_someone_elses_document_cannot_get_a_preview_token(client):
    owner_headers = _auth_headers(client, email="owner@example.com")
    template_id = _generic_template_id(client, owner_headers)
    doc_id = _upload_sample(client, owner_headers, template_id)

    other_headers = _auth_headers(client, email="other@example.com")
    response = client.get(f"/api/documents/{doc_id}/preview-token", headers=other_headers)
    assert response.status_code == 403
