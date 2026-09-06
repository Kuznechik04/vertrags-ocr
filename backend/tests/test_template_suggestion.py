from pathlib import Path

SAMPLE_PDF = Path(__file__).resolve().parents[2] / "test_samples" / "vertrag_vorlage.pdf"


def _auth_headers(client, email="suggest@example.com"):
    response = client.post("/api/auth/register", json={"email": email, "password": "supersecret123"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_suggest_ranks_templates_by_field_match_score(client):
    headers = _auth_headers(client)

    with SAMPLE_PDF.open("rb") as sample:
        response = client.post(
            "/api/templates/suggest",
            headers=headers,
            files={"file": ("vertrag.pdf", sample, "application/pdf")},
        )

    assert response.status_code == 200
    suggestions = response.json()
    keys = [s["template_key"] for s in suggestions]
    assert "versicherung" in keys
    assert "generisch" in keys
    # Absteigend sortiert nach Score.
    scores = [s["score"] for s in suggestions]
    assert scores == sorted(scores, reverse=True)
    # Das Beispieldokument ist ein Versicherungsvertrag mit den passenden
    # Suchbegriffen - das "versicherung"-Template (mit Mustern) sollte klar
    # höher scoren als "generisch" (ohne jedes Muster, Score 0).
    by_key = {s["template_key"]: s["score"] for s in suggestions}
    assert by_key["versicherung"] > by_key["generisch"]
    assert by_key["generisch"] == 0.0
