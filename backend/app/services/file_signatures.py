"""Erkennt den tatsächlichen Dateityp anhand der ersten Bytes (Magic Bytes),
statt dem vom Client gesendeten `Content-Type`-Header zu vertrauen (der sich
beliebig gefälscht mitschicken lässt und keinerlei Garantie über den
tatsächlichen Dateiinhalt gibt)."""
from __future__ import annotations

SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}

EXTENSIONS: dict[str, str] = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


def sniff_content_type(head: bytes) -> str | None:
    """Gibt den erkannten Content-Type zurück, oder None, falls die Bytes zu
    keiner der unterstützten Signaturen passen."""
    for content_type, signatures in SIGNATURES.items():
        if any(head.startswith(sig) for sig in signatures):
            return content_type
    return None
