from pathlib import Path

SAMPLE_PDF = Path(__file__).resolve().parents[2] / "test_samples" / "vertrag_vorlage.pdf"


def _auth_headers(client, email="deleter@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "supersecret123"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _generic_template_id(client, headers):
    templates = client.get("/api/templates", headers=headers).json()
    return next(t["id"] for t in templates if t["key"] == "generisch")


def test_delete_document_removes_file_from_disk(client):
    """Regression-Guard für die Löschzusage in PRIVACY.md: `DELETE
    /api/documents/{id}` muss neben dem DB-Eintrag auch die hochgeladene
    Datei von der Festplatte entfernen."""
    from app.core.config import settings

    headers = _auth_headers(client)
    template_id = _generic_template_id(client, headers)

    with SAMPLE_PDF.open("rb") as sample:
        upload_response = client.post(
            "/api/documents/upload",
            headers=headers,
            data={"template_id": template_id},
            files={"file": ("vertrag.pdf", sample, "application/pdf")},
        )
    doc_id = upload_response.json()["id"]
    dest_path = settings.upload_dir / f"{doc_id}.pdf"
    assert dest_path.exists()

    delete_response = client.delete(f"/api/documents/{doc_id}", headers=headers)
    assert delete_response.status_code == 204
    assert not dest_path.exists()

    get_response = client.get(f"/api/documents/{doc_id}", headers=headers)
    assert get_response.status_code == 404
