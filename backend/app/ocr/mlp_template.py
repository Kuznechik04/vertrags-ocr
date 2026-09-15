"""Feldkatalog und Regex-Muster für MLP-Bauanträge.

Die Muster sind bewusst auf die Formularbeschriftungen ausgerichtet. Werte
werden anschließend weiterhin im Review-UI bestätigt; Regex ist hier eine
Vorselektion und keine fachliche Entscheidung.
"""
from __future__ import annotations

import re


RELEVANT_PAGE_COUNT = 8

DATE = r"\d{1,2}[./]\d{1,2}[./]\d{2,4}"
MONEY = r"[\d.]+(?:,\d{1,2})?\s*(?:EUR|€|Euro)?"
# \b (Wortgrenze) um die ganze Alternation, NICHT nur `[xX]` als bloßes
# Zeichen: an einem echten Dokument nachgewiesen, dass die `_label_nearby`-
# Umkreissuche (siehe `_robust` unten) sonst jedes "x" INNERHALB eines
# Wortes aufgreift - "Explosion" enthält ein "x" und lag zufällig nahe
# genug an einem Klausel-Code, wodurch ein Ja/Nein-Feld fälschlich den
# Wert "x" bekam. Bei einem direkt angrenzenden Label:Wert-Muster
# (`_SAME_LINE_SEP`) wäre das nie aufgefallen, weil dort ohnehin nur der
# Text direkt nach dem Label infrage kommt - erst bei einer offenen
# Umkreissuche über beliebigen Text wird die fehlende Wortgrenze zum
# echten Problem.
YES_NO = r"\b(?:ja|nein|yes|no|x)\b"
# Punkt im Wert nur dann durchlassen, wenn danach (ggf. nach Whitespace)
# eine Ziffer folgt - typisch für Abkürzungen wie "Str." oder "Nr." vor
# einer Hausnummer. WICHTIG: das Matching läuft gegen den BEREITS
# KLEINGESCHRIEBENEN Seitentext (siehe `joined_lower` in
# `mock_model._match_field_in_pages`) - eine Großbuchstaben-Heuristik für
# "Satzanfang" würde dort nie greifen, deshalb Ziffer statt Großbuchstabe
# als Signal. An einem echten Dokument nachgewiesen: "Straße u. Haus-Nr.
# Herner Str. 212" wurde mit einer reinen `[^\n.]`-Ausschlussklasse zu
# "Herner Str" abgeschnitten - die Hausnummer ging komplett verloren.
# Bekannter Rand-/Fehlerfall: "GmbH & Co. KG" (Punkt gefolgt von Buchstabe,
# nicht Ziffer) bricht weiterhin bei "Co" ab - das war aber auch vorher
# schon so (jeder Punkt brach sofort ab), also keine Verschlechterung.
TEXT = r"(?:[^\n.]|\.(?=\s*\d)){2,120}"
# MLP nutzt für Leistungsbausteine ("gewünscht"/"nicht gewünscht") ein
# anderes Vokabular als für die übrigen Ja/Nein-Fragen ("ja"/"nein") - siehe
# `_klausel_status` unten, an einem echten Dokument-Transkript verifiziert.
# "nicht gewünscht" muss vor "gewünscht" stehen, sonst würde die Alternation
# an der Position von "nicht" scheitern, bevor sie den vollen Ausdruck
# probiert - `re.search` sucht ohnehin den am weitesten links liegenden
# Treffer, das ist hier nur zur Klarheit so sortiert.
STATUS_WORD = r"\b(?:nicht\s+gewünscht|gewünscht|ja|nein|yes|no|x)\b"
# Selbstbeteiligungs-Angabe: entweder ein reiner Betrag ("10.000 EUR") oder
# ein Prozentsatz mit Mindestbetrag ("10% mind. 2.500 EUR") - beide Formen
# kommen im selben Formularabschnitt vor (siehe `_klausel_selbstbeteiligung`).
SELBSTBETEILIGUNG = r"(?:\d{1,3}\s*%\s*mind\.?\s*)?[\d.]+(?:,\d{1,2})?\s*(?:EUR|€|Euro)"
# Max. Zeichen-Distanz für den "Wert steht vor dem Klausel-Code"-Fall in
# `_klausel_status`/`_klausel_selbstbeteiligung` (Reihenfolge-Umkehr durch
# Zeilenumbruch, siehe dort). An einem echten Transkript gemessen: legitime
# Distanzen lagen bei 21 und 57 Zeichen; ein zu großzügiger Wert (200) hat
# nachweislich den Wert eines GANZ ANDEREN, weiter vorne stehenden
# Leistungsbausteins aufgegriffen (139 Zeichen entfernt) statt "kein
# Treffer" zu liefern - 80 deckt die beobachteten Fälle mit Puffer ab, ohne
# über eine komplette andere Aufzählungszeile hinwegzureichen.
_KLAUSEL_PROXIMITY_WINDOW = 80


