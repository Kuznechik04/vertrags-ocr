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

import hashlib
import logging
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass

import pdfplumber
import regex

from app.core.config import settings
from app.ocr.base import BaseOCRModel, FieldPrediction, FieldSpec, MatchStatus
from app.ocr.mlp_template import RELEVANT_PAGE_COUNT

logger = logging.getLogger(__name__)

# Ab wie vielen Zeichen wir der eingebetteten PDF-Textebene vertrauen, statt
# zusätzlich auf OCR auszuweichen (kurze Fragmente deuten auf ein Scan-PDF hin,
# bei dem pdfplumber nur vereinzelte Artefakte statt echten Text findet).
MIN_TRUSTED_TEXT_LENGTH = 40

# Horizontale Lücke (relativ zur Seitenbreite) zwischen zwei Wörtern derselben
# Zeile, ab der sie als Grenze zwischen zwei Tabellenzellen gilt und im
# durchsuchbaren Text als "\t" statt " " landet (siehe `_match_field_in_pages`).
# Das MLP-Formular ist tabellarisch (Label-Spalte links, Wert-Spalte rechts) -
# an zwei echten docTR-Läufen gemessen: Wortabstände INNERHALB einer Zelle
# lagen bei < 1,2 %, zwischen Label- und Wertzelle bei 1,7-50 %.
CELL_GAP_THRESHOLD = 0.02


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
_doctr_load_lock = threading.Lock()


def _get_doctr_predictor():
    """Lädt den docTR-Predictor (inkl. Modellgewichten) genau einmal pro
    Prozess – wie bei EasyOCR ist die Initialisierung teuer. Der Lock
    verhindert doppeltes Laden, wenn der Preload beim Serverstart und der
    erste Upload gleichzeitig hier ankommen. Läuft auf GPU (CUDA/MPS),
    falls vorhanden - auf Apple Silicon gemessen ~8x schneller als CPU."""
    global _doctr_predictor
    with _doctr_load_lock:
        if _doctr_predictor is None:
            from doctr.models import ocr_predictor

            from app.ocr.device import torch_device

            _doctr_predictor = ocr_predictor(pretrained=True).to(torch_device())
    return _doctr_predictor


def preload_ocr_engine() -> None:
    """Lädt die konfigurierte OCR-Engine vorab (siehe `settings.ocr_preload`,
    aufgerufen aus einem Hintergrund-Thread beim Serverstart in main.py).
    Tesseract braucht keinen Preload: es ist ein externes Programm, das pro
    Aufruf gestartet wird und keine Gewichte im Python-Prozess hält."""
    engine = (settings.mock_ocr_engine or "doctr").lower()
    try:
        if engine == "doctr":
            _get_doctr_predictor()
        elif engine == "easyocr":
            _get_easyocr_reader()
    except ImportError:
        pass  # Fehlende Engine wird beim ersten echten OCR-Lauf geloggt.


# Cache der extrahierten Seiten, Schlüssel = SHA-256 des Dateiinhalts. Der
# Upload-Dialog extrahiert dieselbe Datei erst für den Vertragstyp-Vorschlag
# (POST /api/templates/suggest) und direkt danach für den eigentlichen Upload
# - ohne Cache lief die teure OCR dafür zweimal. Bewusst klein und nur im
# Arbeitsspeicher (verschwindet mit dem Prozess).
_PAGE_CACHE_SIZE = 16
_page_cache: OrderedDict[tuple, "_CachedPages"] = OrderedDict()
# Serialisiert die eigentliche Extraktion: parallele OCR-Läufe würden sich
# nur gegenseitig CPU/GPU wegnehmen, und eine zweite Anfrage für dieselbe
# Datei findet nach dem Warten das Ergebnis bereits im Cache.
_extraction_lock = threading.Lock()


@dataclass
class _CachedPages:
    """Cache-Eintrag eines Dokuments. `pages` enthält immer einen lückenlosen
    Anfang des Dokuments (Seite 1..n) - bei `complete=False` können danach
    noch weitere Seiten folgen, die bisher nicht gebraucht wurden."""

    pages: list["PageData"]
    complete: bool  # True = alle Seiten des Dokuments extrahiert


