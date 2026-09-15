"""Gemeinsame Pydantic-Hilfstypen für alle Schemas."""
from datetime import datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer


def _as_utc(value: datetime) -> datetime:
    """Naive Datetimes aus der DB sind laut Konvention immer UTC (alle
    Models nutzen `datetime.utcnow()` als Default) - werden aber ohne
    Zeitzonen-Angabe serialisiert (z.B. "2026-09-15T13:19:58", kein "Z"/
    Offset). `new Date(...)` im Frontend interpretiert einen ISO-String
    ohne Zeitzone als LOKALE Zeit statt UTC - dadurch erschien der
    Upload-Zeitstempel im Review-UI um die UTC-Differenz zur Ortszeit
    versetzt (z.B. 2h zu früh während der Sommerzeit). Hier wird die
    Zeitzone explizit als UTC gesetzt, bevor Pydantic serialisiert, damit
    das Ergebnis einen Offset enthält und der Browser korrekt umrechnet -
    ohne dass sich am Speicherformat in der DB etwas ändert."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


UtcDatetime = Annotated[datetime, PlainSerializer(_as_utc, return_type=datetime)]