def _escape_label(label: str) -> str:
    """Wie `re.escape`, aber mit `\\s*` ZWISCHEN JEDEM Zeichen statt fixer
    Leerzeichen an den ursprünglichen Wortgrenzen. Zwei reale Beispiele aus
    einem tatsächlich erkannten MLP-Bauantrag belegen, warum ein reines
    Ersetzen der Wortgrenzen (frühere Version dieser Funktion) nicht reicht:

    1. Lange Feldbeschriftungen (v.a. die Checkbox-Fragen unten) brechen im
       echten Formular häufig über eine Zeile um - im extrahierten Text wird
       so ein Umbruch zu "\\n" statt einem Leerzeichen (siehe Zeilentrennung
       in `mock_model._match_field_in_pages`).
    2. Satzzeichen wie "?" werden von pdfplumber/der OCR oft als eigenes
       Wort-Token extrahiert, selbst wenn im Originaldokument kein
       sichtbarer Abstand davor steht - "gewünscht?" im PDF wird beim
       Zusammenfügen der Zeile zu "gewünscht ?" (siehe Wort-für-Wort-
       Verkettung in `_group_words_into_lines`/den Extraktionspfaden). Ein
       Label, das nur an eigenen Wortgrenzen Leerzeichen toleriert, verfehlt
       genau solche Treffer komplett, weil "gewünscht?" als EIN Token ohne
       jegliches `\\s` dazwischen erwartet wurde.

    `\\s*` zwischen jedem Einzelzeichen deckt beide Fälle ab, ohne den
    Anker zu verwässern - die Zeichen müssen weiterhin exakt in dieser
    Reihenfolge vorkommen, nur mit optionalem Whitespace dazwischen."""
    return r"\s*".join(re.escape(ch) for ch in label if not ch.isspace())


# Trenner zwischen Label und Wert: bewusst NUR Whitespace INNERHALB der
# Zeile (kein `\n`), plus optionaler Doppelpunkt, optionaler EIN-zeiliger
# Klammer-Zusatz ("(unter Berücksichtigung der ...)") und optionaler
# Fußnoten-Stern ("*"). Label und Wert stehen im MLP-Formular praktisch
# immer auf DERSELBEN Zeile (label-wort(e) direkt gefolgt vom Wert im
# selben Tabellenzeilen-Fließtext).
#
# Warum kein `\s*` (das auch "\n" matcht): an einem echten Dokument
# nachgewiesen, dass ein im Formular LEER gelassenes Feld (Label allein auf
# seiner Zeile, kein Wert dahinter) sonst über den Zeilenumbruch hinweg
# fälschlich den TEXT DES NÄCHSTEN FELD-LABELS als eigenen Wert einfängt -
# z.B. matchte das leere Kontoinhaber-"Name"-Feld den Text "oder
# Firmenname" (Label des NÄCHSTEN Feldes) als seinen eigenen Wert. Das ist
# schlimmer als ein Fehltreffer, weil es als "matched" mit falschem Inhalt
# im Review landet statt korrekt als "kein Wert gefunden" aufzufallen.
#
# Die optionale Klammer-Zusatz-Gruppe deckt Fälle wie "Baugrubenumschließung
# (10.000 EUR beitragsfrei) 10.000 EUR" ab, wo der eigentliche Wert nach
# einem erklärenden Klammereinschub in Klammern folgt.
_SAME_LINE_SEP = r"[ \t]*:?[ \t]*(?:\([^)\n]*\)[ \t]*)?\*?[ \t]*"


def _label(label: str, value: str = TEXT, *aliases: str) -> list[str]:
    labels = (label,) + aliases
    return [rf"{_escape_label(item)}{_SAME_LINE_SEP}({value})" for item in labels]


def _checkbox(label: str, *aliases: str) -> list[str]:
    # Unterstützt sowohl "Ja/Nein"-Angaben als auch ein angekreuztes X.
    return _label(label, YES_NO, *aliases)


def _date(label: str, *aliases: str) -> list[str]:
    return _label(label, DATE, *aliases)


def _money(label: str, *aliases: str) -> list[str]:
    return _label(label, MONEY, *aliases)


