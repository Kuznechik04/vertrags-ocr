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
YES_NO = r"(?:ja|nein|yes|no|[xX])"
TEXT = r"[^\n.]{2,120}"
# MLP nutzt für Leistungsbausteine ("gewünscht"/"nicht gewünscht") ein
# anderes Vokabular als für die übrigen Ja/Nein-Fragen ("ja"/"nein") - siehe
# `_klausel_status` unten, an einem echten Dokument-Transkript verifiziert.
# "nicht gewünscht" muss vor "gewünscht" stehen, sonst würde die Alternation
# an der Position von "nicht" scheitern, bevor sie den vollen Ausdruck
# probiert - `re.search` sucht ohnehin den am weitesten links liegenden
# Treffer, das ist hier nur zur Klarheit so sortiert.
STATUS_WORD = r"(?:nicht\s+gewünscht|gewünscht|ja|nein|yes|no|[xX])"
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


def _label(label: str, value: str = TEXT, *aliases: str) -> list[str]:
    labels = (label,) + aliases
    return [rf"{_escape_label(item)}\s*:?\s*({value})" for item in labels]


def _checkbox(label: str, *aliases: str) -> list[str]:
    # Unterstützt sowohl "Ja/Nein"-Angaben als auch ein angekreuztes X.
    return _label(label, YES_NO, *aliases)


def _date(label: str, *aliases: str) -> list[str]:
    return _label(label, DATE, *aliases)


def _money(label: str, *aliases: str) -> list[str]:
    return _label(label, MONEY, *aliases)


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


