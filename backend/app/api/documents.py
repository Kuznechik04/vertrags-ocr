import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_admin, get_current_user, get_current_user_flexible
from app.models.document import ContractField, Document, DocumentStatus
from app.models.template import ContractTemplate
from app.models.user import User, UserRole
from app.ocr.base import FieldSpec
from app.ocr.registry import get_ocr_model
from app.schemas.document import DocumentDetailOut, DocumentOut, FieldUpdate, TrainingExportRow
from app.services.xlsx_export import build_multi_document_xlsx, build_single_document_xlsx

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg"}


def _get_owned_document(document_id: str, user: User, db: Session) -> Document:
    """Lädt ein Dokument und prüft Zugriffsrechte: normale Nutzer dürfen nur
    ihre eigenen Dokumente sehen/bearbeiten, Admins alle."""
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Dokument nicht gefunden")
    if user.role != UserRole.ADMIN and document.owner_id != user.id:
        raise HTTPException(403, "Kein Zugriff auf dieses Dokument")
    return document


@router.post("/upload", response_model=DocumentDetailOut)
def upload_document(
    file: UploadFile = File(...),
    template_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"Dateityp nicht unterstützt: {file.content_type}")

    template = db.get(ContractTemplate, template_id)
    if not template:
        raise HTTPException(400, "Unbekannter Vertragstyp (template_id)")

    doc_id = str(uuid.uuid4())
    suffix = Path(file.filename or "upload").suffix or ".pdf"
    dest_path = settings.upload_dir / f"{doc_id}{suffix}"

    with dest_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    document = Document(
        id=doc_id,
        owner_id=user.id,
        template_id=template.id,
        filename=file.filename or dest_path.name,
        file_path=str(dest_path),
        content_type=file.content_type,
        status=DocumentStatus.PROCESSING,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        _run_ocr(document, db)
    except Exception as exc:  # noqa: BLE001
        document.status = DocumentStatus.FAILED
        document.error_message = str(exc)
        db.commit()
        raise HTTPException(500, f"OCR-Verarbeitung fehlgeschlagen: {exc}") from exc

    db.refresh(document)
    return document


def _run_ocr(document: Document, db: Session) -> None:
    model = get_ocr_model()
    document.page_count = model.page_count(document.file_path)
    fields = [
        FieldSpec(field_key=f.field_key, field_label=f.field_label, patterns=f.patterns)
        for f in document.template.fields
    ]
    predictions = model.predict(document.file_path, fields)

    for pred in predictions:
        bbox_x = bbox_y = bbox_w = bbox_h = None
        if pred.bbox:
            bbox_x, bbox_y, bbox_w, bbox_h = pred.bbox
        db.add(
            ContractField(
                document_id=document.id,
                field_key=pred.field_key,
                field_label=pred.field_label,
                predicted_value=pred.value,
                confidence=pred.confidence,
                match_status=pred.match_status,
                page=pred.page,
                bbox_x=bbox_x,
                bbox_y=bbox_y,
                bbox_w=bbox_w,
                bbox_h=bbox_h,
            )
        )

    document.status = DocumentStatus.NEEDS_REVIEW
    db.commit()


def _accessible_documents_query(user: User, db: Session):
    """Query aller für `user` sichtbaren Dokumente: eigene für normale Nutzer,
    alle für Admins. Zentral gehalten, damit Liste, Excel-Export & Co. dieselbe
    Zugriffsregel verwenden."""
    query = db.query(Document)
    if user.role != UserRole.ADMIN:
        query = query.filter(Document.owner_id == user.id)
    return query


@router.get("", response_model=list[DocumentOut])
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _accessible_documents_query(user, db).order_by(Document.uploaded_at.desc()).all()


@router.get("/export/training-data", response_model=list[TrainingExportRow])
def export_training_data(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Exportiert alle validierten Felder aller Nutzer als Trainingsdatensatz
    (Grundlage für `training/prepare_dataset.py`). Nur für Admins, da hier
    Vertragsdaten über Nutzergrenzen hinweg zusammengeführt werden."""
    documents = db.query(Document).filter(Document.status == DocumentStatus.REVIEWED).all()
    rows: list[TrainingExportRow] = []
    for doc in documents:
        for field in doc.fields:
            rows.append(
                TrainingExportRow(
                    document_id=doc.id,
                    filename=doc.filename,
                    field_key=field.field_key,
                    field_label=field.field_label,
                    predicted_value=field.predicted_value,
                    final_value=field.final_value,
                    was_corrected=field.is_corrected,
                    match_status=field.match_status,
                    confidence=field.confidence,
                    page=field.page,
                    bbox_x=field.bbox_x,
                    bbox_y=field.bbox_y,
                    bbox_w=field.bbox_w,
                    bbox_h=field.bbox_h,
                    was_position_corrected=field.is_position_corrected,
                )
            )
    return rows


@router.get("/export/xlsx")
def export_all_xlsx(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Excel-Export aller für den Nutzer sichtbaren Verträge (eigene für normale
    Nutzer, alle für Admins) – ein Blatt, eine Zeile pro erkanntem Feld."""
    documents = _accessible_documents_query(user, db).order_by(Document.uploaded_at.desc()).all()
    buffer = build_multi_document_xlsx(documents)
    return StreamingResponse(
        buffer,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="vertraege_export.xlsx"'},
    )


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get_owned_document(document_id, user, db)


@router.get("/{document_id}/export/xlsx")
def export_document_xlsx(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Excel-Export der Felder eines einzelnen Dokuments."""
    document = _get_owned_document(document_id, user, db)
    buffer = build_single_document_xlsx(document)
    safe_name = document.filename.rsplit(".", 1)[0] or "vertrag"
    return StreamingResponse(
        buffer,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.xlsx"'},
    )


@router.get("/{document_id}/file")
def get_document_file(
    document_id: str, user: User = Depends(get_current_user_flexible), db: Session = Depends(get_db)
):
    document = _get_owned_document(document_id, user, db)
    # content_disposition_type="inline" (statt des FastAPI-Standards "attachment"),
    # damit der Browser das PDF/Bild direkt im Viewer anzeigt statt es herunterzuladen.
    return FileResponse(
        document.file_path,
        media_type=document.content_type,
        filename=document.filename,
        content_disposition_type="inline",
    )


@router.put("/{document_id}/fields/{field_id}", response_model=DocumentDetailOut)
def update_field(
    document_id: str,
    field_id: str,
    payload: FieldUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _get_owned_document(document_id, user, db)

    field = db.get(ContractField, field_id)
    if not field or field.document_id != document_id:
        raise HTTPException(404, "Feld nicht gefunden")

    if payload.corrected_value is not None:
        field.corrected_value = payload.corrected_value
        field.is_corrected = field.corrected_value != (field.predicted_value or "")
        field.is_validated = True

    bbox_values = [payload.bbox_x, payload.bbox_y, payload.bbox_w, payload.bbox_h]
    if any(v is not None for v in bbox_values):
        if not all(v is not None for v in bbox_values):
            raise HTTPException(
                400,
                "Für eine Positionskorrektur müssen bbox_x, bbox_y, bbox_w und bbox_h "
                "zusammen angegeben werden.",
            )
        field.bbox_x, field.bbox_y, field.bbox_w, field.bbox_h = bbox_values
        if payload.page is not None:
            field.page = payload.page
        field.is_position_corrected = True
        field.is_validated = True

    if payload.is_validated is not None:
        field.is_validated = payload.is_validated

    db.commit()
    db.refresh(document)
    return document


@router.post("/{document_id}/finalize", response_model=DocumentDetailOut)
def finalize_document(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from datetime import datetime

    document = _get_owned_document(document_id, user, db)

    unvalidated = [f for f in document.fields if not f.is_validated]
    if unvalidated:
        raise HTTPException(
            400,
            f"{len(unvalidated)} Feld(er) sind noch nicht validiert: "
            + ", ".join(f.field_label for f in unvalidated),
        )

    document.status = DocumentStatus.REVIEWED
    document.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(document)
    return document


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    document = _get_owned_document(document_id, user, db)
    Path(document.file_path).unlink(missing_ok=True)
    db.delete(document)
    db.commit()
