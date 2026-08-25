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
   Reines Python, kein natives Programm nötig.
2. Liefert Stufe 1 nichts oder nur sehr wenig Text (z.B. weil es sich um ein
   gescanntes Dokument oder ein hochgeladenes Bild handelt), wird als Fallback
   OCR auf die gerenderten Seiten angewendet. PDF-Seiten werden dafür über
   `PyMuPDF` (`fitz`) zu Bildern gerendert – ein reiner pip-Wheel mit
   eingebautem MuPDF, kein externes Programm nötig (anders als das früher
   genutzte `pdf2image`, das Poppler brauchte).

Welche OCR-Engine für Stufe 2 läuft, ist über `settings.mock_ocr_engine`
konfigurierbar (`.env`, Variable `MOCK_OCR_ENGINE`):
- `"easyocr"` (Standard): reines `pip install`, Modellgewichte werden beim
  ersten Lauf automatisch heruntergeladen, kein Installer/Admin-Recht nötig.
  Unterstützt Deutsch (inkl. Umlaute) und Englisch gemeinsam.
- `"tesseract"`: braucht das `tesseract`-Kommandozeilenprogramm lokal
  installiert (macOS: `brew install tesseract tesseract-lang`, Ubuntu/Debian:
  `apt install tesseract-ocr tesseract-ocr-deu`). Ist es nicht installiert,
  wird Stufe 2 übersprungen und die Extraktion liefert ggf. leeren Text.
  Teils präziser bei sehr dichtem/tabellarischem Text als EasyOCR.

Beide Engines liefern dieselben `Word`/`PageData`-Strukturen (Bounding-Boxen
auf 0..1 normiert, Konfidenz auf 0..100 skaliert), sodass das nachgelagerte
Regex-Matching (`_match_field_in_pages`) unabhängig von der gewählten Engine
identisch funktioniert.

