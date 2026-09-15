"""Unit-Tests direkt gegen MockOCRModel._match_field_in_pages, ohne über die
HTTP-API zu gehen - schneller und präziser für die Matching-/Scoring-Logik
selbst (Kandidaten-Sammlung, Mehrdeutigkeits-Erkennung, re.error-Robustheit)."""
from app.ocr.mock_model import MockOCRModel, PageData, Word
from app.ocr.mlp_template import (
    ANTRAGSTELLER_ANCHOR,
    KONTOINHABER_ANCHOR,
    MONEY,
    TEXT,
    YES_NO,
    _escape_label,
    _klausel_selbstbeteiligung,
    _klausel_status,
    _label_nearby,
    _label_until,
    _SAME_LINE_SEP,
    _scoped_label,
)


def _word(text: str, x0: float, top: float) -> Word:
    return Word(text=text, x0=x0, x1=x0 + 0.05, top=top, bottom=top + 0.02)


def _page(words: list[Word]) -> PageData:
    return PageData(lines=[words])


def _page_from_lines(lines: list[str]) -> PageData:
    """Baut eine PageData aus mehreren Textzeilen (je ein Wort pro
    Leerzeichen-getrenntem Token) - fürs Nachbauen längerer, realer
    Dokumentausschnitte in Tests deutlich lesbarer als einzelne `_word(...)`-
    Aufrufe."""
    plines: list[list[Word]] = []
    for line in lines:
        x = 0.05
        words: list[Word] = []
        for tok in line.split(" "):
            if not tok:
                continue
            words.append(_word(tok, x, 0.1))
            x += 0.03
        plines.append(words)
    return PageData(lines=plines)


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


def test_multiline_label_still_matches():
    """Regression-Guard für MLP-Checkbox-Fragen: lange Labels (z.B.
    "Absicherung der groben Fahrlässigkeit bis 20.000 EUR?") brechen im
    echten Formular oft über eine Zeile um. Vorher zerbrach das Matching
    daran, weil der Anker literale Leerzeichen statt `\\s+` nutzte (siehe
    `_escape_label` in mlp_template.py)."""
    model = MockOCRModel()
    line1 = [_word("Absicherung", 0.1, 0.10), _word("der", 0.22, 0.10), _word("groben", 0.27, 0.10)]
    line2 = [_word("Fahrlässigkeit", 0.1, 0.12), _word("bis", 0.2, 0.12), _word("20.000", 0.25, 0.12), _word("EUR?", 0.35, 0.12), _word("Ja", 0.42, 0.12)]
    page = PageData(lines=[line1, line2])

    pattern = rf"{_escape_label('Absicherung der groben Fahrlässigkeit bis 20.000 EUR?')}\s*:?\s*({YES_NO})"
    match = model._match_field_in_pages([pattern], [page])

    assert match.match_status == "matched"
    assert match.value == "Ja"


def test_question_mark_extracted_as_separate_word_still_matches():
    """Regression-Guard anhand eines echten MLP-Bauantrag-Transkripts: das
    abschließende "?" von Checkbox-Fragen wird dort von der Text-Extraktion
    als EIGENES Wort-Token geliefert ("... gewünscht" + "?" statt
    "gewünscht?"), obwohl im Formular kein sichtbarer Abstand davor steht.
    Beim Zusammenfügen der Zeile entsteht daraus ein Leerzeichen vor dem "?",
    das ein Label mit nur an Wortgrenzen toleriertem Whitespace (frühere
    Version von `_escape_label`) verfehlt hätte."""
    model = MockOCRModel()
    page = _page(
        [
            _word("Absicherung", 0.1, 0.1), _word("Bauleistung", 0.2, 0.1),
            _word("gewünscht", 0.3, 0.1), _word("?", 0.4, 0.1), _word("Ja", 0.42, 0.1),
        ]
    )
    pattern = rf"{_escape_label('Absicherung Bauleistung gewünscht?')}\s*:?\s*({YES_NO})"

    match = model._match_field_in_pages([pattern], [page])

    assert match.match_status == "matched"
    assert match.value == "Ja"


