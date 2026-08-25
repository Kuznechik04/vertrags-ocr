import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.template import ContractTemplate  # noqa: F401  (für relationship-Auflösung nötig)
from app.models.user import User  # noqa: F401  (für relationship-Auflösung nötig)


def gen_uuid() -> str:
    return str(uuid.uuid4())


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"          # hochgeladen, OCR noch nicht gelaufen
    PROCESSING = "processing"      # OCR läuft
    NEEDS_REVIEW = "needs_review"  # OCR fertig, wartet auf Validierung im UI
    REVIEWED = "reviewed"          # vom Nutzer vollständig validiert/korrigiert
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    template_id: Mapped[str] = mapped_column(ForeignKey("contract_templates.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, default="application/pdf")
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.UPLOADED
    )
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner: Mapped["User"] = relationship(back_populates="documents")
    template: Mapped["ContractTemplate"] = relationship()
    fields: Mapped[list["ContractField"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    @property
    def owner_email(self) -> str | None:
        return self.owner.email if self.owner else None


class ContractField(Base):
    """Ein einzelnes vom Modell erkanntes Feld (z.B. Vertragspartner, Betrag, Kündigungsfrist)."""

    __tablename__ = "contract_fields"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)

    field_key: Mapped[str] = mapped_column(String, nullable=False)   # z.B. "vertragspartner"
    field_label: Mapped[str] = mapped_column(String, nullable=False)  # z.B. "Vertragspartner"

    predicted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # Warum `predicted_value` fehlt (falls es fehlt) – siehe app.ocr.base.MatchStatus:
    # "matched" | "field_not_found" | "data_not_found" | "no_pattern".
    match_status: Mapped[str] = mapped_column(String, nullable=False, default="matched")

    # Position im Dokument, um die Fundstelle im Viewer hervorzuheben
    page: Mapped[int] = mapped_column(Integer, default=1)
    bbox_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_h: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    # True, wenn die Position (bbox_x/y/w/h + page) manuell vom Nutzer gesetzt/
    # korrigiert wurde (z.B. weil das Modell das Feld gar nicht erkannt hatte).
    # Nützlich als Trainingssignal für ein zukünftiges positionsbewusstes Modell
    # (z.B. LayoutLMv3) – siehe `training/prepare_dataset.py`.
    is_position_corrected: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped["Document"] = relationship(back_populates="fields")

    @property
    def final_value(self) -> str | None:
        return self.corrected_value if self.is_corrected else self.predicted_value
