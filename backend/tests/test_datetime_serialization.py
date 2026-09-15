"""Regression-Guard: naive UTC-Datetimes aus der DB (alle Models nutzen
`datetime.utcnow()`) müssen bei der API-Ausgabe MIT Zeitzonen-Angabe
serialisiert werden. Ohne das interpretiert `new Date(...)` im Frontend
einen ISO-String ohne Offset als LOKALE statt UTC-Zeit - der angezeigte
Upload-Zeitstempel lag dadurch um die UTC-Differenz zur Ortszeit daneben
(z.B. 2h während der Sommerzeit)."""
from datetime import datetime

from app.schemas.auth import UserOut
from app.schemas.document import DocumentOut


def test_document_out_serializes_naive_datetime_with_utc_offset():
    doc = DocumentOut(
        id="doc-1",
        owner_id="user-1",
        owner_email=None,
        filename="test.pdf",
        content_type="application/pdf",
        status="uploaded",
        page_count=1,
        uploaded_at=datetime(2026, 9, 15, 13, 19, 58, 508974),
        reviewed_at=None,
        error_message=None,
    )

    dumped = doc.model_dump(mode="json")

    assert dumped["uploaded_at"].endswith(("Z", "+00:00"))


def test_user_out_serializes_naive_datetime_with_utc_offset():
    user = UserOut(id="user-1", email="a@b.de", role="user", created_at=datetime(2026, 9, 15, 13, 19, 58))

    dumped = user.model_dump(mode="json")

    assert dumped["created_at"].endswith(("Z", "+00:00"))
