"""Seiten-Cache der Mock-OCR: dieselbe Datei (gleicher Inhalt, egal unter
welchem Pfad) wird nur einmal extrahiert, fehlende Folgeseiten werden
nachträglich ergänzt statt das ganze Dokument neu zu erkennen."""
import pytest

from app.ocr import mock_model
from app.ocr.mock_model import MockOCRModel, PageData


@pytest.fixture(autouse=True)
def _empty_cache():
    mock_model.clear_page_cache()
    yield
    mock_model.clear_page_cache()


def _fake_document(monkeypatch, model, page_count):
    calls = []

    def fake_uncached(file_path, first_page=0, max_pages=None):
        calls.append((first_page, max_pages))
        end = page_count if max_pages is None else min(page_count, first_page + max_pages)
        return [PageData(lines=[]) for _ in range(first_page, end)]

    monkeypatch.setattr(model, "_extract_pages_uncached", fake_uncached)
    return calls


def test_same_content_is_extracted_once(tmp_path, monkeypatch):
    model = MockOCRModel()
    calls = _fake_document(monkeypatch, model, page_count=3)
    first = tmp_path / "suggest.pdf"
    second = tmp_path / "upload.pdf"
    first.write_bytes(b"%PDF-gleicher-inhalt")
    second.write_bytes(b"%PDF-gleicher-inhalt")

    assert len(model._extract_pages(str(first))) == 3
    assert len(model._extract_pages(str(second))) == 3
    assert len(model._extract_pages(str(second), max_pages=2)) == 2
    assert calls == [(0, None)]


def test_partial_extraction_is_extended_with_remaining_pages(tmp_path, monkeypatch):
    model = MockOCRModel()
    calls = _fake_document(monkeypatch, model, page_count=10)
    doc = tmp_path / "antrag.pdf"
    doc.write_bytes(b"%PDF-antrag")

    assert len(model._extract_pages(str(doc), max_pages=8)) == 8
    assert len(model._extract_pages(str(doc))) == 10
    assert len(model._extract_pages(str(doc))) == 10
    assert calls == [(0, 8), (8, None)]


def test_short_document_is_complete_after_partial_extraction(tmp_path, monkeypatch):
    model = MockOCRModel()
    calls = _fake_document(monkeypatch, model, page_count=3)
    doc = tmp_path / "kurz.pdf"
    doc.write_bytes(b"%PDF-kurz")

    assert len(model._extract_pages(str(doc), max_pages=8)) == 3
    assert len(model._extract_pages(str(doc))) == 3
    assert calls == [(0, 8)]


def test_different_content_is_not_shared(tmp_path, monkeypatch):
    model = MockOCRModel()
    calls = _fake_document(monkeypatch, model, page_count=1)
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"%PDF-a")
    b.write_bytes(b"%PDF-b")

    model._extract_pages(str(a))
    model._extract_pages(str(b))
    assert len(calls) == 2


def test_image_has_no_pages_after_the_first(tmp_path):
    from PIL import Image

    image = tmp_path / "scan.png"
    Image.new("RGB", (10, 10), "white").save(image)
    model = MockOCRModel()
    assert model._load_images(str(image), is_pdf=False, first_page=1) == []
