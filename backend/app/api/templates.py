from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_admin, get_current_user
from app.models.template import ContractTemplate, TemplateField
from app.models.user import User
from app.schemas.template import TemplateCreate, TemplateFieldCreate, TemplateFieldUpdate, TemplateOut

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=list[TemplateOut])
def list_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Alle Vertragstyp-Templates inkl. ihrer Felder – für die Vertragstyp-Auswahl
    beim Upload und zum Anzeigen, welche Felder ein Template aktuell hat."""
    return db.query(ContractTemplate).all()


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(
    payload: TemplateCreate, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)
):
    """Legt einen neuen Vertragstyp an (z.B. für weitere Vertragsarten neben
    'versicherung'/'generisch'). Felder werden anschließend über
    POST /api/templates/{id}/fields ergänzt."""
    if db.query(ContractTemplate).filter(ContractTemplate.key == payload.key).first():
        raise HTTPException(400, f"Vertragstyp mit key '{payload.key}' existiert bereits")

    template = ContractTemplate(key=payload.key, name=payload.name)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.post("/{template_id}/fields", response_model=TemplateOut, status_code=201)
def add_template_field(
    template_id: str,
    payload: TemplateFieldCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Fügt einem bestehenden Vertragstyp ein neues Feld hinzu. So lassen sich
    Felder, die beim Anlegen des Templates noch nicht vorgesehen waren, später
    ergänzen und ab dem nächsten Upload mit diesem Template nutzen – mit
    optionalen Regex-Mustern fürs Mock-Backend, oder ganz ohne (dann bleibt das
    Feld leer, bis es im Review-UI manuell befüllt wird)."""
    template = db.get(ContractTemplate, template_id)
    if not template:
        raise HTTPException(404, "Vertragstyp nicht gefunden")

    if any(f.field_key == payload.field_key for f in template.fields):
        raise HTTPException(400, f"Feld-Key '{payload.field_key}' existiert in diesem Template bereits")

    next_order = max((f.sort_order for f in template.fields), default=-1) + 1
    db.add(
        TemplateField(
            template_id=template.id,
            field_key=payload.field_key,
            field_label=payload.field_label,
            sort_order=next_order,
            patterns=payload.patterns,
        )
    )
    db.commit()
    db.refresh(template)
    return template


@router.put("/{template_id}/fields/{field_id}", response_model=TemplateOut)
def update_template_field(
    template_id: str,
    field_id: str,
    payload: TemplateFieldUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Aktualisiert Anzeigename und Erkennungsmuster eines bestehenden Feldes –
    z.B. um ein zu weit gefasstes Muster nachträglich zu verschärfen, ohne das
    Feld löschen und neu anlegen zu müssen (der `field_key` bleibt dabei fix,
    da bereits existierende Dokumente darüber referenzieren)."""
    template = db.get(ContractTemplate, template_id)
    if not template:
        raise HTTPException(404, "Vertragstyp nicht gefunden")

    field = db.get(TemplateField, field_id)
    if not field or field.template_id != template_id:
        raise HTTPException(404, "Feld nicht gefunden")

    field.field_label = payload.field_label
    field.patterns = payload.patterns
    db.commit()
    db.refresh(template)
    return template