def _robust(primary: list[str], label: str, value: str) -> list[str]:
    """Ergänzt ein bereits gebautes Musterset (`_checkbox`/`_label`/...) um
    ein zusätzliches, NACHRANGIGES `_label_nearby`-Fallback-Muster.

    Grund: An einem echten gescannten MLP-Dokument (OCR-Fallback, docTR)
    nachgewiesen, dass Label und Wert auf ZWEI GETRENNTEN erkannten Zeilen
    landen können, obwohl sie im Originalbild in derselben Zeile stehen
    (z.B. "Pfahl-, ... (10.000 EUR beitragsfrei)" und "10.000 EUR" als
    zwei separate docTR-Zeilen). `_SAME_LINE_SEP` (siehe dort) verhindert
    das primäre Muster hier absichtlich am Zeilenumbruch - `_label_nearby`
    überbrückt das als Fallback.

    Bewusst nur für ENGE Wertetypen (Ja/Nein, Geld, Prozent/Selbst-
    beteiligung, Status-Wort) genutzt, nie für `TEXT`/Freitext: bei
    Freitext bestünde wieder das Risiko, das `_SAME_LINE_SEP` ursprünglich
    beheben sollte (ein leeres Feld greift fälschlich den Text/das Label
    des nächsten Feldes). Ja/Nein-/Geld-/Prozent-Muster sind eng genug,
    dass diese Kollision praktisch ausgeschlossen ist."""
    return primary + [_label_nearby(label, value)]


def _checkbox_robust(label: str, *aliases: str) -> list[str]:
    return _robust(_checkbox(label, *aliases), label, YES_NO)


def _money_robust(label: str, *aliases: str) -> list[str]:
    return _robust(_money(label, *aliases), label, MONEY)


def _label_nearby(label: str, value: str) -> str:
    """Sucht `value` irgendwo innerhalb von `_KLAUSEL_PROXIMITY_WINDOW`
    Zeichen NACH `label` - nicht nur direkt angrenzend wie `_label`. Für
    Fälle, in denen der Wert durch einen Zeilenumbruch mitten in einem
    erklärenden, MEHRZEILIGEN Klammer-Einschub landet (anders als der
    einzeilige Fall, den `_SAME_LINE_SEP` bereits abdeckt) - an einem echten
    Dokument nachgewiesen: "Nettobeitrag Bauherrenhaftpflicht (unter
    Berücksichtigung der 59,00 EUR\\nMindestprämie)". Als zusätzliches,
    NACHRANGIGES Muster gedacht (nach den präziseren `_label`/`_money`-
    Mustern in der Musterliste), da es durch den größeren Suchradius
    unspezifischer ist.

    Das Fenster ist NICHT-gierig (`.{0,N}?`, nicht `.{0,N}`): ein gieriges
    Fenster konsumiert erst maximal viele Zeichen und backtracked dann nur
    minimal, um den Wert noch unterzubringen - dabei nachweislich (an
    diesem Dokument) nur das ENDE des richtigen Betrags "59,00 EUR"
    erwischt ("0 EUR" statt "59,00 EUR"), weil ein einzelnes "0" direkt vor
    "EUR" bereits als minimaler `[\\d.]+`-Treffer reicht. Nicht-gierig
    stoppt beim erstmöglichen (= nächstgelegenen) gültigen Wert."""
    return rf"{_escape_label(label)}.{{0,{_KLAUSEL_PROXIMITY_WINDOW}}}?({value})"


def _label_until(label: str, until_anchor: str, max_len: int = 3000) -> list[str]:
    """Erfasst mehrzeiligen Freitext ab `label` bis (ausschließlich) zum
    nächsten bekannten Feld-Label `until_anchor` - anders als `_label` mit
    `TEXT`/`r"[^\\n]{2,500}"`, das nach der ersten Zeile abbricht.

    Für Freitext-Felder wie "Beschreibung", deren Wert im echten Dokument
    über viele Zeilen/Absätze geht (z.B. eine Maßnahmen-Tabelle,
    Anmerkungen, ein Unterschriftenblock), bevor das nächste Formularfeld
    beginnt - an einem echten Dokument nachgewiesen: der Beschreibungstext
    war dort >1000 Zeichen lang. `[\\s\\S]` statt `.`, damit es unabhängig
    vom global gesetzten `re.DOTALL` (siehe `mock_model._match_field_in_pages`)
    explizit über Zeilenumbrüche hinweg matcht.

    Nicht-gierig (`{0,max_len}?`) und mit Lookahead auf `until_anchor` statt
    fixer Länge: verhindert sowohl "verschluckt zu viel" (würde sonst bis
    zum allerletzten Vorkommen von `until_anchor` im Dokument greifen) als
    auch "verschluckt zu wenig". Ein LEERER Wert (Label direkt gefolgt vom
    nächsten Feld, ohne Inhalt dazwischen) matcht ebenfalls - wird von
    `_match_field_in_pages` dann korrekt als "kein Wert" behandelt (leere
    Strings werden dort verworfen), nicht als Fehler."""
    return [rf"{_escape_label(label)}\s*:?\s*([\s\S]{{0,{max_len}}}?)(?=\s*{_escape_label(until_anchor)})"]


def _klausel_status(klausel_code: str) -> list[str]:
    """Ja/Nein-artiger Status ("gewünscht"/"nicht gewünscht"/"ja"/"nein") zu
    einer Klausel im Fließtext einer Aufzählung ("Leistungsbausteine") -
    KEIN klassisches Label:Wert-Paar. An einem echten MLP-Transkript
    verifiziert, zwei Fälle je nach Beschreibungslänge:

    1. Kurze Beschreibung (passt auf eine Zeile): Status kommt NACH dem
       Klausel-Verweis, z.B. "... (Klausel T512805u) nicht gewünscht".
    2. Lange Beschreibung (bricht im tabellarisch aufgebauten PDF über eine
       Zeile um): die Text-Extraktion hängt den Status ans Ende der ERSTEN
       Zeile, der Klausel-Verweis folgt erst in der fortgesetzten
       Beschreibung auf Zeile 2 - der Status steht hier VOR dem
       Klausel-Verweis, mit Beschreibungs-Resttext dazwischen, z.B.
       "... Neubauleistung Nein\\nsowie infolge ... (Klausel T590080k)".

    Der Klausel-Code selbst (z.B. "T590080k") ist als Anker genutzt statt
    der Beschreibung, weil er im Dokument eindeutig ist. Die Distanz beim
    "Status-vor-Klausel"-Fall ist bewusst auf ~1 Zeile gedeckelt, damit
    nicht versehentlich ein Status aus einem komplett anderen
    Leistungsbaustein aufgegriffen wird."""
    klausel = re.escape(klausel_code)
    return [
        rf"{klausel}\)?\s*({STATUS_WORD})",
        rf"({STATUS_WORD}).{{0,{_KLAUSEL_PROXIMITY_WINDOW}}}{klausel}",
    ]


def _klausel_selbstbeteiligung(klausel_code: str) -> list[str]:
    """Wie `_klausel_status`, aber für den "Selbstbeteiligungen"-Abschnitt,
    in dem statt eines Ja/Nein-Status ein Betrag bzw. eine Prozent-/
    Mindestbetrags-Angabe zur Klausel steht (siehe `SELBSTBETEILIGUNG`).
    Gleiche zwei Reihenfolge-Fälle wie dort, aus demselben Transkript
    verifiziert."""
    klausel = re.escape(klausel_code)
    return [
        rf"{klausel}\)?\s*({SELBSTBETEILIGUNG})",
        rf"({SELBSTBETEILIGUNG}).{{0,{_KLAUSEL_PROXIMITY_WINDOW}}}{klausel}",
    ]


def _scoped_label(
    section_anchor: str, label: str, value: str = TEXT, *aliases: str, not_followed_by: str | None = None
) -> list[str]:
    """Wie `_label`, verlangt aber zusätzlich, dass `section_anchor` (z.B.
    die Frage "Gibt es einen abweichenden Kontoinhaber?") im Text VOR diesem
    Label vorkommt.

    Grund: Mehrere Formularabschnitte verwenden dieselben generischen
    Beschriftungen (z.B. "Name", "Geburtsdatum", "Straße u. Haus-Nr." sowohl
    beim Antragsteller als auch beim abweichenden Kontoinhaber). Ohne
    Einschränkung gewinnt in `_match_field_in_pages` schlicht der Treffer auf
    der frühesten Seite/mit dem frühesten Muster - unabhängig davon, zu
    welchem Formularabschnitt er eigentlich gehört. Damit hätte z.B. das
    Feld "kontoinhaber_name" fälschlich den Namen des Antragstellers
    übernommen, obwohl beide Werte unterschiedlich sind.

    Nutzt ein nicht-gieriges `(?:...)`-Präfix vor dem eigentlichen Label;
    das dazwischenliegende `.*?` braucht DOTALL, um über Zeilenumbrüche
    hinweg zu matchen (siehe `re.DOTALL` in `mock_model._match_field_in_pages`).
    Anker und Label müssen dafür auf derselben Seite stehen, da dort pro
    Feld je Seite einzeln gesucht wird.

    `not_followed_by` (optional): schließt eine konkrete, bekannte
    Kollision INNERHALB desselben Abschnitts aus. Beispiel aus einem echten
    Dokument: das (im Formular leer gelassene) Kontoinhaber-Feld "Name"
    matchte fälschlich auf das spätere, inhaltlich andere Feld "Name des
    Kreditinstituts" - weil "name" als Teilstring auch dort vorkommt und
    DIESES Vorkommen (anders als das leere) tatsächlich einen Wert danach
    hat. Ein negativer Lookahead direkt nach dem Label schließt das aus,
    ohne den Suchradius für alle anderen gescopten Felder einzuschränken."""
    labels = (label,) + aliases
    exclude = rf"(?!\s*{_escape_label(not_followed_by)})" if not_followed_by else ""
    return [
        rf"(?:{_escape_label(section_anchor)}.*?){_escape_label(item)}{exclude}{_SAME_LINE_SEP}({value})"
        for item in labels
    ]


def _scoped_date(section_anchor: str, label: str, *aliases: str) -> list[str]:
    return _scoped_label(section_anchor, label, DATE, *aliases)


# Abschnitts-Anker für `_scoped_label`/`_scoped_date` unten - jeweils der
# Text der Frage/Überschrift, die den jeweiligen Formularabschnitt einleitet.
KONTOINHABER_ANCHOR = "Gibt es einen abweichenden Kontoinhaber?"
RISIKOORT_ANCHOR = "Versicherungsort"
# Scoped, weil "Name" allein sonst nachweislich am ERSTEN Formularabschnitt
# hängen bleibt - dort steht der MLP-BERATER-Name ("Berater Name Martin
# Blaton"), noch vor der eigentlichen Antragsteller-Sektion. Ohne Scoping
# gewinnt der frühere (falsche) Treffer, siehe `_scoped_label`-Docstring.
ANTRAGSTELLER_ANCHOR = "Versicherungsnehmer / Antragsteller"


MLP_FIELDS: list[tuple[str, str, list[str]]] = [
    # Gescoptes Muster zuerst (gewinnt bei Erfolg immer, siehe Sortierung
    # in `_match_field_in_pages`), ungescoptes Muster als Fallback für
    # Dokumentvarianten ohne diese Abschnittsüberschrift.
    ("name", "Name", _scoped_label(ANTRAGSTELLER_ANCHOR, "Name", TEXT, "Antragsteller", "Versicherungsnehmer") + _label("Name", TEXT, "Antragsteller", "Versicherungsnehmer")),
    ("strasse_hausnummer", "Straße u. Haus-Nr.", _scoped_label(ANTRAGSTELLER_ANCHOR, "Straße u. Haus-Nr.", TEXT, "Straße und Hausnummer", "Straße, Hausnummer") + _label("Straße u. Haus-Nr.", TEXT, "Straße und Hausnummer", "Straße, Hausnummer")),
    ("plz_wohnort", "PLZ, Wohnort", _scoped_label(ANTRAGSTELLER_ANCHOR, "PLZ, Wohnort", TEXT, "PLZ und Wohnort", "PLZ, Ort") + _label("PLZ, Wohnort", TEXT, "PLZ und Wohnort", "PLZ, Ort")),
    ("geburtsdatum", "Geburtsdatum", _scoped_date(ANTRAGSTELLER_ANCHOR, "Geburtsdatum") + _date("Geburtsdatum")),
    # Zusätzliches Muster je Feld deckt das im echten Dokument beobachtete
    # KOMBINIERTE Label "Versicherungsbeginn / -ablauf 01.07.2026 bis
    # 01.07.2028" ab (ein Formularfeld für beide Daten statt zweier
    # getrennter Labels) - die ursprünglichen `_date(...)`-Muster bleiben
    # als Fallback für Dokumentvarianten mit getrennten Labels erhalten.
    # "[/1]" statt reinem "/": an einem echten gescannten Dokument
    # nachgewiesen, dass docTR den Schrägstrich in "Versicherungsbeginn /
    # -ablauf" als Ziffer "1" liest ("Versicherungsbeginn 1 -ablauf") -
    # optische Ähnlichkeit von "/" und "1" bei niedrig aufgelösten Scans.
    ("versicherungsbeginn", "Versicherungsbeginn", _date("Versicherungsbeginn", "Versicherungsbeginn ab", "Beginn der Versicherung") + [rf"versicherungsbeginn\s*[/1]\s*-?ablauf[ \t]*:?[ \t]*({DATE})"]),
    ("versicherungsablauf", "Versicherungsablauf", _date("Versicherungsablauf", "Versicherungsende", "Ablauf der Versicherung") + [rf"versicherungsbeginn\s*[/1]\s*-?ablauf[ \t]*:?[ \t]*{DATE}[ \t]*bis[ \t]*({DATE})"]),
    ("vertragslaufzeit_jahre", "Vertragslaufzeit in Jahren", _robust(_label("Vertragslaufzeit in Jahren", r"\d{1,2}", "Vertragslaufzeit", "Laufzeit"), "Vertragslaufzeit in Jahren", r"\d{1,2}")),
    ("bruttobeitrag", "Bruttobeitrag inkl. Versicherungssteuer", _money_robust("Bruttobeitrag inkl. Versicherungssteuer", "Bruttobeitrag", "Gesamtbeitrag inkl. Versicherungssteuer")),
    ("versicherungssumme", "Versicherungs-/ Bausumme", _money_robust("Versicherungs-/ Bausumme", "Versicherungs-/Bausumme", "Bausumme", "Versicherungssumme")),
    ("vorsteuerabzugsberechtigt", "Vorsteuerabzugsberechtigt", _checkbox_robust("Vorsteuerabzugsberechtigt")),
    ("inkl_umsatzsteuer", "inkl. Umsatzsteuer", _checkbox_robust("inkl. Umsatzsteuer", "inklusive Umsatzsteuer")),
    ("absicherung_bauleistung", "Absicherung Bauleistung gewünscht?", _checkbox_robust("Absicherung Bauleistung gewünscht?", "Absicherung der Bauleistung gewünscht?")),
    ("grobe_fahrlaessigkeit_20000", "Absicherung der groben Fahrlässigkeit bis 20.000 EUR?", _checkbox_robust("Absicherung der groben Fahrlässigkeit bis 20.000 EUR?", "grobe Fahrlässigkeit bis 20.000 EUR")),
    ("wetterbedingte_luftbewegungen", "Einschluss außergewöhnlicher wetterbedingter Luftbewegungen", _checkbox_robust("Einschluss außergewöhnlicher wetterbedingter Luftbewegungen")),
    ("feuerrohbau", "Feuerrohbau", _checkbox_robust("Feuerrohbau")),
    ("altbauten_sachschaeden_t590080k", "Mitversicherung von Altbauten gegen Sachschäden ... (Klausel T590080k)", _klausel_status("T590080k")),
    ("ausstattung_kunstwert_t512807u", "Aufwendige Ausstattung / Kunstwert (Klausel T512807u)", _klausel_status("T512807u")),
    ("altbau_brand_t512805u", "Brand, Blitzschlag, Explosion für den Altbau (Klausel T512805u)", _klausel_status("T512805u")),
    ("pfahl_brunnen_senkkasten", "Pfahl-, Brunnen- und Senkkastengründung, Baugrundverbesserung", _robust(_label("Pfahl-, Brunnen- und Senkkastengründung, Baugrundverbesserung", SELBSTBETEILIGUNG, "Baugrundverbesserung"), "Baugrundverbesserung", SELBSTBETEILIGUNG)),
    ("baugrubenumschliessung", "Baugrubenumschließung", _robust(_label("Baugrubenumschließung", SELBSTBETEILIGUNG), "Baugrubenumschließung", SELBSTBETEILIGUNG)),
    ("wasserhaltung", "Wasserhaltung", _robust(_label("Wasserhaltung", SELBSTBETEILIGUNG), "Wasserhaltung", SELBSTBETEILIGUNG)),
    ("wasserdruckhaltende_dichtung", "Geklebte oder geschweißte wasserdruckhaltende Dichtung", _robust(_label("Geklebte oder geschweißte wasserdruckhaltende Dichtung", SELBSTBETEILIGUNG), "Geklebte oder geschweißte wasserdruckhaltende Dichtung", SELBSTBETEILIGUNG)),
    # Steht im Dokument direkt vor den übrigen Selbstbeteiligungs-Feldern
    # ("Mit folgenden Selbstbeteiligungen: - Grundselbstbeteiligung ... -
    # Nachhaftung ... - Altbauten gegen Einsturz ...") - gehört daher hier
    # hin statt weiter unten bei Bauherrenhaftpflicht/Versicherungsort.
    ("grundselbstbeteiligung", "Grundselbstbeteiligung", _robust(_label("Grundselbstbeteiligung", SELBSTBETEILIGUNG), "Grundselbstbeteiligung", SELBSTBETEILIGUNG)),
    ("nachhaftung_6_monate", "Nachhaftung bis 6 Monate gem. Klausel TK5290", _klausel_selbstbeteiligung("TK5290")),
    ("altbauten_einsturz_tk5155", "Altbauten gegen Einsturz gem. Klausel TK5155", _klausel_selbstbeteiligung("TK5155")),
    ("altbauten_sachschaeden_t590081k", "Altbauten gegen Sachschäden gem. Klausel T590081k", _klausel_selbstbeteiligung("T590081k")),
    ("altbauten_kunstwert_t512807u", "Aufwendige Ausstattung / Kunstwert gem. Klausel T512807u", _klausel_selbstbeteiligung("T512807u")),
    ("altbauten_brand_t512805u", "Brand, Blitzschlag, Explosionsschäden für den Altbau gem. Klausel T512805u", _klausel_selbstbeteiligung("T512805u")),
    ("art_bauvorhaben", "Art des Bauvorhabens", _label("Art des Bauvorhabens", TEXT, "Bauvorhaben")),
    # _label_until zuerst (mehrzeilig bis zum nächsten Feld "Liegt das
    # Bauvorhaben in einem Bergbaugebiet?" - an einem echten Dokument war
    # der Beschreibungstext >1000 Zeichen lang, u.a. eine Maßnahmen-Tabelle
    # und ein Unterschriftenblock). Alte einzeilige Variante als Fallback,
    # falls "Bergbaugebiet" mal nicht auf derselben Seite folgt.
    ("beschreibung", "Beschreibung", _label_until("Beschreibung", "Liegt das Bauvorhaben in einem Bergbaugebiet?") + _label("Beschreibung", r"[^\n]{2,500}")),
    ("bergbaugebiet", "Liegt das Bauvorhaben in einem Bergbaugebiet?", _checkbox_robust("Liegt das Bauvorhaben in einem Bergbaugebiet?", "Bauvorhaben in einem Bergbaugebiet")),
    ("feuergefaehrliche_nachbarbetriebe", "Gefahrerhöhung durch feuergefährliche Nachbarbetriebe", _checkbox_robust("Gefahrerhöhung durch feuergefährliche Nachbarbetriebe")),
    # Zusätzliches Muster: im echten Dokument bricht diese lange Frage über
    # eine Zeile um genau zwischen "500.000" und "EUR" - die Text-Extraktion
    # hängt "Nein" dabei mitten hinein ("... über 500.000 Nein\nEUR verbaut
    # ? *"), noch vor "EUR verbaut?". `_label_nearby` sucht den Ja/Nein-Wert
    # daher zusätzlich direkt nach der (im Dokument stabilen) Zahl statt nur
    # nach der vollständigen Frage.
    ("solar_anlagen_ueber_500000", "Photovoltaik-/ Solar-/ Geothermie-Anlagen über 500.000 EUR", _checkbox("Photovoltaik-/ Solar-/ Geothermie-Anlagen über 500.000 EUR", "Werden Photovoltaik-/ Solar-/ Geothermie-Anlagen über 500.000 EUR verbaut?") + [_label_nearby("500.000", YES_NO)]),
    ("denkmalschutz", "Steht das Gebäude unter Denkmalschutz?", _checkbox_robust("Steht das Gebäude unter Denkmalschutz?", "Denkmalschutz")),
    ("nettobeitrag_bauleistung", "Nettobeitrag Bauleistung", _money_robust("Nettobeitrag Bauleistung (ohne Berücksichtigung der Mindestprämie)", "Nettobeitrag Bauleistung")),
    # Zusätzliches Muster: im echten Dokument bricht der Klammer-Zusatz
    # "(unter Berücksichtigung der Mindestprämie)" über eine Zeile um, der
    # Betrag landet dabei MITTEN in der (dadurch über 2 Zeilen offenen)
    # Klammer ("... Bauherrenhaftpflicht (unter Berücksichtigung der 59,00
    # EUR\nMindestprämie)") - der einzeilige Klammer-Zusatz in `_SAME_LINE_SEP`
    # deckt das nicht ab, `_label_nearby` schon.
    ("nettobeitrag_bauherrenhaftpflicht", "Nettobeitrag Bauherrenhaftpflicht", _money("Nettobeitrag Bauherrenhaftpflicht (unter Berücksichtigung der Mindestprämie)", "Nettobeitrag Bauherrenhaftpflicht") + [_label_nearby("Nettobeitrag Bauherrenhaftpflicht", MONEY)]),
    ("nettobeitrag_gesamt", "Nettobeitrag", _money_robust("Nettobeitrag (unter Berücksichtigung der Mindestprämie)", "Nettobeitrag gesamt")),
    ("gesamtbeitrag_versicherungssteuer", "Gesamtbeitrag inkl. Versicherungssteuer", _money_robust("Gesamtbeitrag inkl. Versicherungssteuer")),
    ("absicherung_bauherrenhaftpflicht", "Absicherung der Bauherrenhaftpflicht", _robust(_label("Absicherung der Bauherrenhaftpflicht", STATUS_WORD), "Absicherung der Bauherrenhaftpflicht", STATUS_WORD)),
    # Eigenständiges Feld statt `_label("Selbstbeteiligung", ...)`: "Grund-
    # selbstbeteiligung" (siehe oben) enthält "Selbstbeteiligung" als
    # Teilstring OHNE Wortgrenze davor (zusammengeschriebenes Wort) - ein
    # einfacher Label-Anker würde dort versehentlich hineinmatchen. Negative
    # Lookbehind schließt genau diesen Fall aus (Matching läuft auf bereits
    # kleingeschriebenem Text, siehe `joined_lower` in `mock_model.py`).
    ("selbstbeteiligung_bauherrenhaftpflicht", "Selbstbeteiligung Bauherrenhaftpflicht", [rf"(?<!grund)selbstbeteiligung\s*:?\s*({SELBSTBETEILIGUNG})"]),
    # Alias "Versicherungsort" (ohne "/ Risikoort") entfernt: er ist ein
    # reines Präfix des primären Labels "Versicherungsort/ Risikoort" - an
    # einem echten Dokument nachgewiesen, dass er sich dadurch selbst
    # trifft und den REST des eigenen Labels ("/ Risikoort") als Wert
    # einfängt, statt der tatsächlichen Antwort. "Risikoort" allein bleibt
    # als Alias, da es kein Präfix-Teilstring des primären Labels ist.
    ("versicherungsort", "Versicherungsort/ Risikoort", _label("Versicherungsort/ Risikoort", TEXT, "Risikoort")),
    ("risikoort_strasse_hausnummer", "Straße u. Haus-Nr. (Risikoort)", _scoped_label(RISIKOORT_ANCHOR, "Straße u. Haus-Nr.", TEXT, "Straße und Hausnummer")),
    ("risikoort_plz", "PLZ Risikoort", _label("PLZ Risikoort", r"\d{5}", "PLZ des Risikoorts")),
    # Zusätzliches _label_nearby-Fallback explizit auf den KÜRZEREN Anker
    # "Vorversicherung" (nicht die volle Phrase wie bei `_checkbox_robust`
    # sonst üblich): an einem echten Dokument nachgewiesen, dass "vorhanden"
    # von der OCR bis zur Unkenntlichkeit verstümmelt wird (z.B.
    # "Vorversicherung,.vrhanden ?") - ein Fallback auf die volle Phrase
    # würde dort ebenfalls nie treffen, "Vorversicherung" allein (im
    # Dokument eindeutig) schon.
    ("vorversicherung", "Vorversicherung vorhanden?", _checkbox("Vorversicherung vorhanden?") + [_label_nearby("Vorversicherung", YES_NO)]),
    ("antrag_abgelehnt", "Ähnlicher Antrag abgelehnt?", _checkbox_robust("Ist bereits ein ähnlicher Antrag abgelehnt worden?", "ähnlicher Antrag abgelehnt")),
    ("schaeden_letzte_5_jahre", "Schäden in den letzten 5 Jahren", _checkbox_robust("Waren Sie in den letzten 5 Jahren von Schäden betroffen?", "Schäden in den letzten 5 Jahren")),
    ("besondere_hinweise", "Besondere Hinweise und Vereinbarungen", _label("Besondere Hinweise und Vereinbarungen", r"[^\n]{2,500}")),
    ("abweichender_kontoinhaber", "Abweichender Kontoinhaber vorhanden?", _checkbox_robust("Gibt es einen abweichenden Kontoinhaber?")),
    ("kontoinhaber_name", "Name Kontoinhaber", _scoped_label(KONTOINHABER_ANCHOR, "Name", TEXT, not_followed_by="des Kreditinstituts")),
    ("kontoinhaber_firmenname", "Firmenname Kontoinhaber", _label("Firmenname", TEXT)),
    ("kontoinhaber_geburtsdatum", "Geburtsdatum Kontoinhaber", _scoped_date(KONTOINHABER_ANCHOR, "Geburtsdatum")),
    ("kontoinhaber_strasse", "Straße, Hausnummer Kontoinhaber", _scoped_label(KONTOINHABER_ANCHOR, "Straße, Hausnummer", TEXT)),
    ("kontoinhaber_plz_ort", "PLZ, Ort Kontoinhaber", _scoped_label(KONTOINHABER_ANCHOR, "PLZ, Ort", TEXT)),
    # Gescopt, weil "Kreditinstitut" allein sonst z.B. bei einem
    # gescannten Dokument (docTR-Fallback) fälschlich "MLP Banking AG" aus
    # dem wiederkehrenden Seitenfuß ("Bankverbindung ... MLP Banking AG")
    # treffen kann statt dem tatsächlichen Kreditinstitut des
    # Kontoinhabers - gleiche Bug-Klasse wie bei kontoinhaber_iban oben.
    ("kontoinhaber_kreditinstitut", "Name des Kreditinstituts", _scoped_label(KONTOINHABER_ANCHOR, "Name des Kreditinstituts", TEXT, "Kreditinstitut")),
    # Gescopt, weil "IBAN" allein sonst nachweislich die MLP-eigene
    # Bankverbindung aus dem Seitenfuß trifft ("Bankverbindung ... IBAN:
    # DE19 6723 ...", wiederholt sich auf fast jeder Seite) statt der
    # tatsächlichen Kontoinhaber-IBAN - der Seitenfuß steht auf einer
    # FRÜHEREN Seite als der eigentliche Kontoinhaber-Abschnitt und würde
    # ohne Scoping gewinnen.
    ("kontoinhaber_iban", "IBAN Kontoinhaber", _scoped_label(KONTOINHABER_ANCHOR, "IBAN", r"[A-Z]{2}\s?[A-Z0-9 ]{12,30}")),
]
