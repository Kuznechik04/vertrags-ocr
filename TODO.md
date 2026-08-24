# Roadmap: Vertragserkennungsmodell von Vertrag zu Vertrag trainieren

Konzeptionsphase, vor Test und Rollout. Reihenfolge = Priorität.

## 1. Feldkatalog/Vertragstypen-Scope — 🔨 in Arbeit

`CONTRACT_FIELDS` (9 Felder in `backend/app/ocr/base.py`) war bisher fest auf
Versicherungsverträge zugeschnitten. Entscheidung: bestehendes Feldset bleibt
als "Versicherung"-Template erhalten, zusätzlich ein erweiterbares
"generisch"-Template für weitere Vertragstypen. Neue Felder müssen sich ohne
Codeänderung anlegen und nutzen lassen (siehe
`.claude/plans/private-projects-vertrags-ocr-training-velvety-dusk.md` für
die volle Architektur).

Zurückgestellte Folgepunkte:
- [ ] Frontend: Vertragstyp-Auswahl beim Upload (Dropdown aus `GET /api/templates`)
- [ ] Admin-UI zum Anlegen neuer Vertragstypen/Felder (aktuell nur über `/docs`)
- [ ] Optional: `template_key` ins Trainings-Manifest aufnehmen, falls später pro Vertragstyp getrennte Modelle trainiert werden sollen

## 2. Bounding-Box-Strategie für Donut

Donut liefert standardmäßig keine Positionsdaten — sobald von Mock auf Donut
umgestellt wird, verschwindet das Fundstellen-Highlighting im Review-UI.
Entscheidung nötig: reines Donut akzeptieren, oder zusätzlich LayoutLMv3
(Token-Klassifikation mit Positionsdaten) einführen. Beeinflusst das
Trainingsdatenformat, deshalb früh entscheiden.

## 3. Train/Val-Split + Eval-Metrik in der Trainingspipeline

`training/train_donut.py` trainiert aktuell ohne Split und ohne
Qualitätsmetrik. Ohne Holdout-Set + Metrik (z.B. Feld-Exact-Match) lässt sich
nie objektiv sagen, ob ein neues Donut-Modell besser als Mock bzw. als das
vorherige Modell ist. Schon mit den wenigen Test-Dokumenten umsetzbar, nicht
von echten Vertragsdaten abhängig.

## 4. Re-Training- und Modellversionierungs-Konzept

Aktuell rein manuelles CLI (`prepare_dataset.py` → `train_donut.py`), keine
Versionierung von `MODEL_PATH`. Für den Rollout: Trigger für Re-Training
festlegen (Zeitplan? Anzahl neuer validierter Verträge?) und Rollback-Konzept
für den Fall, dass ein neues Modell schlechter performt.

## 5. Datenschutz-/Rollenkonzept für echte Vertragsdaten

Sobald reale, personenbezogene Verträge hochgeladen werden: Aufbewahrungsfrist,
Löschkonzept, und dass der Admin-Export (`/export/training-data`)
Vertragsdaten nutzerübergreifend zusammenführt — DSGVO-relevant. Vor dem
ersten echten Upload klären, nicht danach.
