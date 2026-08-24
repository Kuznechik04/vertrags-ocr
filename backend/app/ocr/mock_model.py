"""Regelbasiertes Demo-Backend.

Extrahiert Text (inkl. Wortpositionen) aus dem Dokument und sucht darin per
Regex-Heuristiken nach typischen Vertragsfeldern. Das ist KEIN trainiertes
ML-Modell, sondern ein Platzhalter, damit die App von Tag 1 an ohne
GPU/Trainingsdaten lauffähig ist und die Weboberfläche end-to-end getestet
werden kann. Sobald echte Trainingsdaten (validierte Korrekturen) vorliegen,
kann auf `DonutOCRModel` umgeschaltet werden.

Text-Extraktion in zwei Stufen (jeweils inkl. Wort-Bounding-Boxes, damit die
Fundstelle im Frontend markiert werden kann):
1. `pdfplumber` liest die eingebettete Textebene eines PDFs (schnell, exakt,
   funktioniert aber nur, wenn das PDF "echten" Text enthält statt nur Bildern).
2. Liefert Stufe 1 nichts oder nur sehr wenig Text (z.B. weil es sich um ein
   gescanntes Dokument oder ein hochgeladenes Bild handelt), wird als Fallback
   Tesseract-OCR (`pytesseract`) auf die gerenderten Seiten angewendet.

Für Tesseract muss das `tesseract`-Kommandozeilenprogramm lokal installiert
sein (macOS: `brew install tesseract tesseract-lang`, Ubuntu/Debian:
`apt install tesseract-ocr tesseract-ocr-deu`). Ist es nicht installiert,
wird Stufe 2 übersprungen und die Extraktion liefert ggf. leeren Text.

Zur Konfidenz: Da dieses Backend nur Regex-Muster statt eines echten Modells
nutzt, gibt es keine "richtige" Wahrscheinlichkeit – ein trainiertes Modell
mit kalibrierten Wahrscheinlichkeiten liefert erst `DonutOCRModel`
(siehe `DonutOCRModel._sequence_confidence`, dort aus den Generation-Scores
berechnet). Die hier ausgegebene Konfidenz ist die durchschnittliche
Tesseract-Worterkennungssicherheit (0–100, von Tesseract selbst pro Wort
geliefert) der Wörter, die zum gefundenen Feldwert gehören – siehe
`_average_word_confidence`. Stammt der Treffer aus der eingebetteten
PDF-Textebene (pdfplumber) statt aus OCR, gibt es keine Erkennungsunsicherheit
(der Text ist exakt, keine Bildinterpretation nötig) – dort wird 100%
angesetzt. Welches der Regex-Muster in `PATTERNS` getroffen hat, fließt
bewusst NICHT mehr in die Konfidenz ein (das war reine Musterspezifität,
keine tatsächliche Lesesicherheit).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import pdfplumber

from app.ocr.base import BaseOCRModel, FieldPrediction, FieldSpec

logger = logging.getLogger(__name__)

# Ab wie vielen Zeichen wir der eingebetteten PDF-Textebene vertrauen, statt
# zusätzlich auf OCR auszuweichen (kurze Fragmente deuten auf ein Scan-PDF hin,
# bei dem pdfplumber nur vereinzelte Artefakte statt echten Text findet).
MIN_TRUSTED_TEXT_LENGTH = 40


def _average_word_confidence(words: list["Word"]) -> float:
    """Mittelt die Tesseract-Wortkonfidenz (0..100) der an einem Treffer
    beteiligten Wörter und normiert sie auf 0..1. Wörter ohne OCR-Konfidenz
    (= aus der eingebetteten PDF-Textebene, exakter Text statt Erkennung)
    werden mit voller Konfidenz (1.0) gewertet, da dort keine Bilderkennung
    stattfand, die hätte unsicher sein können."""
    values = [w.ocr_confidence for w in words if w.ocr_confidence is not None]
    if not values:
        return 1.0
    avg = sum(values) / len(values)
    return max(0.0, min(1.0, avg / 100))


@dataclass
class Word:
    text: str
    x0: float  # alle Koordinaten bereits relativ zur Seite normiert (0..1)
    x1: float
    top: float
    bottom: float
    # Tesseract-Worterkennungssicherheit (0..100), nur gesetzt wenn das Wort
    # über den OCR-Fallback stammt. `None` = aus der eingebetteten PDF-Textebene
    # (exakter Text, keine Erkennungsunsicherheit).
    ocr_confidence: float | None = None


@dataclass
class PageData:
    # Wörter gruppiert nach Zeile (in Lesereihenfolge), damit beim Zusammenfügen
    # zu durchsuchbarem Text echte Zeilenumbrüche erhalten bleiben – sonst
    # könnten gierige Muster wie `[^\n\.]{3,60}` über das Zeilenende hinweg in
    # die nächste Zeile "hineinlesen".
    lines: list[list[Word]]


class MockOCRModel(BaseOCRModel):
    def page_count(self, file_path: str) -> int:
        if not file_path.lower().endswith(".pdf"):
            return 1
        with pdfplumber.open(file_path) as pdf:
            return len(pdf.pages)

    def predict(self, file_path: str, fields: list[FieldSpec]) -> list[FieldPrediction]:
        pages = self._extract_pages(file_path)

        predictions: list[FieldPrediction] = []
        for field in fields:
            match = self._match_field_in_pages(field.patterns or [], pages)
            if match:
                value, confidence, page_number, bbox = match
            else:
                value, confidence, page_number, bbox = None, 0.0, 1, None
            predictions.append(
                FieldPrediction(
                    field_key=field.field_key,
                    field_label=field.field_label,
                    value=value,
                    confidence=confidence,
                    page=page_number,
                    bbox=bbox,
                )
            )
        return predictions

    # ------------------------------------------------------------------
    # Text-/Wort-Extraktion
    # ------------------------------------------------------------------

    def _extract_pages(self, file_path: str) -> list[PageData]:
        is_pdf = file_path.lower().endswith(".pdf")

        pdf_pages = self._extract_pages_via_pdfplumber(file_path) if is_pdf else []
        total_chars = sum(len(w.text) for page in pdf_pages for line in page.lines for w in line)

        if total_chars >= MIN_TRUSTED_TEXT_LENGTH:
            return pdf_pages

        # Kein/kaum Text gefunden -> vermutlich gescanntes PDF oder direkt ein
        # Bild-Upload. Fallback auf Tesseract-OCR (liefert Wortpositionen als Pixel,
        # die wir ebenfalls auf 0..1 normieren).
        ocr_pages = self._extract_pages_via_ocr(file_path, is_pdf)
        if any(page.lines for page in ocr_pages):
            return ocr_pages
        return pdf_pages

    def _extract_pages_via_pdfplumber(self, file_path: str) -> list[PageData]:
        pages: list[PageData] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                width, height = page.width, page.height
                if not width or not height:
                    pages.append(PageData(lines=[]))
                    continue

                words = [
                    Word(
                        text=w["text"],
                        x0=w["x0"] / width,
                        x1=w["x1"] / width,
                        top=w["top"] / height,
                        bottom=w["bottom"] / height,
                    )
                    for w in page.extract_words()
                ]
                pages.append(PageData(lines=self._group_words_into_lines(words)))
        return pages

    def _group_words_into_lines(self, words: list[Word]) -> list[list[Word]]:
        """Gruppiert Wörter (bereits in Lesereihenfolge) anhand ihrer vertikalen
        Position in Zeilen. `pdfplumber.extract_words()` liefert keine expliziten
        Zeilennummern, daher der Heuristik-Ansatz: Ein neues Wort startet eine
        neue Zeile, wenn es deutlich weiter unten beginnt als das vorherige Wort
        (mehr als die halbe Zeilenhöhe des vorherigen Worts)."""
        lines: list[list[Word]] = []
        current_line: list[Word] = []
        prev_word: Word | None = None

        for word in words:
            if prev_word is not None:
                prev_height = max(prev_word.bottom - prev_word.top, 0.001)
                if word.top - prev_word.top > prev_height * 0.5:
                    lines.append(current_line)
                    current_line = []
            current_line.append(word)
            prev_word = word

        if current_line:
            lines.append(current_line)
        return lines

    def _extract_pages_via_ocr(self, file_path: str, is_pdf: bool) -> list[PageData]:
        try:
            import pytesseract
            from pytesseract import Output
        except ImportError:
            logger.warning(
                "pytesseract ist nicht installiert – OCR-Fallback für gescannte "
                "Dokumente/Bilder wird übersprungen. `pip install pytesseract` "
                "und das tesseract-Kommandozeilenprogramm installieren."
            )
            return []

        try:
            images = self._load_images(file_path, is_pdf)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Konnte Dokument nicht als Bild laden für OCR (%s): %s", file_path, exc)
            return []

        pages: list[PageData] = []
        for image in images:
            try:
                data = pytesseract.image_to_data(image, lang="deu+eng", output_type=Output.DICT)
            except Exception as exc:  # noqa: BLE001
                # z.B. tesseract-Binary nicht gefunden (TesseractNotFoundError)
                logger.warning("OCR-Fallback fehlgeschlagen für %s: %s", file_path, exc)
                pages.append(PageData(lines=[]))
                continue

            width, height = image.size
            # Tesseract liefert block_num/par_num/line_num pro Wort mit – im
            # Gegensatz zu pdfplumber brauchen wir hier also keine Heuristik,
            # um Zeilenumbrüche zu erkennen.
            lines: list[list[Word]] = []
            current_key = None
            current_line: list[Word] = []
            for i, text in enumerate(data["text"]):
                text = text.strip()
                if not text:
                    continue
                line_key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
                if current_key is not None and line_key != current_key:
                    lines.append(current_line)
                    current_line = []
                current_key = line_key

                left, top = data["left"][i], data["top"][i]
                w, h = data["width"][i], data["height"][i]
                try:
                    conf = float(data["conf"][i])
                except (TypeError, ValueError):
                    conf = None
                # Tesseract nutzt -1 für Zeilen/Absatz-/Block-Container statt
                # echter Worttreffer; da wir nur Zeilen mit nicht-leerem Text
                # aufnehmen, sollte das hier praktisch nicht vorkommen, aber
                # zur Sicherheit trotzdem abfangen.
                if conf is not None and conf < 0:
                    conf = None
                current_line.append(
                    Word(
                        text=text,
                        x0=left / width,
                        x1=(left + w) / width,
                        top=top / height,
                        bottom=(top + h) / height,
                        ocr_confidence=conf,
                    )
                )
            if current_line:
                lines.append(current_line)
            pages.append(PageData(lines=lines))
        return pages

    def _load_images(self, file_path: str, is_pdf: bool) -> list:
        from PIL import Image

        if is_pdf:
            from pdf2image import convert_from_path

            return [p.convert("RGB") for p in convert_from_path(file_path, dpi=300)]
        return [Image.open(file_path).convert("RGB")]

    # ------------------------------------------------------------------
    # Feld-Matching über die extrahierten Wörter
    # ------------------------------------------------------------------

    def _match_field_in_pages(
        self, patterns: list[str], pages: list[PageData]
    ) -> tuple[str, float, int, tuple[float, float, float, float]] | None:
        if not patterns:
            return None

        for page_number, page in enumerate(pages, start=1):
            if not page.lines:
                continue

            # Wörter zu durchsuchbarem Text zusammenfügen: Leerzeichen zwischen
            # Wörtern derselben Zeile, "\n" zwischen Zeilen (wichtig, damit
            # Muster wie `[^\n\.]{3,60}` nicht in die nächste Zeile "hineinlesen").
            # Dabei werden die Zeichen-Offsets pro Wort gemerkt, um einen
            # Regex-Treffer wieder auf die passenden Wort-Bounding-Boxes abbilden
            # zu können.
            joined_parts: list[str] = []
            spans: list[tuple[int, int, Word]] = []  # (start, end, word)
            cursor = 0
            for line_index, line in enumerate(page.lines):
                if line_index > 0:
                    joined_parts.append("\n")
                    cursor += 1
                for word_index, word in enumerate(line):
                    if word_index > 0:
                        joined_parts.append(" ")
                        cursor += 1
                    start = cursor
                    joined_parts.append(word.text)
                    cursor += len(word.text)
                    spans.append((start, cursor, word))
            joined_text = "".join(joined_parts)
            joined_lower = joined_text.lower()

            for pattern_index, pattern in enumerate(patterns):
                match = re.search(pattern, joined_lower, flags=re.IGNORECASE)
                if not match:
                    continue

                group_start, group_end = match.span(1)
                covered_words = [w for (s, e, w) in spans if s < group_end and e > group_start]
                if not covered_words:
                    continue

                value = joined_text[group_start:group_end].strip(" .:")
                if not value:
                    continue

                bbox = (
                    min(w.x0 for w in covered_words),
                    min(w.top for w in covered_words),
                    0.0,
                    0.0,
                )
                max_x1 = max(w.x1 for w in covered_words)
                max_bottom = max(w.bottom for w in covered_words)
                bbox = (bbox[0], bbox[1], max_x1 - bbox[0], max_bottom - bbox[1])

                confidence = round(_average_word_confidence(covered_words), 4)
                return value, confidence, page_number, bbox

        return None
