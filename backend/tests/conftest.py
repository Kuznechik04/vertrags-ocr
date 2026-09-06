"""Test-Setup: isolierte SQLite-Datei + Upload-Verzeichnis pro Testlauf, damit
Tests nie die echte lokale `.env`/`vertrags_ocr.db` berühren.

Die Umgebungsvariablen müssen gesetzt sein, bevor `app.core.config`/`app.main`
zum ersten Mal importiert werden (dort wird `Settings()` beim Modul-Import
instanziiert) - deshalb stehen sie vor den App-Imports.
"""
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vertrags_ocr_test_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DIR / 'test.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_TEST_DIR / "uploads"))
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("OCR_BACKEND", "mock")

from app.core.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    """FastAPI-TestClient mit frischer, leerer DB pro Test."""
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)
