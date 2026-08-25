"""Zentrale Konfiguration der Anwendung, per Umgebungsvariablen (.env) steuerbar."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Allgemein
    app_name: str = "Vertrags-OCR"
    debug: bool = True

    # Datenbank
    database_url: str = "sqlite:///./vertrags_ocr.db"

    # Datei-Speicher (lokal für Dev; in Produktion z.B. S3/Blob Storage)
    upload_dir: Path = Path("./data/uploads")

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
    secret_key: str = "dev-only-insecure-secret-key-bitte-aendern"
    access_token_expire_minutes: int = 60 * 24  # 24h


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