def _scoped_label(section_anchor: str, label: str, value: str = TEXT, *aliases: str) -> list[str]:
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
    Feld je Seite einzeln gesucht wird."""
    labels = (label,) + aliases
    return [
        rf"(?:{_escape_label(section_anchor)}.*?){_escape_label(item)}\s*:?\s*({value})"
        for item in labels
    ]


def _scoped_date(section_anchor: str, label: str, *aliases: str) -> list[str]:
    return _scoped_label(section_anchor, label, DATE, *aliases)


# Abschnitts-Anker für `_scoped_label`/`_scoped_date` unten - jeweils der
# Text der Frage/Überschrift, die den jeweiligen Formularabschnitt einleitet.
KONTOINHABER_ANCHOR = "Gibt es einen abweichenden Kontoinhaber?"
RISIKOORT_ANCHOR = "Versicherungsort"


MLP_FIELDS: list[tuple[str, str, list[str]]] = [
    ("name", "Name", _label("Name", TEXT, "Antragsteller", "Versicherungsnehmer")),
    ("strasse_hausnummer", "Straße u. Haus-Nr.", _label("Straße u. Haus-Nr.", TEXT, "Straße und Hausnummer", "Straße, Hausnummer")),
    ("plz_wohnort", "PLZ, Wohnort", _label("PLZ, Wohnort", TEXT, "PLZ und Wohnort", "PLZ, Ort")),
    ("geburtsdatum", "Geburtsdatum", _date("Geburtsdatum")),
    ("versicherungsbeginn", "Versicherungsbeginn", _date("Versicherungsbeginn", "Versicherungsbeginn ab", "Beginn der Versicherung")),
    ("versicherungsablauf", "Versicherungsablauf", _date("Versicherungsablauf", "Versicherungsende", "Ablauf der Versicherung")),
    ("vertragslaufzeit_jahre", "Vertragslaufzeit in Jahren", _label("Vertragslaufzeit in Jahren", r"\d{1,2}", "Vertragslaufzeit", "Laufzeit")),
    ("bruttobeitrag", "Bruttobeitrag inkl. Versicherungssteuer", _money("Bruttobeitrag inkl. Versicherungssteuer", "Bruttobeitrag", "Gesamtbeitrag inkl. Versicherungssteuer")),
    ("versicherungssumme", "Versicherungs-/ Bausumme", _money("Versicherungs-/ Bausumme", "Versicherungs-/Bausumme", "Bausumme", "Versicherungssumme")),
    ("vorsteuerabzugsberechtigt", "Vorsteuerabzugsberechtigt", _checkbox("Vorsteuerabzugsberechtigt")),
    ("inkl_umsatzsteuer", "inkl. Umsatzsteuer", _checkbox("inkl. Umsatzsteuer", "inklusive Umsatzsteuer")),
    ("absicherung_bauleistung", "Absicherung Bauleistung gewünscht?", _checkbox("Absicherung Bauleistung gewünscht?", "Absicherung der Bauleistung gewünscht?")),
    ("grobe_fahrlaessigkeit_20000", "Absicherung der groben Fahrlässigkeit bis 20.000 EUR?", _checkbox("Absicherung der groben Fahrlässigkeit bis 20.000 EUR?", "grobe Fahrlässigkeit bis 20.000 EUR")),
    ("wetterbedingte_luftbewegungen", "Einschluss außergewöhnlicher wetterbedingter Luftbewegungen", _checkbox("Einschluss außergewöhnlicher wetterbedingter Luftbewegungen")),
    ("feuerrohbau", "Feuerrohbau", _checkbox("Feuerrohbau")),
    ("altbauten_sachschaeden_t590080k", "Mitversicherung von Altbauten gegen Sachschäden ... (Klausel T590080k)", _klausel_status("T590080k")),
    ("ausstattung_kunstwert_t512807u", "Aufwendige Ausstattung / Kunstwert (Klausel T512807u)", _klausel_status("T512807u")),
    ("altbau_brand_t512805u", "Brand, Blitzschlag, Explosion für den Altbau (Klausel T512805u)", _klausel_status("T512805u")),
    ("pfahl_brunnen_senkkasten", "Pfahl-, Brunnen- und Senkkastengründung, Baugrundverbesserung", _label("Pfahl-, Brunnen- und Senkkastengründung, Baugrundverbesserung", SELBSTBETEILIGUNG, "Baugrundverbesserung")),
    ("baugrubenumschliessung", "Baugrubenumschließung", _label("Baugrubenumschließung", SELBSTBETEILIGUNG)),
    ("wasserhaltung", "Wasserhaltung", _label("Wasserhaltung", SELBSTBETEILIGUNG)),
    ("wasserdruckhaltende_dichtung", "Geklebte oder geschweißte wasserdruckhaltende Dichtung", _label("Geklebte oder geschweißte wasserdruckhaltende Dichtung", SELBSTBETEILIGUNG)),
    ("nachhaftung_6_monate", "Nachhaftung bis 6 Monate gem. Klausel TK5290", _klausel_selbstbeteiligung("TK5290")),
    ("altbauten_einsturz_tk5155", "Altbauten gegen Einsturz gem. Klausel TK5155", _klausel_selbstbeteiligung("TK5155")),
    ("altbauten_sachschaeden_t590081k", "Altbauten gegen Sachschäden gem. Klausel T590081k", _klausel_selbstbeteiligung("T590081k")),
    ("altbauten_kunstwert_t512807u", "Aufwendige Ausstattung / Kunstwert gem. Klausel T512807u", _klausel_selbstbeteiligung("T512807u")),
    ("altbauten_brand_t512805u", "Brand, Blitzschlag, Explosionsschäden für den Altbau gem. Klausel T512805u", _klausel_selbstbeteiligung("T512805u")),
    ("art_bauvorhaben", "Art des Bauvorhabens", _label("Art des Bauvorhabens", TEXT, "Bauvorhaben")),
    ("beschreibung", "Beschreibung", _label("Beschreibung", r"[^\n]{2,500}")),
    ("bergbaugebiet", "Liegt das Bauvorhaben in einem Bergbaugebiet?", _checkbox("Liegt das Bauvorhaben in einem Bergbaugebiet?", "Bauvorhaben in einem Bergbaugebiet")),
    ("feuergefaehrliche_nachbarbetriebe", "Gefahrerhöhung durch feuergefährliche Nachbarbetriebe", _checkbox("Gefahrerhöhung durch feuergefährliche Nachbarbetriebe")),
    ("solar_anlagen_ueber_500000", "Photovoltaik-/ Solar-/ Geothermie-Anlagen über 500.000 EUR", _checkbox("Photovoltaik-/ Solar-/ Geothermie-Anlagen über 500.000 EUR", "Werden Photovoltaik-/ Solar-/ Geothermie-Anlagen über 500.000 EUR verbaut?")),
    ("denkmalschutz", "Steht das Gebäude unter Denkmalschutz?", _checkbox("Steht das Gebäude unter Denkmalschutz?", "Denkmalschutz")),
    ("nettobeitrag_bauleistung", "Nettobeitrag Bauleistung", _money("Nettobeitrag Bauleistung (ohne Berücksichtigung der Mindestprämie)", "Nettobeitrag Bauleistung")),
    ("nettobeitrag_bauherrenhaftpflicht", "Nettobeitrag Bauherrenhaftpflicht", _money("Nettobeitrag Bauherrenhaftpflicht (unter Berücksichtigung der Mindestprämie)", "Nettobeitrag Bauherrenhaftpflicht")),
    ("nettobeitrag_gesamt", "Nettobeitrag", _money("Nettobeitrag (unter Berücksichtigung der Mindestprämie)", "Nettobeitrag gesamt")),
    ("gesamtbeitrag_versicherungssteuer", "Gesamtbeitrag inkl. Versicherungssteuer", _money("Gesamtbeitrag inkl. Versicherungssteuer")),
    ("grundselbstbeteiligung", "Grundselbstbeteiligung", _label("Grundselbstbeteiligung", SELBSTBETEILIGUNG)),
    ("absicherung_bauherrenhaftpflicht", "Absicherung der Bauherrenhaftpflicht", _label("Absicherung der Bauherrenhaftpflicht", STATUS_WORD)),
    # Eigenständiges Feld statt `_label("Selbstbeteiligung", ...)`: "Grund-
    # selbstbeteiligung" (siehe oben) enthält "Selbstbeteiligung" als
    # Teilstring OHNE Wortgrenze davor (zusammengeschriebenes Wort) - ein
    # einfacher Label-Anker würde dort versehentlich hineinmatchen. Negative
    # Lookbehind schließt genau diesen Fall aus (Matching läuft auf bereits
    # kleingeschriebenem Text, siehe `joined_lower` in `mock_model.py`).
    ("selbstbeteiligung_bauherrenhaftpflicht", "Selbstbeteiligung Bauherrenhaftpflicht", [rf"(?<!grund)selbstbeteiligung\s*:?\s*({SELBSTBETEILIGUNG})"]),
    ("versicherungsort", "Versicherungsort/ Risikoort", _label("Versicherungsort/ Risikoort", TEXT, "Versicherungsort", "Risikoort")),
    ("risikoort_strasse_hausnummer", "Straße u. Haus-Nr. (Risikoort)", _scoped_label(RISIKOORT_ANCHOR, "Straße u. Haus-Nr.", TEXT, "Straße und Hausnummer")),
    ("risikoort_plz", "PLZ Risikoort", _label("PLZ Risikoort", r"\d{5}", "PLZ des Risikoorts")),
    ("vorversicherung", "Vorversicherung vorhanden?", _checkbox("Vorversicherung vorhanden?")),
    ("antrag_abgelehnt", "Ähnlicher Antrag abgelehnt?", _checkbox("Ist bereits ein ähnlicher Antrag abgelehnt worden?", "ähnlicher Antrag abgelehnt")),
    ("schaeden_letzte_5_jahre", "Schäden in den letzten 5 Jahren", _checkbox("Waren Sie in den letzten 5 Jahren von Schäden betroffen?", "Schäden in den letzten 5 Jahren")),
    ("besondere_hinweise", "Besondere Hinweise und Vereinbarungen", _label("Besondere Hinweise und Vereinbarungen", r"[^\n]{2,500}")),
    ("abweichender_kontoinhaber", "Abweichender Kontoinhaber vorhanden?", _checkbox("Gibt es einen abweichenden Kontoinhaber?")),
    ("kontoinhaber_name", "Name Kontoinhaber", _scoped_label(KONTOINHABER_ANCHOR, "Name", TEXT)),
    ("kontoinhaber_firmenname", "Firmenname Kontoinhaber", _label("Firmenname", TEXT)),
    ("kontoinhaber_geburtsdatum", "Geburtsdatum Kontoinhaber", _scoped_date(KONTOINHABER_ANCHOR, "Geburtsdatum")),
    ("kontoinhaber_strasse", "Straße, Hausnummer Kontoinhaber", _scoped_label(KONTOINHABER_ANCHOR, "Straße, Hausnummer", TEXT)),
    ("kontoinhaber_plz_ort", "PLZ, Ort Kontoinhaber", _scoped_label(KONTOINHABER_ANCHOR, "PLZ, Ort", TEXT)),
    ("kontoinhaber_kreditinstitut", "Name des Kreditinstituts", _label("Name des Kreditinstituts", TEXT, "Kreditinstitut")),
    ("kontoinhaber_iban", "IBAN Kontoinhaber", _label("IBAN", r"[A-Z]{2}\s?[A-Z0-9 ]{12,30}")),
]