def _file_digest(file_path: str) -> str:
    """Hash über den Dateiinhalt statt über den Pfad: der Vorschlag arbeitet
    auf einer temporären Datei, der Upload auf der endgültig gespeicherten -
    beide haben unterschiedliche Pfade, aber denselben Inhalt. Liest in
    1-MB-Blöcken, damit große PDFs nicht komplett im Speicher landen."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clear_page_cache() -> None:
    """Leert den Seiten-Cache (vor allem für Tests, damit sie sich nicht
    gegenseitig Ergebnisse unterschieben)."""
    _page_cache.clear()


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
    # True, wenn mindestens zwei unterschiedliche Muster für dasselbe Feld
    # auf voneinander abweichende Werte gekommen sind - ein Signal an den
    # menschlichen Prüfer, dass die automatische Erkennung sich hier nicht
    # sicher ist, statt das stillschweigend zu verschlucken.
    ambiguous: bool = False


# Fragment, das patternTypeFields.ts (Frontend) für die generische
# "Freitext"-Catch-all-Werterkennung erzeugt (siehe VALUE_PATTERNS.freitext,
# `[^\n\.]{3,80}`). Kein Versuch, Presets vollständig zu erkennen - nur ein
# grober, dokumentierter Spezifitäts-Abschlag auf die Konfidenz, damit "vom
# OCR gut lesbar" nicht mit "von einem spezifischen Muster erkannt"
# verwechselt wird (ein sehr weit gefasstes Muster kann den falschen
# Textabschnitt genauso "gut lesbar" treffen wie den richtigen).
_GENERIC_FREITEXT_FRAGMENT = r"[^\n\.]{"
_FREITEXT_CONFIDENCE_DISCOUNT = 0.85


def _is_generic_freitext_pattern(pattern: str) -> bool:
    return _GENERIC_FREITEXT_FRAGMENT in pattern


@dataclass
class _Candidate:
    pattern_index: int
    page_number: int
    value: str
    confidence: float
    bbox: tuple[float, float, float, float]


_UMLAUT_FOLD = str.maketrans(
    {"ü": "u", "Ü": "U", "ä": "a", "Ä": "A", "ö": "o", "Ö": "O", "ß": "b", "ẞ": "B"}
)


def _fold_umlauts(text: str) -> str:
    """Faltet deutsche Umlaute auf ihren Grundbuchstaben (ü->u, ä->a, ö->o) -
    jede Ersetzung ist genau 1 Zeichen für 1 Zeichen, damit Zeichen-Offsets
    für die Wort-Bounding-Box-Zuordnung erhalten bleiben (anders als z.B.
    ü->ue, was die Länge verändern würde). Manche OCR-Engines lassen bei
    bestimmten Schriftarten/Scans die Umlaut-Punkte weg (beobachtet z.B. bei
    "Kündigungsfrist" -> "Kundigungsfrist", "München" -> "Munchen") - ein
    Admin-Suchbegriff mit korrekt geschriebenem Umlaut würde dann nie
    matchen. Nur als Fallback genutzt, wenn die direkte Suche fehlschlägt,
    damit ein korrekt erkannter Umlaut weiterhin Vorrang hat.

    ß->b (statt der eigentlich korrekten Transkription "ss", die die Länge
    verändern würde) deckt einen an einem echten docTR-gescannten Dokument
    beobachteten, sehr konsistenten Fehler ab: "Einschluß" -> "EinschluB",
    "geschweißte" -> "geschweiBte", "Baumaßnahmen" -> "BaumaBnahmen" - die
    OCR liest ß systematisch als großes B. Da hier auf dem bereits
    kleingeschriebenen Seitentext (`joined_lower`) gematcht wird, faltet
    "b" zwar nicht zurück auf "B" selbst, aber die Ziel-Abbildung ist
    trotzdem eindeutig: "ß" im (korrekt geschriebenen) Suchmuster wird zu
    "b" gefaltet, genau wie das "b", das die OCR bereits anstelle von "ß"
    geliefert hat - beide Seiten landen also auf demselben Zeichen."""
    return text.translate(_UMLAUT_FOLD)


def _pattern_anchor_prefix(pattern: str) -> str:
    """Liefert den Teil eines Patterns VOR der ersten nicht-escapten
    öffnenden Klammer der Werte-Capture-Gruppe (= der "Anker"-Teil davor).
    Jedes Pattern in diesem System hat laut Konvention genau eine
    Capture-Gruppe für den Wert (siehe `match.span(1)` in
    `_match_field_in_pages`) – alles davor ist der Suchbegriff/Kontext, der
    unabhängig vom eigentlichen Wert geprüft werden kann.

    Eine `(` allein reicht dafür nicht als Erkennungsmerkmal: Abschnitts-
    gescopte Muster (siehe `_scoped_label` in mlp_template.py) enthalten VOR
    der eigentlichen Werte-Gruppe zusätzlich eine nicht-capturing Gruppe
    `(?:...)` für den Kontext-Anker - "(?" wird daher übersprungen statt als
    Gruppenstart gewertet, sonst würde der Anker-Nachweis in Stufe 2 nur den
    (oft leeren) Teil vor dieser nicht-capturing Gruppe prüfen."""
    i = 0
    while i < len(pattern):
        if pattern[i] == "\\":
            i += 2
            continue
        if pattern[i] == "(":
            if pattern[i + 1 : i + 2] == "?":
                i += 2
                continue
            return pattern[:i]
        i += 1
    return pattern  # keine Gruppe gefunden (Sonderfall bei frei getipptem Regex)


def _candidate_from_match(
    match, pattern_index: int, page_number: int, joined_text: str, spans: list[tuple[int, int, Word]], pattern: str
) -> _Candidate | None:
    """Bildet einen Regex-Treffer (Werte-Gruppe 1) auf die abgedeckten Wörter
    ab und baut daraus Wert, Bounding-Box und Konfidenz."""
    group_start, group_end = match.span(1)
    covered_words = [w for (s, e, w) in spans if s < group_end and e > group_start]
    if not covered_words:
        return None

    value = joined_text[group_start:group_end].strip(" .:\t")
    if not value:
        return None

    x0 = min(w.x0 for w in covered_words)
    top = min(w.top for w in covered_words)
    bbox = (x0, top, max(w.x1 for w in covered_words) - x0, max(w.bottom for w in covered_words) - top)

    confidence = round(_average_word_confidence(covered_words), 4)
    if _is_generic_freitext_pattern(pattern):
        confidence = round(confidence * _FREITEXT_CONFIDENCE_DISCOUNT, 4)
    return _Candidate(
        pattern_index=pattern_index, page_number=page_number, value=value, confidence=confidence, bbox=bbox
    )


# Unscharfe Label-Suche (Stufe 1b in `_match_field_in_pages`): OCR liest
# Labels in Scans regelmäßig mit einzelnen falschen Zeichen - an echten
# docTR-Läufen beobachtet u.a. "gewinscht" (gewünscht), "Ber@cksichtigung",
# "Gefahrerhôhung", "inJ Jahren". Der exakte Anker scheitert dann komplett,
# obwohl der Wert dahinter sauber gelesen wurde.
#
# Fehlerbudget nach Anzahl BUCHSTABEN im Anker (Ziffern zählen bewusst nicht):
# Klausel-Codes wie "T590080k"/"T590081k" unterscheiden sich in nur einem
# Zeichen - ein Fehlerbudget dort würde die Codes miteinander verwechseln.
# Kurze Labels ("Name", "IBAN", "PLZ Risikoort") bleiben exakt, weil ein
# Fehler dort schon ein ganz anderes Wort trifft.
_FUZZY_MIN_LETTERS = 12
_FUZZY_LETTERS_PER_ERROR = 12
_FUZZY_MAX_ERRORS = 3
# Unscharfer Treffer = Label nicht exakt gelesen -> geringere Sicherheit,
# damit der Prüfer im Review genauer hinsieht.
_FUZZY_CONFIDENCE_DISCOUNT = 0.8
# Schutz gegen Laufzeit-Ausreißer: unscharfe Suche ist teurer als exakte.
_FUZZY_TIMEOUT_SECONDS = 2.0
_REGEX_CLASS_ESCAPE = re.compile(r"\\[sSdDwWbBnt]")


def _fuzzy_anchor_pattern(pattern: str) -> str | None:
    """Liefert `pattern` mit unscharf (Fehlertoleranz `{e<=n}` des
    `regex`-Pakets) gesuchtem Anker-Teil - die Werte-Gruppe bleibt exakt,
    damit ein OCR-Fehler im Label nicht auch noch einen falschen Wert
    zulässt. `None`, wenn der Anker zu kurz/codeartig ist (siehe oben) oder
    einen Abschnitts-Scope (`.*?`, siehe `_scoped_label`) enthält: dort
    würde die Fehlertoleranz über beliebig langen Text gestreckt.

    Ebenfalls `None` bei Lookarounds im Anker (`(?<!grund)selbstbeteiligung`,
    `not_followed_by` in `_scoped_label`): das sind bewusste Ausschlüsse
    bekannter Kollisionen, die eine Fehlertoleranz umgehen würde - an einem
    echten Scan nachgewiesen, dass "Grundselbstbeteiligung" sonst über ein
    als "eingefügt" gewertetes "d" doch matchte. Aus demselben Grund muss
    der Treffer an einer Wortgrenze beginnen (`(?<!\\w)` außerhalb der
    unscharfen Gruppe), statt mitten in einem längeren Wort."""
    anchor = _pattern_anchor_prefix(pattern)
    value_part = pattern[len(anchor):]
    if not anchor or anchor == pattern or ".*?" in anchor:
        return None
    if any(look in anchor for look in ("(?<!", "(?<=", "(?!", "(?=")):
        return None
    letters = sum(ch.isalpha() for ch in _REGEX_CLASS_ESCAPE.sub("", anchor))
    if letters < _FUZZY_MIN_LETTERS:
        return None
    max_errors = min(_FUZZY_MAX_ERRORS, letters // _FUZZY_LETTERS_PER_ERROR)
    # `\s*` zwischen den Label-Zeichen (siehe `mlp_template._escape_label`)
    # darf unscharf keinen Zeilenumbruch überbrücken: zusammen mit einem als
    # "gelöscht" gewerteten letzten Zeichen würde das Label sonst erst auf der
    # nächsten Zeile "enden" und deren Text als Wert einfangen. Über zwei
    # Zeilen umbrochene Labels bleiben damit der exakten Suche vorbehalten.
    anchor = anchor.replace(r"\s*", r"[ ]*")
    # `(?!(?<=\w)\w)` = Anker endet nicht mitten in einem Wort: sonst
    # "löscht" die Fehlertoleranz das Label-Ende und die Werte-Gruppe fängt
    # den Rest des Labels als Wert ein ("Versicherungsort/ Risikoo" + "rt").
    # `:[^\n\t]` = ein Fehler darf nie einen Zeilenumbruch/eine Zellgrenze
    # einbeziehen - sonst überbrückt die Toleranz genau die Zeilengrenze, die
    # `mlp_template._SAME_LINE_SEP` bewusst nicht überschreitet (leeres Feld
    # würde den Text der nächsten Zeile als Wert einfangen).
    return (
        rf"(?<!\w)(?:{_fold_umlauts(anchor)}){{e<={max_errors}:[^\n\t]}}(?!(?<=\w)\w)"
        + _fold_umlauts(value_part)
    )


class MockOCRModel(BaseOCRModel):
    def page_count(self, file_path: str) -> int:
        if not file_path.lower().endswith(".pdf"):
            return 1
        with pdfplumber.open(file_path) as pdf:
            return len(pdf.pages)

    def predict(
        self, file_path: str, fields: list[FieldSpec], template_key: str | None = None
    ) -> list[FieldPrediction]:
        # template_key wird hier nicht gebraucht: `fields` ist bereits auf den
        # Feldkatalog des jeweiligen Vertragstyp-Templates zugeschnitten (nur
        # DonutOCRModel nutzt template_key zusätzlich für einen eigenen
        # Decoder-Prompt pro Vertragstyp, siehe donut_model.py).
        max_pages = RELEVANT_PAGE_COUNT if template_key == "mlp_bauantrag" else None
        pages = self._extract_pages(file_path, max_pages=max_pages)
        return self._predict_from_pages(fields, pages)

    def extract_text(self, file_path: str) -> str:
        return self._pages_to_text(self._extract_pages(file_path))

    def _predict_from_pages(self, fields: list[FieldSpec], pages: list[PageData]) -> list[FieldPrediction]:
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
                    ambiguous=match.ambiguous,
                )
            )
        return predictions

    @staticmethod
    def _pages_to_text(pages: list[PageData]) -> str:
        return "\n\n".join(
            f"--- Seite {page_number} ---\n"
            + "\n".join(" ".join(word.text for word in line) for line in page.lines)
            for page_number, page in enumerate(pages, start=1)
        )

    def preview_match(self, file_path: str, patterns: list[str]) -> FieldMatch:
        """Testet Kandidaten-Muster gegen eine (i.d.R. temporäre) Beispieldatei,
        ohne dass dafür ein Template/Feld existieren muss - schließt den beim
        Anlegen neuer Vertragstypen bisher fehlenden Vorschau-Loop (siehe
        POST /api/templates/preview-pattern). Nutzt exakt dieselbe
        Extraktions-/Matching-Logik wie `predict()`, keine Duplikation."""
        pages = self._extract_pages(file_path)
        return self._match_field_in_pages(patterns, pages)

    def extract_pages(self, file_path: str) -> list[PageData]:
        """Öffentlicher Zugriff auf die Text-/Wort-Extraktion, damit sie für
        mehrere Templates wiederverwendet werden kann (siehe `score_fields`
        und POST /api/templates/suggest) statt pro Template neu zu laufen -
        die Extraktion (insbesondere der OCR-Fallback) ist der teure Teil."""
        return self._extract_pages(file_path)

    def score_fields(self, fields: list[FieldSpec], pages: list[PageData]) -> float:
        """Anteil der übergebenen Felder (die ein Muster haben), deren Muster
        in den bereits extrahierten Seiten einen Treffer liefert - die
        Heuristik hinter dem Vertragstyp-Vorschlag (POST
        /api/templates/suggest): kein trainierter Klassifikator, sondern
        dieselbe Matching-Maschinerie, die auch die eigentliche Feld-
        Erkennung nutzt."""
        fields_with_patterns = [f for f in fields if f.patterns]
        if not fields_with_patterns:
            return 0.0
        matched = sum(
            1
            for f in fields_with_patterns
            if self._match_field_in_pages(f.patterns, pages).match_status == "matched"
        )
        return matched / len(fields_with_patterns)

    # ------------------------------------------------------------------
    # Text-/Wort-Extraktion
    # ------------------------------------------------------------------

    def _extract_pages(self, file_path: str, max_pages: int | None = None) -> list[PageData]:
        """Extrahiert die ersten `max_pages` Seiten (bzw. alle) über den
        Cache: bereits extrahierte Seiten derselben Datei werden
        wiederverwendet, fehlende Folgeseiten nur noch ergänzt (z.B. erst
        die relevanten Seiten eines MLP-Antrags für die Felder, danach der
        Rest für den OCR-Volltext)."""
        # Die Einstellungen gehören mit in den Schlüssel: wird zur Laufzeit
        # z.B. die OCR-Engine gewechselt, darf kein Ergebnis der alten Engine
        # wiederverwendet werden.
        key = (_file_digest(file_path), settings.mock_ocr_always, settings.mock_ocr_engine)
        with _extraction_lock:
            cached = _page_cache.get(key)
            if cached is not None:
                # LRU: zuletzt benutzte Einträge wandern ans Ende und werden
                # zuletzt verdrängt.
                _page_cache.move_to_end(key)
                # Treffer, wenn der Cache das ganze Dokument kennt oder
                # zumindest so viele Seiten wie angefragt. `[:None]` liefert
                # bei `max_pages=None` die vollständige Liste.
                if cached.complete or (max_pages is not None and len(cached.pages) >= max_pages):
                    return cached.pages[:max_pages]

            # Kein oder nur teilweiser Treffer: nur die noch fehlenden Seiten
            # extrahieren, ab der ersten noch unbekannten Seite.
            known = cached.pages if cached is not None else []
            new_pages = self._extract_pages_uncached(
                file_path,
                first_page=len(known),
                max_pages=None if max_pages is None else max_pages - len(known),
            )
            pages = known + new_pages
            # Vollständig ist das Dokument, wenn alle Seiten angefragt wurden
            # oder weniger Seiten zurückkamen als angefragt (= Dokumentende
            # erreicht). Kamen genau so viele wie angefragt, ist offen, ob noch
            # Seiten folgen - eine spätere Volltext-Anfrage prüft das dann
            # (und bekommt im Zweifel nur eine leere Ergänzung).
            complete = max_pages is None or len(new_pages) < max_pages - len(known)
            _page_cache[key] = _CachedPages(pages=pages, complete=complete)
            _page_cache.move_to_end(key)
            # Ältesten (am längsten unbenutzten) Eintrag verdrängen, damit
            # der Cache nicht unbegrenzt Speicher belegt.
            while len(_page_cache) > _PAGE_CACHE_SIZE:
                _page_cache.popitem(last=False)
            return pages

    def _extract_pages_uncached(
        self, file_path: str, first_page: int = 0, max_pages: int | None = None
    ) -> list[PageData]:
        """Eigentliche Extraktion ohne Cache: höchstens `max_pages` Seiten ab
        Seite `first_page` (0-basiert). Wählt je nach `mock_ocr_always`
        zwischen OCR und eingebetteter PDF-Textebene."""
        is_pdf = file_path.lower().endswith(".pdf")

        if settings.mock_ocr_always:
            return self._extract_pages_via_ocr(file_path, is_pdf, first_page=first_page, max_pages=max_pages)

        pdf_pages = (
            self._extract_pages_via_pdfplumber(file_path, first_page=first_page, max_pages=max_pages)
            if is_pdf
            else []
        )
        total_chars = sum(len(w.text) for page in pdf_pages for line in page.lines for w in line)

        if total_chars >= MIN_TRUSTED_TEXT_LENGTH:
            return pdf_pages

        # Kein/kaum PDF-Text gefunden -> vermutlich ein Scan. OCR liefert
        # Wortpositionen, die ebenfalls auf 0..1 normiert werden.
        ocr_pages = self._extract_pages_via_ocr(file_path, is_pdf, first_page=first_page, max_pages=max_pages)
        if any(page.lines for page in ocr_pages):
            return ocr_pages
        return pdf_pages

    @staticmethod
    def _page_slice(first_page: int, max_pages: int | None) -> slice:
        """Seitenbereich `first_page` bis `first_page + max_pages` (exklusiv)
        als slice; `max_pages=None` bedeutet "bis zum Dokumentende"."""
        return slice(first_page, None if max_pages is None else first_page + max_pages)

    def _extract_pages_via_pdfplumber(
        self, file_path: str, first_page: int = 0, max_pages: int | None = None
    ) -> list[PageData]:
        pages: list[PageData] = []
        with pdfplumber.open(file_path) as pdf:
            source_pages = pdf.pages[self._page_slice(first_page, max_pages)]
            for page in source_pages:
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

    def _extract_pages_via_ocr(
        self, file_path: str, is_pdf: bool, first_page: int = 0, max_pages: int | None = None
    ) -> list[PageData]:
        try:
            images = self._load_images(file_path, is_pdf, first_page=first_page, max_pages=max_pages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Konnte Dokument nicht als Bild laden für OCR (%s): %s", file_path, exc)
            return []
        # Keine Seiten im angefragten Bereich (z.B. Folgeseiten eines
        # einseitigen Dokuments) - die OCR-Engines nicht mit einer leeren
        # Liste aufrufen, docTR quittiert das mit einem Fehler.
        if not images:
            return []

        engine = (settings.mock_ocr_engine or "doctr").lower()
        if engine == "tesseract":
            pages = self._ocr_pages_with_tesseract(images)
        elif engine == "easyocr":
            pages = self._ocr_pages_with_easyocr(images)
        else:
            pages = self._ocr_pages_with_doctr(images)
        return [
            PageData(lines=self._merge_same_row_lines(page.lines))
            for page in pages
        ]

    @staticmethod
    def _merge_same_row_lines(lines: list[list[Word]]) -> list[list[Word]]:
        """Fügt OCR-Zeilen aus getrennten Tabellenzellen zusammen, wenn ihre
        Wortboxen auf derselben horizontalen Grundlinie liegen."""
        measured_lines: list[tuple[float, float, float, list[Word]]] = []
        for line in lines:
            if not line:
                continue
            top = min(word.top for word in line)
            bottom = max(word.bottom for word in line)
            measured_lines.append(((top + bottom) / 2, top, bottom, line))

        measured_lines.sort(key=lambda item: (item[0], min(word.x0 for word in item[3])))
        rows: list[list[tuple[float, float, float, list[Word]]]] = []
        for measured_line in measured_lines:
            center, top, bottom, _line = measured_line
            if rows:
                row = rows[-1]
                row_center = sum(item[0] for item in row) / len(row)
                row_height = max(item[2] - item[1] for item in row)
                line_height = bottom - top
                if abs(center - row_center) <= max(row_height, line_height) * 0.45:
                    row.append(measured_line)
                    continue
            rows.append([measured_line])

        merged_rows: list[list[Word]] = []
        for row in rows:
            merged_words = [word for _center, _top, _bottom, line in row for word in line]
            merged_rows.append(sorted(merged_words, key=lambda word: word.x0))
        return merged_rows

    def _load_images(
        self, file_path: str, is_pdf: bool, first_page: int = 0, max_pages: int | None = None
    ) -> list:
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
                pages = list(doc)[self._page_slice(first_page, max_pages)]
                images = [
                    Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    for pix in (page.get_pixmap(matrix=matrix) for page in pages)
                ]
        else:
            # Ein Bild-Upload hat genau eine Seite - ab Seite 2 gibt es nichts.
            images = [Image.open(file_path).convert("RGB")] if first_page == 0 else []
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
                        # Zellgrenze als "\t" erhalten statt sie zu einem
                        # Leerzeichen zu glätten, damit Wertmuster wie
                        # `mlp_template.TEXT` an der Zelle enden statt in die
                        # Nachbarzelle weiterzulesen (siehe CELL_GAP_THRESHOLD).
                        gap = word.x0 - line[word_index - 1].x1
                        joined_parts.append("\t" if gap >= CELL_GAP_THRESHOLD else " ")
                        cursor += 1
                    start = cursor
                    joined_parts.append(word.text)
                    cursor += len(word.text)
                    spans.append((start, cursor, word))
            joined_text = "".join(joined_parts)
            page_texts.append((joined_text, joined_text.lower(), spans))

        # Stufe 1: volles Muster (Anker + Wert) suchen. Sammelt ALLE Treffer
        # über alle Muster x Seiten (bei den üblichen wenigen Mustern/Seiten
        # pro Dokument vernachlässigbar teuer), statt beim ersten Treffer
        # zurückzukehren - so lässt sich erkennen, wenn verschiedene Muster
        # auf unterschiedliche Werte kommen (siehe `ambiguous` in FieldMatch).
        candidates = self._collect_candidates(patterns, page_texts, fuzzy=False)
        if not candidates:
            # Stufe 1b: Anker unscharf (OCR-Lesefehler im Label, siehe
            # `_fuzzy_anchor_pattern`) - nur, wenn exakt gar nichts gefunden
            # wurde, damit ein sauber gelesenes Label immer Vorrang hat.
            candidates = self._collect_candidates(patterns, page_texts, fuzzy=True)

        if candidates:
            # Frühere Muster gelten als spezifischer/vertrauenswürdiger (die
            # Reihenfolge ist eine bewusste Admin-Entscheidung beim Anlegen
            # des Feldes) - das ist der primäre Sortierschlüssel, nicht die
            # Seitenzahl.
            best = min(candidates, key=lambda c: (c.pattern_index, c.page_number))
            distinct_values = {c.value.strip().lower() for c in candidates}
            ambiguous = len(distinct_values) > 1
            return FieldMatch(
                value=best.value,
                confidence=best.confidence,
                page=best.page_number,
                bbox=best.bbox,
                match_status="matched",
                ambiguous=ambiguous,
            )

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
                    found = re.search(anchor, joined_lower, flags=re.IGNORECASE | re.DOTALL) or re.search(
                        _fold_umlauts(anchor), _fold_umlauts(joined_lower), flags=re.IGNORECASE | re.DOTALL
                    )
                    if found:
                        return FieldMatch(value=None, confidence=0.0, page=1, bbox=None, match_status="data_not_found")
                except re.error:
                    # Frei getipptes Admin-Regex, dessen Präfix allein nicht
                    # kompilierbar ist – für dieses Pattern keine Aussage
                    # möglich, konservativ als "nicht gefunden" werten.
                    continue

        return FieldMatch(value=None, confidence=0.0, page=1, bbox=None, match_status="field_not_found")

    @staticmethod
    def _collect_candidates(
        patterns: list[str],
        page_texts: list[tuple[str, str, list[tuple[int, int, Word]]]],
        fuzzy: bool,
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for pattern_index, pattern in enumerate(patterns):
            fuzzy_pattern = _fuzzy_anchor_pattern(pattern) if fuzzy else None
            if fuzzy and fuzzy_pattern is None:
                continue
            for page_number, (joined_text, joined_lower, spans) in enumerate(page_texts, start=1):
                if not joined_lower:
                    continue

                if fuzzy_pattern is not None:
                    try:
                        # Umlaut-gefaltet wie der Fallback unten, damit ein
                        # fehlender Umlaut-Punkt nicht schon das Fehlerbudget
                        # verbraucht. BESTMATCH: sonst nimmt `regex` den
                        # ERSTEN Treffer innerhalb des Budgets, auch wenn
                        # weiter hinten das Label fehlerfrei(er) steht.
                        match = regex.search(
                            fuzzy_pattern,
                            _fold_umlauts(joined_lower),
                            flags=regex.IGNORECASE | regex.DOTALL | regex.BESTMATCH,
                            timeout=_FUZZY_TIMEOUT_SECONDS,
                        )
                    except (regex.error, TimeoutError):
                        continue
                    if not match:
                        continue
                    candidate = _candidate_from_match(match, pattern_index, page_number, joined_text, spans, pattern)
                    if candidate is not None:
                        candidate.confidence = round(candidate.confidence * _FUZZY_CONFIDENCE_DISCOUNT, 4)
                        candidates.append(candidate)
                    continue

                try:
                    # DOTALL zusätzlich zu IGNORECASE: manche Muster (siehe
                    # `_scoped_label` in mlp_template.py) verlangen bewusst
                    # einen Kontext-Anker VOR dem eigentlichen Label (z.B.
                    # "Gibt es einen abweichenden Kontoinhaber? ... Name"), um
                    # ein generisches Label wie "Name" nicht versehentlich auf
                    # den gleichnamigen Wert eines anderen Formularabschnitts
                    # matchen zu lassen. Ohne DOTALL würde das dazwischen
                    # liegende `.*?` an jedem Zeilenumbruch ("\n" zwischen
                    # Formularzeilen, siehe oben) abbrechen. Alle bestehenden
                    # Wert-Muster grenzen sich ohnehin explizit über `[^\n...]`
                    # statt über das implizite "kein Zeilenumbruch"-Verhalten
                    # von `.` ab, DOTALL ändert also nichts an deren Reichweite.
                    match = re.search(pattern, joined_lower, flags=re.IGNORECASE | re.DOTALL)
                    if not match:
                        # Fallback: OCR lässt Umlaut-Punkte bei manchen
                        # Scans/Schriftarten weg (siehe _fold_umlauts) - erst
                        # nach der direkten Suche versuchen, damit ein
                        # korrekt erkannter Umlaut Vorrang hat. Die Faltung
                        # ist 1:1 zeichentreu, `match.span(1)` bleibt also
                        # gegenüber `spans`/`joined_text` (unverändert, ohne
                        # Faltung) gültig.
                        match = re.search(
                            _fold_umlauts(pattern),
                            _fold_umlauts(joined_lower),
                            flags=re.IGNORECASE | re.DOTALL,
                        )
                except re.error:
                    # Frei getipptes Admin-Regex kann syntaktisch kaputt sein
                    # (Speichern validiert das inzwischen, siehe
                    # app.schemas.template, aber ältere/direkt in der DB
                    # angelegte Muster könnten das umgehen) - dieses Muster
                    # einfach überspringen statt den ganzen Upload mit einem
                    # unbehandelten re.error abstürzen zu lassen.
                    continue
                if not match:
                    continue

                candidate = _candidate_from_match(match, pattern_index, page_number, joined_text, spans, pattern)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates
