"""Gemeinsame Schnittstelle für alle OCR/Feld-Extraktions-Backends.

Jedes Backend bekommt den Pfad zu einer hochgeladenen Datei (PDF oder Bild)
und liefert eine Liste erkannter Felder zurück. So lässt sich das eigentliche
Modell (Mock, Donut, LayoutLMv3, externe API, ...) austauschen, ohne dass
sich am Rest der Anwendung etwas ändert.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Warum `value` fehlt (falls es fehlt) – siehe app.ocr.mock_model für die
# Herleitung im Regex-Backend:
# - "matched": Wert wurde erkannt.
# - "field_not_found": Kein Anker-Muster wurde irgendwo im Dokumenttext
#   gefunden (das Feld scheint im Dokument gar nicht vorzukommen).
# - "data_not_found": Ein Anker wurde gefunden, aber kein Wert dahinter
#   passend extrahiert.
# - "no_pattern": Für dieses Feld ist gar kein automatisches Muster
#   hinterlegt (z.B. Preset "Kein automatisches Muster") – kein
#   Erkennungsfehlschlag, das Feld ist von vornherein rein manuell
#   auszufüllen.
MatchStatus = Literal["matched", "field_not_found", "data_not_found", "no_pattern"]


@dataclass
class FieldPrediction:
    field_key: str
    field_label: str
    value: str | None
    confidence: float
    page: int = 1
    bbox: tuple[float, float, float, float] | None = None  # x, y, w, h (relative 0..1)
    match_status: MatchStatus = "matched"


@dataclass
class FieldSpec:
    """Ein zu erkennendes Feld, wie es ein Vertragstyp-Template vorgibt (siehe
    `app.models.template.TemplateField`). Von den OCR-Backends unabhängig von
    der DB-Repräsentation genutzt, damit `app/ocr/*` keine SQLAlchemy-Modelle
    importieren muss."""

    field_key: str
    field_label: str
    patterns: list[str] | None = None  # nur vom Mock-Backend genutzt


class BaseOCRModel:
    """Abstrakte Basisklasse für Feld-Extraktions-Backends. Welche Felder
    erkannt werden sollen, gibt der Aufrufer über `fields` vor (abhängig vom
    Vertragstyp-Template des Dokuments) – die Backends legen keinen festen
    Feldkatalog mehr selbst fest."""

    def predict(self, file_path: str, fields: list[FieldSpec]) -> list[FieldPrediction]:
        raise NotImplementedError

    def page_count(self, file_path: str) -> int:
        return 1
