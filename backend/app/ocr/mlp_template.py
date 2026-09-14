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


def _label(label: str, value: str = TEXT, *aliases: str) -> list[str]:
    labels = (label,) + aliases
    return [rf"{re.escape(item)}\s*:?\s*({value})" for item in labels]


def _checkbox(label: str, *aliases: str) -> list[str]:
    # Unterstützt sowohl "Ja/Nein"-Angaben als auch ein angekreuztes X.
    return _label(label, YES_NO, *aliases)


def _date(label: str, *aliases: str) -> list[str]:
    return _label(label, DATE, *aliases)


def _money(label: str, *aliases: str) -> list[str]:
    return _label(label, MONEY, *aliases)


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
    ("altbauten_sachschaeden_t590080k", "Mitversicherung von Altbauten gegen Sachschäden ... (Klausel T590080k)", _checkbox("Klausel T590080k", "T590080k")),
    ("ausstattung_kunstwert_t512807u", "Aufwendige Ausstattung / Kunstwert (Klausel T512807u)", _checkbox("Klausel T512807u", "T512807u")),
    ("altbau_brand_t512805u", "Brand, Blitzschlag, Explosion für den Altbau (Klausel T512805u)", _checkbox("Klausel T512805u", "T512805u")),
    ("pfahl_brunnen_senkkasten", "Pfahl-, Brunnen- und Senkkastengründung, Baugrundverbesserung", _checkbox("Pfahl-, Brunnen- und Senkkastengründung, Baugrundverbesserung", "Baugrundverbesserung")),
    ("baugrubenumschliessung", "Baugrubenumschließung", _checkbox("Baugrubenumschließung")),
    ("wasserhaltung", "Wasserhaltung", _checkbox("Wasserhaltung")),
    ("wasserdruckhaltende_dichtung", "Geklebte oder geschweißte wasserdruckhaltende Dichtung", _checkbox("Geklebte oder geschweißte wasserdruckhaltende Dichtung")),
    ("nachhaftung_6_monate", "Nachhaftung bis 6 Monate gem. Klausel TK5290", _checkbox("Nachhaftung bis 6 Monate gem. Klausel TK5290", "TK5290")),
    ("altbauten_einsturz_tk5155", "Altbauten gegen Einsturz gem. Klausel TK5155", _checkbox("Altbauten gegen Einsturz gem. Klausel TK5155", "TK5155")),
    ("altbauten_sachschaeden_t590081k", "Altbauten gegen Sachschäden gem. Klausel T590081k", _checkbox("Altbauten gegen Sachschäden gem. Klausel T590081k", "T590081k")),
    ("altbauten_kunstwert_t512807u", "Aufwendige Ausstattung / Kunstwert gem. Klausel T512807u", _checkbox("Aufwendige Ausstattung / Kunstwert gem. Klausel T512807u", "T512807u")),
    ("altbauten_brand_t512805u", "Brand, Blitzschlag, Explosionsschäden für den Altbau gem. Klausel T512805u", _checkbox("Brand, Blitzschlag, Explosionsschäden für den Altbau gem. Klausel T512805u", "T512805u")),
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
    ("versicherungsort", "Versicherungsort/ Risikoort", _label("Versicherungsort/ Risikoort", TEXT, "Versicherungsort", "Risikoort")),
    ("risikoort_strasse_hausnummer", "Straße u. Haus-Nr. (Risikoort)", _label("Straße u. Haus-Nr.", TEXT, "Straße und Hausnummer")),
    ("risikoort_plz", "PLZ Risikoort", _label("PLZ Risikoort", r"\d{5}", "PLZ des Risikoorts")),
    ("vorversicherung", "Vorversicherung vorhanden?", _checkbox("Vorversicherung vorhanden?")),
    ("antrag_abgelehnt", "Ähnlicher Antrag abgelehnt?", _checkbox("Ist bereits ein ähnlicher Antrag abgelehnt worden?", "ähnlicher Antrag abgelehnt")),
    ("schaeden_letzte_5_jahre", "Schäden in den letzten 5 Jahren", _checkbox("Waren Sie in den letzten 5 Jahren von Schäden betroffen?", "Schäden in den letzten 5 Jahren")),
    ("besondere_hinweise", "Besondere Hinweise und Vereinbarungen", _label("Besondere Hinweise und Vereinbarungen", r"[^\n]{2,500}")),
    ("abweichender_kontoinhaber", "Abweichender Kontoinhaber vorhanden?", _checkbox("Gibt es einen abweichenden Kontoinhaber?")),
    ("kontoinhaber_name", "Name Kontoinhaber", _label("Name", TEXT)),
    ("kontoinhaber_firmenname", "Firmenname Kontoinhaber", _label("Firmenname", TEXT)),
    ("kontoinhaber_geburtsdatum", "Geburtsdatum Kontoinhaber", _date("Geburtsdatum")),
    ("kontoinhaber_strasse", "Straße, Hausnummer Kontoinhaber", _label("Straße, Hausnummer", TEXT)),
    ("kontoinhaber_plz_ort", "PLZ, Ort Kontoinhaber", _label("PLZ, Ort", TEXT)),
    ("kontoinhaber_kreditinstitut", "Name des Kreditinstituts", _label("Name des Kreditinstituts", TEXT, "Kreditinstitut")),
    ("kontoinhaber_iban", "IBAN Kontoinhaber", _label("IBAN", r"[A-Z]{2}\s?[A-Z0-9 ]{12,30}")),
]