Zur Konfidenz: Da dieses Backend nur Regex-Muster statt eines echten Modells
nutzt, gibt es keine "richtige" Wahrscheinlichkeit – ein trainiertes Modell
mit kalibrierten Wahrscheinlichkeiten liefert erst `DonutOCRModel`
(siehe `DonutOCRModel._sequence_confidence`, dort aus den Generation-Scores
berechnet). Die hier ausgegebene Konfidenz ist die durchschnittliche
OCR-Worterkennungssicherheit (0–100, von der jeweiligen Engine pro Wort
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

from app.core.config import settings
from app.ocr.base import BaseOCRModel, FieldPrediction, FieldSpec, MatchStatus

logger = logging.getLogger(__name__)

# Ab wie vielen Zeichen wir der eingebetteten PDF-Textebene vertrauen, statt
# zusätzlich auf OCR auszuweichen (kurze Fragmente deuten auf ein Scan-PDF hin,
# bei dem pdfplumber nur vereinzelte Artefakte statt echten Text findet).
MIN_TRUSTED_TEXT_LENGTH = 40


_easyocr_reader = None


def _get_easyocr_reader():
    """Lädt den EasyOCR-Reader (inkl. Modellgewichten) genau einmal pro
    Prozess – die Initialisierung ist teuer (mehrere Sekunden), sollte also
    nicht pro Upload neu passieren. `gpu=False`, damit es ohne CUDA-Setup
    überall gleich funktioniert; für Produktivbetrieb mit GPU ggf. anpassen."""
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr

        _easyocr_reader = easyocr.Reader(["de", "en"], gpu=False)
    return _easyocr_reader


_doctr_predictor = None


def _get_doctr_predictor():
    """Lädt den docTR-Predictor (inkl. Modellgewichten) genau einmal pro
    Prozess – wie bei EasyOCR ist die Initialisierung teuer."""
    global _doctr_predictor
    if _doctr_predictor is None:
        from doctr.models import ocr_predictor

        _doctr_predictor = ocr_predictor(pretrained=True)
    return _doctr_predictor


def _preprocess_image_for_ocr(image):
    """Leichte, engine-unabhängige Bildaufbereitung vor der OCR – hilft
    besonders bei unscharfen/kontrastarmen Scans und rohen Bild-Uploads
    (JPG/PNG), bei denen (anders als bei PDFs) keine DPI-Einstellung
    greift. Nutzt ausschließlich Pillow, keine zusätzliche
    Bildverarbeitungs-Bibliothek."""
    from PIL import Image, ImageFilter, ImageOps

    # Kleine Bilder hochskalieren – der einzige verfügbare "Auflösungs-
    # Hebel" bei rohen Bild-Uploads. Deckelt auf max. Faktor 3, um
    # Speicher/Rechenzeit bei winzigen Bildern nicht explodieren zu lassen.
    short_side = min(image.size)
    if short_side < 1500:
        scale = min(2000 / short_side, 3.0)
        image = image.resize(
            (round(image.width * scale), round(image.height * scale)),
            resample=Image.Resampling.LANCZOS,
        )

    gray = image.convert("L")
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    return gray.convert("RGB")


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


@dataclass
class FieldMatch:
    value: str | None
    confidence: float
    page: int
    bbox: tuple[float, float, float, float] | None
    match_status: MatchStatus


def _pattern_anchor_prefix(pattern: str) -> str:
    """Liefert den Teil eines Patterns VOR der ersten nicht-escapten
    öffnenden Klammer (= der "Anker"-Teil vor der Werte-Capture-Gruppe).
    Jedes Pattern in diesem System hat laut Konvention genau eine
    Capture-Gruppe für den Wert (siehe `match.span(1)` in
    `_match_field_in_pages`) – alles davor ist der Suchbegriff/Kontext, der
    unabhängig vom eigentlichen Wert geprüft werden kann."""
    i = 0
    while i < len(pattern):
        if pattern[i] == "\\":
            i += 2
            continue
        if pattern[i] == "(":
            return pattern[:i]
        i += 1
    return pattern  # keine Gruppe gefunden (Sonderfall bei frei getipptem Regex)


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
            predictions.append(
                FieldPrediction(
                    field_key=field.field_key,
                    field_label=field.field_label,
                    value=match.value,
                    confidence=match.confidence,
                    page=match.page,
                    bbox=match.bbox,
                    match_status=match.match_status,
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
            images = self._load_images(file_path, is_pdf)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Konnte Dokument nicht als Bild laden für OCR (%s): %s", file_path, exc)
            return []

        engine = (settings.mock_ocr_engine or "doctr").lower()
        if engine == "tesseract":
            return self._ocr_pages_with_tesseract(images)
        if engine == "easyocr":
            return self._ocr_pages_with_easyocr(images)
        return self._ocr_pages_with_doctr(images)

    def _load_images(self, file_path: str, is_pdf: bool) -> list:
        from PIL import Image

        if is_pdf:
            import fitz  # PyMuPDF

            # 400 statt der oft empfohlenen 300 DPI, da Vertrags-Fließtext/
            # Klauseln häufig kleine Schrift (<10pt) enthalten, bei der laut
            # OCR-Best-Practices höhere DPI die Erkennung spürbar verbessert.
            # Deckelt aber nur nach oben, was PyMuPDF aus dem PDF herausholen
            # KANN – ein mit niedriger Auflösung eingescanntes PDF gewinnt
            # dadurch keine Bildinformation hinzu, die nicht schon drin steckt.
            dpi = 400
            zoom = dpi / 72  # PyMuPDFs Basisauflösung ist 72 DPI
            matrix = fitz.Matrix(zoom, zoom)
            with fitz.open(file_path) as doc:
                images = [
                    Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    for pix in (page.get_pixmap(matrix=matrix) for page in doc)
                ]
        else:
            images = [Image.open(file_path).convert("RGB")]
        return [_preprocess_image_for_ocr(image) for image in images]

    def _ocr_pages_with_easyocr(self, images: list) -> list[PageData]:
        try:
            reader = _get_easyocr_reader()
        except ImportError:
            logger.warning(
                "easyocr ist nicht installiert – OCR-Fallback für gescannte Dokumente/"
                "Bilder wird übersprungen. `pip install easyocr` installieren."
            )
            return []

        import numpy as np

        pages: list[PageData] = []
        for image in images:
            width, height = image.size
            try:
                detections = reader.readtext(np.array(image), detail=1, paragraph=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("EasyOCR-Fallback fehlgeschlagen: %s", exc)
                pages.append(PageData(lines=[]))
                continue

            # EasyOCR liefert keine Block/Absatz/Zeilen-Nummern wie Tesseract,
            # daher hier dieselbe Zeilen-Heuristik wie beim pdfplumber-Pfad
            # (siehe _group_words_into_lines).
            words: list[Word] = []
            for bbox_points, text, confidence in detections:
                text = text.strip()
                if not text:
                    continue
                xs = [p[0] for p in bbox_points]
                ys = [p[1] for p in bbox_points]
                words.append(
                    Word(
                        text=text,
                        x0=min(xs) / width,
                        x1=max(xs) / width,
                        top=min(ys) / height,
                        bottom=max(ys) / height,
                        # EasyOCR liefert 0..1, hier auf die gemeinsame 0..100-Skala
                        # gebracht (wie Tesseracts conf), damit
                        # _average_word_confidence unverändert bleiben kann.
                        ocr_confidence=max(0.0, min(1.0, confidence)) * 100,
                    )
                )
            pages.append(PageData(lines=self._group_words_into_lines(words)))
        return pages

    def _ocr_pages_with_doctr(self, images: list) -> list[PageData]:
        try:
            predictor = _get_doctr_predictor()
        except ImportError:
            logger.warning(
                "python-doctr ist nicht installiert – OCR-Fallback für gescannte "
                "Dokumente/Bilder wird übersprungen. `pip install \"python-doctr[torch]\"` "
                "installieren."
            )
            return []

        import numpy as np

        try:
            result = predictor([np.array(image) for image in images])
        except Exception as exc:  # noqa: BLE001
            logger.warning("docTR-Fallback fehlgeschlagen: %s", exc)
            return [PageData(lines=[]) for _ in images]

        pages: list[PageData] = []
        for page in result.pages:
            # docTR liefert Wörter bereits nach Block/Zeile gruppiert (im
            # Gegensatz zu EasyOCR) – keine eigene Zeilen-Heuristik nötig.
            # `geometry` ist bei nicht-rotierten Boxen bereits
            # ((xmin, ymin), (xmax, ymax)) in relativen 0..1-Koordinaten,
            # identisch zur hier genutzten Konvention.
            lines: list[list[Word]] = []
            for block in page.blocks:
                for line in block.lines:
                    words = [
                        Word(
                            text=word.value.strip(),
                            x0=word.geometry[0][0],
                            top=word.geometry[0][1],
                            x1=word.geometry[1][0],
                            bottom=word.geometry[1][1],
                            ocr_confidence=max(0.0, min(1.0, word.confidence)) * 100,
                        )
                        for word in line.words
                        if word.value.strip()
                    ]
                    if words:
                        lines.append(words)
            pages.append(PageData(lines=lines))
        return pages

    def _ocr_pages_with_tesseract(self, images: list) -> list[PageData]:
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

        pages: list[PageData] = []
        for image in images:
            try:
                data = pytesseract.image_to_data(image, lang="deu+eng", output_type=Output.DICT)
            except Exception as exc:  # noqa: BLE001
                # z.B. tesseract-Binary nicht gefunden (TesseractNotFoundError)
                logger.warning("OCR-Fallback fehlgeschlagen: %s", exc)
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

    # ------------------------------------------------------------------
    # Feld-Matching über die extrahierten Wörter
    # ------------------------------------------------------------------

    def _match_field_in_pages(self, patterns: list[str], pages: list[PageData]) -> FieldMatch:
        if not patterns:
            return FieldMatch(value=None, confidence=0.0, page=1, bbox=None, match_status="no_pattern")

        # Pro Seite den durchsuchbaren Text + Wort-Spans einmal vorbereiten:
        # Leerzeichen zwischen Wörtern derselben Zeile, "\n" zwischen Zeilen
        # (wichtig, damit Muster wie `[^\n\.]{3,60}` nicht in die nächste
        # Zeile "hineinlesen"). Die Zeichen-Offsets pro Wort werden gemerkt,
        # um einen Regex-Treffer wieder auf die passenden Wort-Bounding-Boxes
        # abbilden zu können. Wird für den vollen Match-Versuch UND (falls
        # nötig) den Anker-only-Versuch wiederverwendet.
        page_texts: list[tuple[str, str, list[tuple[int, int, Word]]]] = []
        for page in pages:
            if not page.lines:
                page_texts.append(("", "", []))
                continue
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
            page_texts.append((joined_text, joined_text.lower(), spans))

        # Stufe 1: volles Muster (Anker + Wert) suchen.
        for page_number, (joined_text, joined_lower, spans) in enumerate(page_texts, start=1):
            if not joined_lower:
                continue

            for pattern in patterns:
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
                return FieldMatch(value=value, confidence=confidence, page=page_number, bbox=bbox, match_status="matched")

        # Stufe 2: kein volles Muster hat gematcht. Prüfen, ob wenigstens der
        # Anker-Teil (vor der Werte-Gruppe) irgendwo vorkommt, um "Feld nicht
        # gefunden" von "Feld gefunden, aber kein Wert erkannt" zu unterscheiden.
        for _joined_text, joined_lower, _spans in page_texts:
            if not joined_lower:
                continue
            for pattern in patterns:
                anchor = _pattern_anchor_prefix(pattern)
                if not anchor:
                    continue
                try:
                    if re.search(anchor, joined_lower, flags=re.IGNORECASE):
                        return FieldMatch(value=None, confidence=0.0, page=1, bbox=None, match_status="data_not_found")
                except re.error:
                    # Frei getipptes Admin-Regex, dessen Präfix allein nicht
                    # kompilierbar ist – für dieses Pattern keine Aussage
                    # möglich, konservativ als "nicht gefunden" werten.
                    continue

        return FieldMatch(value=None, confidence=0.0, page=1, bbox=None, match_status="field_not_found")
