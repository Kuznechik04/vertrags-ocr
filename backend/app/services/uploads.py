"""Gemeinsame Validierung für Datei-Uploads: echte Dokument-Uploads
(`app.api.documents.upload_document`) und temporäre Testdateien, die nur
kurzzeitig gebraucht werden (Muster-Vorschau, Vertragstyp-Vorschlag) und
nicht dauerhaft gespeichert werden sollen."""
from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.services.file_signatures import EXTENSIONS, sniff_content_type

ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg"}
UPLOAD_CHUNK_SIZE = 1024 * 1024


def sniff_and_validate(file: UploadFile) -> str:
    """Prüft die tatsächliche Dateisignatur (nicht den fälschbaren
    Client-`Content-Type`-Header) und gibt den erkannten Content-Type zurück,
    oder wirft eine 400, falls Typ nicht unterstützt/Datei beschädigt ist."""
    head = file.file.read(16)
    file.file.seek(0)
    sniffed_type = sniff_content_type(head)
    if sniffed_type is None or sniffed_type not in ALLOWED_TYPES:
        raise HTTPException(400, "Dateityp nicht unterstützt oder Datei beschädigt")
    return sniffed_type


@contextmanager
def temp_upload_file(file: UploadFile) -> Iterator[Path]:
    """Validiert (Signatur + Größenlimit, wie beim echten Dokument-Upload)
    und schreibt eine hochgeladene Datei in eine temporäre Datei, die nach
    Verlassen des Kontexts wieder gelöscht wird."""
    sniffed_type = sniff_and_validate(file)
    suffix = EXTENSIONS[sniffed_type]
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = Path(tmp.name)
    try:
        size = 0
        with tmp:
            while chunk := file.file.read(UPLOAD_CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"Datei zu groß (max. {settings.max_upload_size_mb} MB)")
                tmp.write(chunk)
        yield tmp_path
    finally:
        tmp_path.unlink(missing_ok=True)
