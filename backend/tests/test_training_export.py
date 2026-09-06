from pathlib import Path

SAMPLE_PDF = Path(__file__).resolve().parents[2] / "test_samples" / "vertrag_vorlage.pdf"


def _admin_headers(client, email="training-admin@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "supersecret123"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _generic_template_id(client, headers):
    templates = client.get("/api/templates", headers=headers).json()
    return next(t["id"] for t in templates if t["key"] == "generisch")


def test_training_export_includes_template_key(client):
    """Regression-Guard: ohne template_key würde train_donut.py Felder aus
    allen Vertragstypen in ein gemeinsames Vokabular/Prompt mischen (siehe
    TODO.md Punkt 1)."""
    headers = _admin_headers(client)
    template_id = _generic_template_id(client, headers)

    with SAMPLE_PDF.open("rb") as sample:
        upload_response = client.post(
            "/api/documents/upload",
            headers=headers,
            data={"template_id": template_id},
            files={"file": ("vertrag.pdf", sample, "application/pdf")},
        )
    doc_id = upload_response.json()["id"]

    doc = client.get(f"/api/documents/{doc_id}", headers=headers).json()
    for field in doc["fields"]:
        client.put(
            f"/api/documents/{doc_id}/fields/{field['id']}",
            headers=headers,
            json={"is_validated": True},
        )
    finalize_response = client.post(f"/api/documents/{doc_id}/finalize", headers=headers)
    assert finalize_response.status_code == 200

    export_response = client.get("/api/documents/export/training-data", headers=headers)
    assert export_response.status_code == 200
    rows = export_response.json()
    assert rows
    assert all(row["template_key"] == "generisch" for row in rows)
