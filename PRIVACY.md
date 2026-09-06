# Datenschutz-/Aufbewahrungskonzept

Kurzer, bewusst schlanker Datenschutzhinweis für dieses Projekt (Einzelentwickler-
Nebenprojekt). Ersetzt keine rechtliche Beratung – vor dem ersten Upload *echter*
(personenbezogener) Vertragsdaten unbedingt selbst prüfen, ob das hier
beschriebene Vorgehen für den geplanten Einsatzzweck ausreicht.

## Welche personenbezogenen Daten fallen an?

- **Account-Daten**: E-Mail-Adresse, Passwort-Hash je registriertem Nutzer.
- **Vertragsdokumente**: die hochgeladenen PDF-/Bilddateien selbst
  (`backend/data/uploads/`) sowie die daraus erkannten/korrigierten Feldwerte
  in der Datenbank (`backend/vertrags_ocr.db`) – je nach Vertragsinhalt z.B.
  Namen, Vertragsnummern, Beträge.

## Löschung

- `DELETE /api/documents/{id}` entfernt sowohl den Datenbankeintrag als auch
  die zugehörige Datei von der Festplatte (siehe
  `backend/app/api/documents.py`, `delete_document` –
  durch `backend/tests/test_document_deletion.py` regressionsgesichert).
- Es gibt aktuell **keine automatische Löschfrist** – Dokumente bleiben
  bestehen, bis ein Nutzer (bzw. ein Admin für fremde Dokumente) sie aktiv
  löscht. Für einen Produktivbetrieb mit echten Vertragsdaten sollte hier
  eine Aufbewahrungsfrist festgelegt und ggf. ein automatisierter
  Lösch-Job ergänzt werden.
- Ein gelöschter Account (User-Zeile) wird aktuell nicht durch einen
  API-Endpunkt unterstützt; das Löschen eines Nutzerkontos samt aller
  Dokumente ist derzeit nur direkt in der Datenbank möglich.

## Admin-Exporte: nutzerübergreifende Zusammenführung

Zwei Endpunkte führen bewusst Vertragsdaten *aller* Nutzer zusammen und sind
deshalb auf Admins beschränkt:

- `GET /api/documents/export/training-data` – Grundlage für
  `training/prepare_dataset.py` (Donut-Fine-Tuning). Enthält Feldwerte und den
  ursprünglichen Dateinamen, **keine** Owner-/E-Mail-Spalte.
- `GET /api/documents/export/xlsx` – für Admins ein Export *aller* Nutzer
  inkl. `owner_email`/`owner_id`-Spalte (bewusst enthalten, da dieser Export
  für Buchhaltung/Qualitätssicherung gedacht ist, nicht fürs Modelltraining).

Beide Exporte sind für den lokalen, internen Gebrauch (Admin-Rechner)
gedacht – **nicht** an Dritte weitergeben oder öffentlich ablegen.
`training/prepare_dataset.py` speichert heruntergeladene Dokumente lokal unter
`training/data/` (bereits per `.gitignore` von Git ausgeschlossen) und benennt
sie nur nach `document_id` + Dateiendung, ohne den vom Nutzer vergebenen
Original-Dateinamen zu übernehmen (der könnte personenbezogene Daten
enthalten, z.B. den Namen des Vertragspartners).

## Vor dem ersten Upload echter Vertragsdaten

- Diese Datei lesen und die Aufbewahrungsfrist ggf. an die eigenen
  Anforderungen anpassen.
- `SECRET_KEY` und `ENVIRONMENT` gemäß README für den Produktivbetrieb
  konfigurieren.
- Zugriff auf `/api/auth/register` erst nach dem eigenen Admin-Bootstrap
  öffentlich machen (siehe README, Abschnitt "Mehrnutzerbetrieb").
