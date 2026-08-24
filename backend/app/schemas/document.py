from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    field_key: str
    field_label: str
    predicted_value: str | None
    corrected_value: str | None
    final_value: str | None
    confidence: float
    page: int
    bbox_x: float | None
    bbox_y: float | None
    bbox_w: float | None
    bbox_h: float | None
    is_validated: bool
    is_corrected: bool
    is_position_corrected: bool


class FieldUpdate(BaseModel):
    corrected_value: str | None = None
    is_validated: bool | None = None

    # Manuelle Positionskorrektur: wird gesetzt, wenn der Nutzer im Viewer ein
    # Rechteck über die tatsächliche Fundstelle zieht (z.B. weil das Modell das
    # Feld gar nicht erkannt hatte). Alle vier Bbox-Werte müssen zusammen
    # mitgeschickt werden, `page` ist optional (Default: aktuelle Seite bleibt
    # bzw. wird auf 1 gesetzt, falls noch keine Seite bekannt war).
    page: int | None = None
    bbox_x: float | None = Field(default=None, ge=0, le=1)
    bbox_y: float | None = Field(default=None, ge=0, le=1)
    bbox_w: float | None = Field(default=None, gt=0, le=1)
    bbox_h: float | None = Field(default=None, gt=0, le=1)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    owner_email: str | None
    filename: str
    content_type: str
    status: str
    page_count: int
    uploaded_at: datetime
    reviewed_at: datetime | None
    error_message: str | None


class DocumentDetailOut(DocumentOut):
    fields: list[FieldOut]


class TrainingExportRow(BaseModel):
    document_id: str
    filename: str
    field_key: str
    field_label: str
    predicted_value: str | None
    final_value: str | None
    was_corrected: bool
    confidence: float
    page: int
    bbox_x: float | None
    bbox_y: float | None
    bbox_w: float | None
    bbox_h: float | None
    was_position_corrected: bool
