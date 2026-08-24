from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.templates import router as templates_router
from app.core.config import settings
from app.core.db import Base, SessionLocal, engine
from app.models import document, template, user  # noqa: F401  (Modelle registrieren, damit create_all sie kennt)
from app.models.template import ContractTemplate, TemplateField

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(templates_router)

# Seed-Templates, mit denen die App startet. "versicherung" trägt die
# bisherigen Erkennungsmuster fürs Mock-Backend, "generisch" bewusst ohne
# Muster – neue Vertragstypen/Felder ohne automatische Erkennung lassen sich
# darüber (bzw. per POST /api/templates) trotzdem sofort im Review-UI nutzen.
SEED_TEMPLATES: list[dict] = [
    {
        "key": "versicherung",
        "name": "Versicherungsvertrag",
        "fields": [
            (
                "versicherungsnummer",
                "Versicherungsnummer",
                [
                    r"versicherungs(?:-)?nr\.?\s*:?\s*([A-Za-z0-9\-\/]+)",
                    r"versicherungsnummer\s*:?\s*([A-Za-z0-9\-\/]+)",
                    r"vsnr\.?\s*:?\s*([A-Za-z0-9\-\/]+)",
                ],
            ),
            ("versicherungsnehmer", "Versicherungsnehmer", [r"versicherungsnehmer(?:in)?\s*:?\s*([^\n\.]{3,60})"]),
            ("vertragspartner", "Vertragspartner", [r"vertragspartner\s*:?\s*([^\n\.]{3,60})"]),
            (
                "vertragsbeginn",
                "Vertragsbeginn",
                [r"vertragsbeginn\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})", r"beginn(?:datum)?\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})"],
            ),
            (
                "vertragsende",
                "Vertragsende",
                [r"vertragsende\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})", r"laufzeit\s*bis\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})"],
            ),
            ("kuendigungsfrist", "Kündigungsfrist", [r"kündigungsfrist\s*:?\s*([^\n\.]{3,40})"]),
            ("betrag", "Betrag / Preis", [r"(?:betrag|preis|entgelt)\s*:?\s*([\d\.,]+\s?(?:€|eur|euro))"]),
            ("zahlungsintervall", "Zahlungsintervall", [r"(monatlich|jährlich|quartalsweise|wöchentlich|einmalig)"]),
            ("unterschriftsdatum", "Unterschriftsdatum", [r"(?:datum|ort,\s*datum)\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})"]),
        ],
    },
    {
        "key": "generisch",
        "name": "Sonstiger Vertrag",
        "fields": [
            ("vertragspartner", "Vertragspartner", None),
            ("vertragsbeginn", "Vertragsbeginn", None),
            ("vertragsende", "Vertragsende", None),
            ("kuendigungsfrist", "Kündigungsfrist", None),
            ("betrag", "Betrag / Preis", None),
            ("unterschriftsdatum", "Unterschriftsdatum", None),
        ],
    },
]


def _seed_templates() -> None:
    db = SessionLocal()
    try:
        if db.query(ContractTemplate).first() is not None:
            return
        for template_def in SEED_TEMPLATES:
            tpl = ContractTemplate(key=template_def["key"], name=template_def["name"])
            db.add(tpl)
            db.flush()
            for order, (field_key, field_label, patterns) in enumerate(template_def["fields"]):
                db.add(
                    TemplateField(
                        template_id=tpl.id,
                        field_key=field_key,
                        field_label=field_label,
                        sort_order=order,
                        patterns=patterns,
                    )
                )
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    _seed_templates()


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "ocr_backend": settings.ocr_backend}