def test_kontoinhaber_section_does_not_pick_up_antragsteller_value():
    """Regression-Guard für die Label-Kollision zwischen Antragsteller- und
    Kontoinhaber-Abschnitt: beide nutzen im MLP-Formular die generische
    Beschriftung "Name". Ohne Sektions-Scoping (siehe `_scoped_label` in
    mlp_template.py) hätte das Kontoinhaber-Feld fälschlich den Namen des
    Antragstellers übernommen, weil beide Muster sonst identisch aussehen
    und `_match_field_in_pages` ohne Kontext einfach den frühesten Treffer
    nimmt."""
    model = MockOCRModel()
    antragsteller_page = _page([_word("Name:", 0.1, 0.1), _word("Max", 0.2, 0.1), _word("Mustermann", 0.3, 0.1)])
    kontoinhaber_page = PageData(
        lines=[
            [
                _word("Gibt", 0.1, 0.05), _word("es", 0.15, 0.05), _word("einen", 0.2, 0.05),
                _word("abweichenden", 0.25, 0.05), _word("Kontoinhaber?", 0.35, 0.05), _word("Ja", 0.45, 0.05),
            ],
            [_word("Name:", 0.1, 0.1), _word("Erika", 0.2, 0.1), _word("Musterfrau", 0.3, 0.1)],
        ]
    )
    pages = [antragsteller_page, kontoinhaber_page]

    scoped_pattern = _scoped_label(KONTOINHABER_ANCHOR, "Name")[0]
    match = model._match_field_in_pages([scoped_pattern], pages)

    assert match.match_status == "matched"
    assert match.value == "Erika Musterfrau"


# Ausschnitt aus einem echten, erkannten MLP-Bauantrag-Transkript (Leistungs-
# bausteine/Selbstbeteiligungen-Block) - Grundlage für die folgenden Tests.
_LEISTUNGSBAUSTEINE_TRANSKRIPT = [
    "- Mitversicherung von Altbauten gegen Sachschäden infolge eines Schadens an der Neubauleistung Nein",
    "sowie infolge Leitungswasser, Sturm/ Hagel (Klausel T590080k)",
    "- Altbauten gegen Sachschäden gem. Klausel T590081k 10% mind. 2.500 EUR",
    "- Mitversicherung von aufwendiger Ausstattung/ Bestandteile von unverhältnismäßig hohem Kunstwert 10% mind. 500 EUR",
    "gem. Klausel T512807u",
]


def test_klausel_status_handles_value_before_klausel_due_to_line_wrap():
    """Regression-Guard anhand eines echten MLP-Transkripts: bricht die
    Beschreibung eines Leistungsbausteins über eine Zeile um (tabellarisches
    PDF), hängt die Text-Extraktion den Ja/Nein-Status ans Ende der ersten
    Zeile - VOR den Klausel-Verweis, der erst auf Zeile 2 folgt (siehe
    `_klausel_status` in mlp_template.py)."""
    model = MockOCRModel()
    page = _page_from_lines(_LEISTUNGSBAUSTEINE_TRANSKRIPT)

    match = model._match_field_in_pages(_klausel_status("T590080k"), [page])

    assert match.match_status == "matched"
    assert match.value == "Nein"


def test_klausel_selbstbeteiligung_does_not_grab_value_from_earlier_klausel():
    """Regression-Guard: eine frühere Version von `_klausel_selbstbeteiligung`
    erlaubte bis zu 200 Zeichen zwischen Wert und Klausel-Code für den
    umgebrochenen Fall - das reichte über eine komplette andere
    Aufzählungszeile hinweg und lieferte fälschlich "10% mind. 2.500 EUR"
    (gehört zu Klausel T590081k) statt der tatsächlich zu T512807u
    gehörenden "10% mind. 500 EUR". Das enger gefasste Zeitfenster
    (`_KLAUSEL_PROXIMITY_WINDOW`) muss den richtigen, nahegelegenen Wert
    liefern."""
    model = MockOCRModel()
    page = _page_from_lines(_LEISTUNGSBAUSTEINE_TRANSKRIPT)

    match = model._match_field_in_pages(_klausel_selbstbeteiligung("T512807u"), [page])

    assert match.match_status == "matched"
    assert match.value == "10% mind. 500 EUR"


