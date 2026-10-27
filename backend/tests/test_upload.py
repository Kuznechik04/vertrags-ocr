import io
from pathlib import Path

from app.core.config import settings

SAMPLE_PDF = Path(__file__).resolve().parents[2] / "test_samples" / "vertrag_vorlage.pdf"


def _auth_headers(client, email="uploader@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "supersecret123"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _generic_template_id(client, headers):
    templates = client.get("/api/templates", headers=headers).json()
    return next(t["id"] for t in templates if t["key"] == "generisch")


def test_upload_rejects_spoofed_content_type(client):
    headers = _auth_headers(client)
    template_id = _generic_template_id(client, headers)

    fake_pdf = io.BytesIO(b"<html>das hier ist kein PDF</html>")
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"template_id": template_id},
        files={"file": ("fake.pdf", fake_pdf, "application/pdf")},
    )

    assert response.status_code == 400


def test_upload_accepts_real_pdf(client):
    headers = _auth_headers(client)
    template_id = _generic_template_id(client, headers)

    with SAMPLE_PDF.open("rb") as sample:
        response = client.post(
            "/api/documents/upload",
            headers=headers,
            data={"template_id": template_id},
            files={"file": ("vertrag.pdf", sample, "application/pdf")},
        )

    assert response.status_code == 200
    assert response.json()["content_type"] == "application/pdf"
    document_id = response.json()["id"]
    ocr_text_path = settings.upload_dir / f"{document_id}.txt"
    assert ocr_text_path.is_file()
    assert ocr_text_path.read_text(encoding="utf-8").strip()

    text_response = client.get(f"/api/documents/{document_id}/ocr-text", headers=headers)
    assert text_response.status_code == 200
    assert text_response.headers["content-type"].startswith("text/plain")
    assert text_response.text == ocr_text_path.read_text(encoding="utf-8")


def test_upload_rejects_oversized_file(client, monkeypatch):
    import app.api.documents as documents_module

    monkeypatch.setattr(documents_module.settings, "max_upload_size_mb", 0)

    headers = _auth_headers(client)
    template_id = _generic_template_id(client, headers)

    oversized = io.BytesIO(b"%PDF-1.4\n" + b"x" * 1024)
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"template_id": template_id},
        files={"file": ("gross.pdf", oversized, "application/pdf")},
    )

    assert response.status_code == 413
