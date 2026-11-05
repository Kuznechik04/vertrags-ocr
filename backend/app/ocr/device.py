"""Wahl des torch-Rechengeräts für die OCR-Modelle (docTR, Donut).

Dieselbe Konfiguration läuft so ohne Anpassung auf einem Mac (MPS), einem
Rechner mit NVIDIA-Karte (CUDA) und einem reinen CPU-System.
"""
from app.core.config import settings


def torch_device() -> str:
    """Liefert den torch-Gerätenamen ("cuda", "mps" oder "cpu") gemäß
    `settings.ocr_device`. torch wird erst hier importiert, damit das
    Modul auch ohne installiertes torch importierbar bleibt."""
    import torch

    requested = (settings.ocr_device or "auto").lower()
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"