def test_blank_field_does_not_pick_up_next_labels_text():
    """Regression-Guard anhand eines echten MLP-Dokuments: ein im Formular
    LEER gelassenes Feld (Label allein auf seiner Zeile, kein Wert
    dahinter) matchte vor `_SAME_LINE_SEP` fälschlich über den
    Zeilenumbruch hinweg den TEXT DES NÄCHSTEN FELD-LABELS als eigenen
    Wert - z.B. übernahm das leere Kontoinhaber-"Name"-Feld den Text "oder
    Firmenname" (Label des nächsten Feldes). `\\s*` erlaubte das, weil es
    auch "\\n" matcht; `_SAME_LINE_SEP` beschränkt den Trenner auf
    Whitespace INNERHALB der Zeile."""
    model = MockOCRModel()
    page = _page_from_lines(
        [
            "Name",
            "oder Firmenname",
            "Geburtsdatum",
        ]
    )
    pattern = rf"{_escape_label('Name')}\s*:?\s*([^\n.]{{2,120}})"
    fixed_pattern = rf"{_escape_label('Name')}{_SAME_LINE_SEP}([^\n.]{{2,120}})"

    old_match = model._match_field_in_pages([pattern], [page])
    fixed_match = model._match_field_in_pages([fixed_pattern], [page])

    assert old_match.match_status == "matched"
    assert old_match.value == "oder Firmenname"  # dokumentiert den alten Bug
    assert fixed_match.match_status == "data_not_found"


def test_scoped_label_not_followed_by_excludes_sibling_field_collision():
    """Regression-Guard anhand eines echten MLP-Dokuments: das leere
    Kontoinhaber-"Name"-Feld matchte (nach dem `_SAME_LINE_SEP`-Fix) immer
    noch falsch - diesmal, weil es über den bloß leeren ersten Treffer
    hinweg zum späteren, inhaltlich ANDEREN Feld "Name des
    Kreditinstituts" weitersprang (das echten Text danach hat). Der
    `not_followed_by`-Lookahead muss diese konkrete Kollision ausschließen,
    ohne den Suchradius für andere gescopte Felder einzuschränken."""
    model = MockOCRModel()
    page = _page_from_lines(
        [
            "Gibt es einen abweichenden Kontoinhaber ? nein",
            "Name",
            "oder Firmenname",
            "Name des Kreditinstituts Deutsche Kreditbank Berlin",
        ]
    )

    pattern_without_exclude = _scoped_label(KONTOINHABER_ANCHOR, "Name")[0]
    pattern_with_exclude = _scoped_label(KONTOINHABER_ANCHOR, "Name", not_followed_by="des Kreditinstituts")[0]

    match_without = model._match_field_in_pages([pattern_without_exclude], [page])
    match_with = model._match_field_in_pages([pattern_with_exclude], [page])

    assert match_without.match_status == "matched"
    assert match_without.value == "des Kreditinstituts Deutsche Kreditbank Berlin"  # dokumentiert den alten Bug
    assert match_with.match_status == "data_not_found"


def test_label_nearby_prefers_closest_value_over_greedy_backtrack():
    """Regression-Guard anhand eines echten MLP-Dokuments: ein GIERIGES
    `.{0,N}` zwischen Anker und Wert konsumiert erst maximal viele Zeichen
    und backtracked dann nur MINIMAL, um doch noch einen Wert unterzubringen
    - dabei griff es nachweislich nur "0 EUR" ab (das Ende von "59,00 EUR",
    weil ein einzelnes "0" direkt vor "EUR" bereits als minimaler
    `[\\d.]+`-Treffer reicht) statt des tatsächlich gemeinten, näher am
    Anker liegenden Betrags. `_label_nearby` muss nicht-gierig sein."""
    model = MockOCRModel()
    page = _page_from_lines(
        [
            "Nettobeitrag Bauherrenhaftpflicht (unter Berücksichtigung der 59,00 EUR",
            "Mindestprämie)",
            "Nettobeitrag (unter Berücksichtigung der Mindestprämie) 224,00 EUR",
        ]
    )

    pattern = _label_nearby("Nettobeitrag Bauherrenhaftpflicht", MONEY)
    match = model._match_field_in_pages([pattern], [page])

    assert match.match_status == "matched"
    assert match.value == "59,00 EUR"


def test_text_allows_abbreviation_period_before_digit():
    """Regression-Guard anhand eines echten MLP-Dokuments: die alte
    `TEXT`-Definition (`[^\\n.]{2,120}`) schloss jeden Punkt als Werte-Ende
    aus - "Straße u. Haus-Nr. Herner Str. 212" wurde dadurch zu "Herner
    Str" abgeschnitten, die Hausnummer ging komplett verloren. Ein Punkt
    direkt vor einer Ziffer (typisch für Abkürzungen wie "Str."/"Nr.") darf
    den Wert nicht mehr abschneiden."""
    model = MockOCRModel()
    page = _page_from_lines(["Straße u. Haus-Nr. Herner Str. 212"])

    pattern = rf"{_escape_label('Straße u. Haus-Nr.')}{_SAME_LINE_SEP}({TEXT})"
    match = model._match_field_in_pages([pattern], [page])

    assert match.match_status == "matched"
    assert match.value == "Herner Str. 212"


