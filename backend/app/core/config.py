"""Zentrale Konfiguration der Anwendung, per Umgebungsvariablen (.env) steuerbar."""
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET_KEY = "dev-only-insecure-secret-key-bitte-aendern"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Allgemein
    app_name: str = "Vertrags-OCR"
    debug: bool = True
    # "development" (Standard) oder "production" - steuert, ob der unsichere
    # Default-SECRET_KEY sowie die hartcodierten Dev-CORS-Origins akzeptiert
    # werden (siehe _check_secret_key unten und main.py).
    environment: str = "development"

    # Datenbank
    database_url: str = "sqlite:///./vertrags_ocr.db"

    # Datei-Speicher (lokal für Dev; in Produktion z.B. S3/Blob Storage)
    upload_dir: Path = Path("./data/uploads")
    max_upload_size_mb: int = 25

    # OCR / Modell
    # "mock"  -> regelbasierte Demo-Extraktion, läuft ohne GPU/Modell
    # "donut" -> lädt ein fine-getuntes Donut-Modell aus `model_path`
    ocr_backend: str = "mock"
    model_path: str = "./training/output/contract-donut"

    # Nur relevant für ocr_backend="mock": welche OCR-Engine für gescannte
    # PDFs/Bild-Uploads genutzt wird (die eingebettete PDF-Textebene läuft
    # davon unabhängig immer über pdfplumber).
    # "doctr"     -> Standard, reines pip-Paket, kein natives Programm nötig.
    #                Beste Genauigkeit bei gedrucktem Text der drei Optionen,
    #                unterstützt Deutsch (inkl. Umlaute) direkt.
    # "easyocr"   -> ebenfalls reines pip-Paket, aber schwächer bei dichtem/
    #                klarem gedrucktem Fließtext als docTR.
    # "tesseract" -> braucht lokal installiertes tesseract-Kommandozeilen-
    #                programm (siehe README).
    mock_ocr_engine: str = "doctr"

    # CORS
    frontend_origin: str = "http://localhost:5173"

    # Auth / JWT
    # WICHTIG: In Produktion per Umgebungsvariable (.env) auf einen zufälligen,
    # geheimen Wert setzen, z.B. `python -c "import secrets; print(secrets.token_hex(32))"`
    secret_key: str = INSECURE_DEFAULT_SECRET_KEY
    access_token_expire_minutes: int = 60 * 24  # 24h

    @model_validator(mode="after")
    def _check_secret_key(self) -> "Settings":
        """Verhindert, dass ein Deployment mit ENVIRONMENT != "development"
        versehentlich mit dem öffentlich bekannten Default-JWT-Secret startet
        (damit ließen sich sonst Tokens beliebiger Nutzer/Admins fälschen)."""
        if self.environment != "development" and self.secret_key == INSECURE_DEFAULT_SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY ist noch der unsichere Default-Wert. Für ENVIRONMENT "
                "!= 'development' muss SECRET_KEY in der .env/Umgebung auf einen "
                "zufälligen, geheimen Wert gesetzt werden, z.B. mit "
                "`python -c \"import secrets; print(secrets.token_hex(32))\"`."
            )
        return self


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
