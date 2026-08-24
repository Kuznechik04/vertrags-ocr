"""Wählt das aktive OCR-Backend anhand der Konfiguration (`OCR_BACKEND`).

So kann zwischen dem sofort lauffähigen Mock-Backend und einem echten
fine-getunten Modell umgeschaltet werden, ohne Code in den API-Routen
anzufassen.
"""
from functools import lru_cache

from app.core.config import settings
from app.ocr.base import BaseOCRModel
from app.ocr.mock_model import MockOCRModel


@lru_cache
def get_ocr_model() -> BaseOCRModel:
    backend = settings.ocr_backend.lower()

    if backend == "mock":
        return MockOCRModel()

    if backend == "donut":
        from app.ocr.donut_model import DonutOCRModel

        return DonutOCRModel(settings.model_path)

    raise ValueError(f"Unbekanntes OCR_BACKEND: {backend!r} (erlaubt: 'mock', 'donut')")
