import re

from pydantic import BaseModel, ConfigDict, field_validator

from app.ocr.base import MatchStatus


def _validate_patterns(patterns: list[str] | None) -> list[str] | None:
    """Verhindert, dass ein syntaktisch kaputtes Regex überhaupt erst
    gespeichert wird - vorher fiel das erst beim nächsten Upload gegen
    dieses Template auf (und ließ diesen dank eines separaten Bugs sogar
    mit einem 500 fehlschlagen, siehe app.ocr.mock_model)."""
    if not patterns:
        return patterns
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Ungültiges Regex-Muster {pattern!r}: {exc}") from exc
    return patterns


class TemplateFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    field_key: str
    field_label: str
    sort_order: int
    patterns: list[str] | None


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    name: str
    fields: list[TemplateFieldOut]


class TemplateCreate(BaseModel):
    key: str
    name: str


class TemplateFieldCreate(BaseModel):
    field_key: str
    field_label: str
    patterns: list[str] | None = None

    _validate_patterns = field_validator("patterns")(_validate_patterns)


class TemplateFieldUpdate(BaseModel):
    field_label: str
    patterns: list[str] | None = None

    _validate_patterns = field_validator("patterns")(_validate_patterns)


class PatternPreviewOut(BaseModel):
    """Ergebnis eines Musters gegen eine Test-Datei (siehe
    POST /api/templates/preview-pattern) - schließt den Vorschau-Loop beim
    Anlegen neuer Vertragstypen-Felder."""

    value: str | None
    confidence: float
    page: int
    match_status: MatchStatus


class TemplateSuggestionOut(BaseModel):
    template_id: str
    template_key: str
    template_name: str
    score: float
