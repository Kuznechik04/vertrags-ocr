"""Unit-Tests direkt gegen MockOCRModel._match_field_in_pages, ohne über die
HTTP-API zu gehen - schneller und präziser für die Matching-/Scoring-Logik
selbst (Kandidaten-Sammlung, Mehrdeutigkeits-Erkennung, re.error-Robustheit)."""
from app.ocr.mock_model import MockOCRModel, PageData, Word


def _word(text: str, x0: float, top: float) -> Word:
    return Word(text=text, x0=x0, x1=x0 + 0.05, top=top, bottom=top + 0.02)


def _page(words: list[Word]) -> PageData:
    return PageData(lines=[words])


def test_malformed_pattern_is_skipped_instead_of_crashing():
    """Regression-Guard für den zuvor unabgesicherten re.error in Stufe 1:
    ein syntaktisch kaputtes Muster darf das Matching für die übrigen Muster
    nicht mehr zum Absturz bringen."""
    model = MockOCRModel()
    page = _page([_word("vertragspartner", 0.1, 0.1), _word("musterfirma", 0.2, 0.1)])
    broken_pattern = r"vertragspartner\s*:?\s*(unbalanced["  # ungültiges Regex
    working_pattern = r"vertragspartner\s*:?\s*([^\n\.]{3,60})"

    match = model._match_field_in_pages([broken_pattern, working_pattern], [page])

    assert match.match_status == "matched"
    assert match.value == "musterfirma"


def test_earlier_configured_pattern_wins_over_later_page():
    """Musterreihenfolge (Admin-Entscheidung) ist der primäre Sortierschlüssel
    - nicht die Seitenzahl, auf der ein Treffer zufällig liegt."""
    model = MockOCRModel()
    page1 = _page([_word("b-anchor", 0.1, 0.1), _word("wert-b", 0.2, 0.1)])
    page2 = _page([_word("a-anchor", 0.1, 0.1), _word("wert-a", 0.2, 0.1)])

    pattern_a = r"a-anchor\s*:?\s*([^\n\.]{3,20})"  # nur auf Seite 2
    pattern_b = r"b-anchor\s*:?\s*([^\n\.]{3,20})"  # nur auf Seite 1

    match = model._match_field_in_pages([pattern_a, pattern_b], [page1, page2])

    assert match.value == "wert-a"
    assert match.page == 2
    assert match.ambiguous is True


def test_not_ambiguous_when_all_candidates_agree():
    model = MockOCRModel()
    page = _page([_word("iban", 0.1, 0.1), _word("de1234567890", 0.2, 0.1)])
    pattern_a = r"iban\s*:?\s*([^\n\.]{3,20})"
    pattern_b = r"iban\s*:?\s*([a-z0-9]{3,20})"

    match = model._match_field_in_pages([pattern_a, pattern_b], [page])

    assert match.match_status == "matched"
    assert match.ambiguous is False


def test_generic_freitext_pattern_gets_confidence_discount():
    model = MockOCRModel()
    page = _page([_word("mietobjekt", 0.1, 0.1), _word("musterstrasse", 0.2, 0.1)])
    freitext_pattern = r"mietobjekt\s*:?\s*([^\n\.]{3,80})"

    match = model._match_field_in_pages([freitext_pattern], [page])

    # Eingebettete PDF-Textebene würde ohne Abschlag 1.0 ergeben; der
    # generische Freitext-Abschlag muss das spürbar senken.
    assert match.match_status == "matched"
    assert match.confidence < 1.0


def test_umlaut_dropped_by_ocr_still_matches_anchor():
    """Regression-Guard: manche OCR-Engines lassen Umlaut-Punkte bei
    bestimmten Schriftarten/Scans weg (beobachtet z.B. bei "Kündigungsfrist"
    -> "Kundigungsfrist"). Ein Suchbegriff mit korrekt geschriebenem Umlaut
    darf dann nicht komplett leer ausgehen."""
    model = MockOCRModel()
    # ocr_confidence gesetzt, um zu simulieren, dass dieses Wort über den
    # OCR-Fallback erkannt wurde (nicht über die eingebettete PDF-Textebene).
    page = _page(
        [
            Word(text="kundigungsfrist", x0=0.1, x1=0.3, top=0.1, bottom=0.12, ocr_confidence=90.0),
            Word(text="3", x0=0.31, x1=0.33, top=0.1, bottom=0.12, ocr_confidence=90.0),
            Word(text="monate", x0=0.34, x1=0.4, top=0.1, bottom=0.12, ocr_confidence=90.0),
        ]
    )
    pattern = r"kündigungsfrist\s*:?\s*([^\n\.]{3,40})"

    match = model._match_field_in_pages([pattern], [page])

    assert match.match_status == "matched"
    assert match.value == "3 monate"
