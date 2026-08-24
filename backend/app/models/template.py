"""Vertragstyp-Templates: Jedes Template definiert einen Satz von Feldern, die
für diesen Vertragstyp erkannt/erfasst werden sollen. So lassen sich neue
Vertragstypen bzw. neue Felder eines Typs anlegen, ohne Code zu ändern (siehe
`app/api/templates.py`)."""
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class ContractTemplate(Base):
    __tablename__ = "contract_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    key: Mapped[str] = mapped_column(String, unique=True, nullable=False)  # z.B. "versicherung"
    name: Mapped[str] = mapped_column(String, nullable=False)  # Anzeigename
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    fields: Mapped[list["TemplateField"]] = relationship(
        back_populates="template", cascade="all, delete-orphan", order_by="TemplateField.sort_order"
    )


class TemplateField(Base):
    """Ein Feld innerhalb eines Vertragstyp-Templates. `patterns` sind optionale
    Regex-Muster fürs Mock-Backend – ohne Muster wird das Feld nie automatisch
    erkannt, bleibt aber im Review-UI vorhanden und manuell befüllbar. So lassen
    sich neue, unbekannte Felder sofort nutzen, auch bevor ein Muster oder ein
    trainiertes Modell dafür existiert."""

    __tablename__ = "template_fields"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    template_id: Mapped[str] = mapped_column(ForeignKey("contract_templates.id"), nullable=False)

    field_key: Mapped[str] = mapped_column(String, nullable=False)
    field_label: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    patterns: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    template: Mapped["ContractTemplate"] = relationship(back_populates="fields")
