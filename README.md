# Vertrags-OCR Review

Fullstack-Anwendung zum Trainieren und Nutzen eines OCR-/Dokumentenverständnis-Modells
für Verträge: Upload von Vertragsdateien, automatische Feld-Erkennung, und eine
Weboberfläche zum Validieren bzw. Korrigieren der erkannten Felder. Die validierten
Korrekturen werden als Trainingsdatensatz für das Fine-Tuning eines eigenen Modells
verwendet (Active-Learning-Loop).

## Architektur

```
vertrags-ocr/
├── backend/      FastAPI-Server (Upload, DB, OCR-Inferenz, REST-API)
├── frontend/     TypeScript-Frontend ohne Vite/App-Bundler – Review-Oberfläche
├── training/     Skripte zum Export der Trainingsdaten & Fine-Tuning von Donut
└── docker-compose.yml
```

**Ablauf:**

1. Nutzer lädt einen Vertrag (PDF/Bild) über die Weboberfläche hoch.
2. Backend führt das aktuell aktive OCR-Backend aus (`OCR_BACKEND` in `.env`):
   - `mock`: regelbasierte Demo-Extraktion via `pdfplumber` + Regex – funktioniert
     sofort ohne Training, aber nur eingeschränkt robust. Guter Startpunkt, um
     die App End-to-End zu testen und erste Trainingsdaten zu sammeln.
   - `donut`: ein auf euren Verträgen fine-getuntes
     [Donut](https://huggingface.co/naver-clova-ix/donut-base)-Modell, das Bilder
     direkt in strukturiertes JSON übersetzt.
3. Erkannte Felder (Vertragsnummer, Vertragspartner, Laufzeit, Kündigungsfrist,
   Betrag, …) werden mit Konfidenzwert in der DB gespeichert.
4. Im Frontend sieht der Nutzer das Dokument neben der Feldliste, kann jedes Feld
   bestätigen oder korrigieren.
5. Nach Abschluss der Prüfung (`Prüfung abschließen`) gilt das Dokument als
   vollständig validiert und fließt in den Trainingsdatensatz-Export ein.
6. `training/prepare_dataset.py` holt alle validierten Dokumente über die API
   und baut daraus ein Donut-Trainingsset; `training/train_donut.py` führt das
   Fine-Tuning durch.
7. `.env` auf `OCR_BACKEND=donut` umstellen, sobald ein trainiertes Modell
   vorliegt – die App nutzt dann automatisch das eigene Modell statt der Mock-Regeln.

## Mehrnutzerbetrieb

Die App unterstützt mehrere Nutzerkonten mit E-Mail/Passwort-Login (JWT-Token):

- **Registrierung**: Jeder kann sich selbst unter `/register` registrieren.
- **Normale Nutzer** sehen und bearbeiten ausschließlich ihre eigenen hochgeladenen
  Verträge.
- **Admins** sehen und bearbeiten die Verträge *aller* Nutzer (u.a. für die
  Qualitätssicherung) und sind die einzigen, die den globalen Trainingsdaten-Export
  (`/api/documents/export/training-data`) nutzen können.
- **Bootstrap**: Der allererste registrierte Nutzer wird automatisch zum Admin.
  Alle danach registrierten Nutzer erhalten die Standardrolle "user". Weitere
  Admins können aktuell nur direkt in der Datenbank befördert werden
  (`UPDATE users SET role = 'admin' WHERE email = '...'`) – ein Admin-UI dafür
  ist eine sinnvolle nächste Ausbaustufe.
- **Wichtig für Produktivbetrieb**: `SECRET_KEY` in `backend/.env` unbedingt auf
  einen zufälligen, geheimen Wert setzen (siehe `.env.example`).

> Falls ihr bereits eine `vertrags_ocr.db` aus einer Version vor dem
> Mehrnutzerbetrieb habt: Diese Datei enthält noch keine `users`-Tabelle bzw.
> `owner_id`-Spalte. Am einfachsten für die lokale Entwicklung: die Datei löschen
> (`rm backend/vertrags_ocr.db`) und beim nächsten Start neu anlegen lassen –
> alte Test-Uploads gehen dabei verloren.

## Voraussetzungen

- Python 3.11+
- Node.js 20+
- Für das Fine-Tuning idealerweise eine GPU (CPU-Training ist möglich, aber langsam)
- Für das Mock-Backend bei gescannten PDFs/Bild-Uploads: Standardmäßig läuft
  OCR über **EasyOCR** (`MOCK_OCR_ENGINE=easyocr` in `backend/.env`, siehe
  `.env.example`) – ein reines `pip`-Paket, es ist **kein** zusätzliches
  Systemprogramm nötig, `pip install -r requirements.txt` reicht. Beim ersten
  OCR-Lauf lädt EasyOCR seine Modellgewichte (`craft_mlt_25k.pth`,
  `latin_g2.pth`) automatisch aus dem Internet herunter (paar hundert MB,
  danach lokal zwischengespeichert unter `~/.EasyOCR/`).
  PDF-Seiten werden dafür über `PyMuPDF` (ebenfalls reines `pip`-Paket) zu
  Bildern gerendert – auch hier kein Systemprogramm nötig.

  Alternativ kann per `MOCK_OCR_ENGINE=tesseract` auf **Tesseract**
  umgeschaltet werden (teils präziser bei sehr dichtem/tabellarischem Text),
  das braucht dann aber das `tesseract`-Kommandozeilenprogramm als
  Systempaket:

  ```bash
  # macOS
  brew install tesseract tesseract-lang

  # Ubuntu/Debian
  sudo apt install tesseract-ocr tesseract-ocr-deu
  ```

## Setup: Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # Achtung: inkl. torch/transformers, kann etwas dauern
cp .env.example .env
uvicorn app.main:app --reload
```

Backend läuft dann unter http://localhost:8000 (Health-Check: `/health`,
interaktive API-Doku: `/docs`).

> Tipp: Wenn ihr das Fine-Tuning nicht sofort braucht, könnt ihr `torch`,
> `transformers`, `datasets`, `accelerate`, `sentencepiece`, `seqeval` aus
> `backend/requirements.txt` vorerst weglassen – für `OCR_BACKEND=mock` werden
> sie nicht benötigt.

## Setup: Frontend

Das Frontend ist reines TypeScript + DOM-APIs – **kein React, kein Vite, kein
Bundler, kein esbuild**. Es gibt bewusst kein UI-Framework: Seiten/Komponenten
sind handgeschriebene Funktionen, die mit einem winzigen JSX-losen DOM-Helper
(`h()` in `src/lib/dom.ts`) echte DOM-Knoten bauen, ein selbstgeschriebener
History-API-Router (`src/lib/router.ts`) übernimmt das Routing, ein
Pub-Sub-Store (`src/auth/authStore.ts`) den Login-Status. `tsc` ist der
**einzige** Build-Schritt (transpiliert `src/**` nach `dist/`, reine
JS-Kompilierung, keine Binärabhängigkeiten); danach kopiert `scripts/build.mjs`
`index.html`/CSS nach `dist/` und trägt die Backend-URL ein; ausgeliefert wird
alles über einen kleinen Node-HTTP-Server (`scripts/dev-server.mjs`).
`pdfjs-dist` (liefert bereits echtes ESM) ist die einzige Laufzeit-Abhängigkeit
und wird direkt aus `node_modules` per
[Importmap](https://developer.mozilla.org/de/docs/Web/HTML/Element/script/type/importmap)
in `index.html` referenziert.

```bash
cd frontend
npm install
npm run dev
```

Frontend läuft unter http://localhost:5173 und spricht direkt mit dem Backend auf
Port 8000 (ohne Proxy). Die Backend-URL steht in `window.__APP_CONFIG__` in
`index.html` und wird beim Build von `scripts/build.mjs` gesetzt (Default
`http://localhost:8000`, überschreibbar per `API_BASE_URL=... npm run build`).

> **Wichtig für native ES-Module ohne Bundler:** Da der Browser den kompilierten
> App-Code direkt lädt (kein Bundler, der Pfade auflöst), müssen relative
> Imports in `src/**` die **`.js`-Endung** tragen, z.B. `import { api } from
> "../api/client.js"` – auch wenn die Quelldatei `client.ts` heißt.
> `tsconfig.json` nutzt dafür `"module"`/`"moduleResolution": "NodeNext"`, was
> solche Imports erzwingt und unverändert nach `dist/` durchreicht. Fehlt die
> Endung, kompiliert `tsc` zwar fehlerfrei, aber der Browser findet das Modul
> im Dev-Server nicht (Fallback auf `index.html`, "Failed to load module
> script") – die Seite bleibt dann leer.

### Fundstellen im Dokument (Sprung zur Position + Rahmen)

Wählt man im Review-UI ein Feld aus, springt die Vorschau automatisch zur
erkannten Fundstelle im Dokument und zeichnet einen Rahmen darum – sofern das
aktive OCR-Backend eine Position (Seite + Bounding Box) mitliefert:

- Das **Mock-Backend** liefert das inzwischen: Es merkt sich beim Regex-Match,
  welche Wörter (inkl. Seite und Koordinaten) getroffen wurden.
- Das **Donut-Backend** liefert aktuell keine Position (Donut generiert Text,
  ohne Koordinaten zu tracken) – dort erscheint kein Rahmen. Für positionsgenaue
  Erkennung mit einem echten Modell eignet sich zusätzlich LayoutLMv3 (siehe
  "Erweiterungsideen" unten).

PDFs werden dafür im Frontend über [`pdfjs-dist`](https://www.npmjs.com/package/pdfjs-dist)
selbst gerendert (auf `<canvas>`-Elemente) statt sie per `<iframe>` dem
systemeigenen PDF-Viewer zu überlassen – nur so lässt sich die Scroll-Position
und das Overlay programmatisch steuern. `pdfjs-dist` ist bereits in
`package.json` eingetragen und wird mit `npm install` automatisch mitinstalliert.

## Setup: Docker (Backend + Frontend zusammen)

```bash
docker compose up --build
```

Der Frontend-Container baut mit `npm run build` und liefert `dist/` anschließend
über denselben `scripts/dev-server.mjs` aus wie im lokalen Dev-Betrieb (statt
eines generischen Static-File-Servers) – nur so werden sowohl die `/node_modules/*`-
Importmap-Pfade als auch die kompilierten Module korrekt aufgelöst. Die
Backend-URL fürs Frontend wird beim Image-Build per Build-Arg `API_BASE_URL`
gesetzt (Default in `docker-compose.yml`: `http://localhost:8000`, passend zum
Port-Mapping des `backend`-Service).

## Training eines eigenen Modells

```bash
cd training
pip install -r requirements.txt

# 1. Validierte Verträge aus der App exportieren
python prepare_dataset.py --api http://localhost:8000 --out ./data/dataset

# 2. Donut fine-tunen (Richtwert: mind. 200-500 validierte Verträge für
#    brauchbare Generalisierung; mit wenigen Beispielen testet ihr nur die Pipeline)
python train_donut.py --manifest ./data/dataset/manifest.jsonl \
    --output ./output/contract-donut --epochs 10

# 3. Backend auf das neue Modell umstellen
#    In backend/.env setzen:
#    OCR_BACKEND=donut
#    MODEL_PATH=../training/output/contract-donut
```

## Konfidenzwerte

Die im UI angezeigte Konfidenz (z.B. "78 %") ist **kein fixer Wert** – sie
hängt vom jeweils aktiven Backend ab:

- **Mock-Backend**: rein heuristisch, abgeleitet aus der Position des
  getroffenen Regex-Musters in `PATTERNS` (`backend/app/ocr/mock_model.py`,
  `CONFIDENCE_BY_PATTERN_RANK`). Ein spezifischeres, erstes Muster ergibt eine
  höhere Konfidenz als ein generischeres, weiter hinten stehendes Muster. Das
  ist eine grobe Krücke, keine kalibrierte Wahrscheinlichkeit.
- **Donut-Backend**: echte Konfidenz, berechnet aus den Softmax-Scores der
  Modell-Generation (`DonutOCRModel._sequence_confidence`) – sobald ihr auf
  ein eigenes trainiertes Modell umsteigt, wird der Wert also aussagekräftiger.

## Erweiterungsideen

- **Bounding Boxes für Donut**: Für positionsgenaue Fundstellen auch mit einem
  trainierten Modell (statt nur beim Mock-Backend) eignet sich zusätzlich ein
  Token-Klassifikations-Modell wie LayoutLMv3, das pro Wort eine Position
  mitliefert – Donut selbst liefert standardmäßig keine Koordinaten.
- **Asynchrone Verarbeitung**: Für große PDF-Batches OCR über eine Queue
  (z.B. Celery/RQ) statt synchron im Request laufen lassen.
- **Admin-Verwaltung**: Ein UI/Endpoint, um weitere Admins zu ernennen oder
  Nutzerkonten zu deaktivieren, statt das aktuell manuell in der DB zu tun.
- **Passwort-Reset**: E-Mail-Versand für "Passwort vergessen" ergänzen.
- **Objekt-Speicher**: Für Produktion Uploads statt lokalem Ordner in S3/Azure
  Blob Storage ablegen (`app/core/config.py` entsprechend anpassen).
