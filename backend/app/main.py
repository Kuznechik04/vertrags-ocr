import hmac

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.templates import router as templates_router
from app.core.config import settings
from app.core.db import Base, SessionLocal, engine
from app.models import document, template, user  # noqa: F401  (Modelle registrieren, damit create_all sie kennt)
from app.models.template import ContractTemplate, TemplateField

app = FastAPI(title=settings.app_name, debug=settings.debug)

# Die hartcodierten Dev-Origins gelten nur in der lokalen Entwicklung - in
# jeder anderen Umgebung zählt ausschließlich das konfigurierte
# FRONTEND_ORIGIN, damit CORS in Produktion nicht versehentlich offener ist
# als beabsichtigt.
_cors_origins = [settings.frontend_origin]
if settings.environment == "development":
    _cors_origins += ["http://localhost:5173", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpunkte, die einen Request ohne bereits bestehende Session verändern
# dürfen (Login/Register stellen die Session/CSRF-Cookies überhaupt erst
# aus) - alles andere mit einer "unsicheren" HTTP-Methode braucht ein
# gültiges CSRF-Token, sobald der Request über das Session-Cookie statt
# einen Authorization-Header authentifiziert wird.
_CSRF_EXEMPT_PATHS = {"/api/auth/login", "/api/auth/register"}
_CSRF_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-Submit-Cookie-CSRF-Schutz fürs Session-Cookie: das Frontend
    liest den nicht-httpOnly CSRF-Cookie per JS aus und schickt ihn als
    `X-CSRF-Token`-Header zurück; ein Angreifer, der nur Requests fremd
    auslösen (nicht aber den Cookie-Wert eines anderen Origins auslesen)
    kann, kennt den Wert nicht. Requests, die stattdessen per
    Authorization-Bearer-Header authentifizieren (API-Clients wie
    training/prepare_dataset.py), sind von CSRF nicht betroffen (Browser
    hängen diesen Header nicht automatisch an fremde Requests an) und
    werden deshalb ausgenommen."""

    async def dispatch(self, request: Request, call_next):
        if (
            request.method in _CSRF_UNSAFE_METHODS
            and request.url.path not in _CSRF_EXEMPT_PATHS
            and "authorization" not in request.headers
        ):
            cookie_token = request.cookies.get(settings.csrf_cookie_name)
            header_token = request.headers.get("x-csrf-token")
            if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
                return JSONResponse({"detail": "Fehlendes oder ungültiges CSRF-Token"}, status_code=403)
        return await call_next(request)


app.add_middleware(CSRFMiddleware)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # "self" reicht aus: das Frontend rendert ausschließlich über DOM-APIs
    # (kein innerHTML), braucht also keine "unsafe-inline"-Ausnahme.
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
    return response


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