def test_scoped_antragsteller_field_ignores_earlier_berater_name():
    """Regression-Guard anhand eines echten MLP-Dokuments: das "name"-Feld
    matchte fälschlich "Martin Blaton" (den MLP-BERATER, Zeile "Berater
    Name Martin Blaton" weiter oben im Dokument) statt "Benjamin Hein" (den
    tatsächlichen Antragsteller/Versicherungsnehmer) - weil "Name" als
    Anker ungescopt einfach den frühesten Treffer im Dokument nimmt. Der
    Scope auf die Abschnittsüberschrift "Versicherungsnehmer /
    Antragsteller" muss den früheren, falschen Treffer ausschließen."""
    model = MockOCRModel()
    page = _page_from_lines(
        [
            "Berater Name Martin Blaton",
            "Versicherungsnehmer / Antragsteller",
            "Name Benjamin Hein",
        ]
    )

    pattern = _scoped_label(ANTRAGSTELLER_ANCHOR, "Name", TEXT)[0]
    match = model._match_field_in_pages([pattern], [page])

    assert match.match_status == "matched"
    assert match.value == "Benjamin Hein"


def test_scoped_kontoinhaber_iban_ignores_earlier_company_iban():
    """Regression-Guard anhand eines echten MLP-Dokuments: das ungescopte
    "IBAN"-Feld matchte die MLP-eigene Bankverbindung aus dem Seitenfuß
    ("Bankverbindung ... IBAN: DE19 6723 ..."), die auf einer früheren
    Seite als der eigentliche Kontoinhaber-Abschnitt steht, statt der
    tatsächlichen Kontoinhaber-IBAN."""
    model = MockOCRModel()
    footer_page = _page_from_lines(["Bankverbindung MLP Banking AG IBAN: DE19 6723 0000 0009 0000 25"])
    kontoinhaber_page = _page_from_lines(
        [
            "Gibt es einen abweichenden Kontoinhaber ? nein",
            "IBAN DE77 1203 0000 1063 0763 58",
        ]
    )

    pattern = _scoped_label(KONTOINHABER_ANCHOR, "IBAN", r"[A-Z]{2}\s?[A-Z0-9 ]{12,30}")[0]
    match = model._match_field_in_pages([pattern], [footer_page, kontoinhaber_page])

    assert match.match_status == "matched"
    assert match.value == "DE77 1203 0000 1063 0763 58"


def test_label_until_captures_multiline_value_up_to_next_field():
    """Regression-Guard: "Beschreibung" ist im echten MLP-Dokument kein
    einzeiliges Feld, sondern geht über viele Zeilen/Absätze (Maßnahmen-
    Tabelle, Anmerkungen, Unterschriftenblock), bevor das nächste
    Formularfeld ("Liegt das Bauvorhaben in einem Bergbaugebiet?")
    beginnt. `_label(..., r"[^\\n]{2,500}")` hätte nach der ersten Zeile
    abgebrochen."""
    model = MockOCRModel()
    page = _page_from_lines(
        [
            "Beschreibung Sanierungsaufwände Verkehrsstr. 19",
            "Erste Zeile Inhalt",
            "Zweite Zeile Inhalt",
            "Liegt das Bauvorhaben in einem Bergbaugebiet ? Nein",
        ]
    )

    pattern = _label_until("Beschreibung", "Liegt das Bauvorhaben in einem Bergbaugebiet?")[0]
    match = model._match_field_in_pages([pattern], [page])

    assert match.match_status == "matched"
    assert match.value == "Sanierungsaufwände Verkehrsstr. 19\nErste Zeile Inhalt\nZweite Zeile Inhalt"


def test_label_until_reports_no_value_when_empty():
    """Regression-Guard: steht das nächste Feld direkt nach dem Label (kein
    Inhalt dazwischen), muss das als "kein Wert gefunden" erkannt werden -
    nicht als leerer, aber "matched" Treffer."""
    model = MockOCRModel()
    page = _page_from_lines(
        [
            "Beschreibung",
            "Liegt das Bauvorhaben in einem Bergbaugebiet ? Nein",
        ]
    )

    pattern = _label_until("Beschreibung", "Liegt das Bauvorhaben in einem Bergbaugebiet?")[0]
    match = model._match_field_in_pages([pattern], [page])

    assert match.match_status == "data_not_found"
    assert match.value is None
