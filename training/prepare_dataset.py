"""Baut aus den in der App validierten/korrigierten Verträgen einen Trainingsdatensatz
für das Fine-Tuning von Donut.

Ablauf (Active-Learning-Loop):
1. Nutzer lädt Verträge in der Weboberfläche hoch, das aktuelle Modell (zunächst das
   Mock-Backend) schlägt Feldwerte vor.
2. Nutzer validiert/korrigiert die Felder im Browser.
3. Dieses Skript liest die korrigierten Daten über die Backend-API
   (`/api/documents/export/training-data`) sowie die zugehörigen Original-Dateien
   und baut daraus ein Donut-kompatibles Trainingsset (Bild -> JSON-Zielstruktur).
4. `train_donut.py` fine-tuned Donut auf diesem Datensatz.
5. Nach dem Training: `OCR_BACKEND=donut` in der `.env` setzen, damit die App das
   neue Modell statt des Mock-Backends verwendet.

Nutzung (E-Mail/Passwort eines Admin-Accounts, der Export-Endpoint ist admin-only):
    python prepare_dataset.py --api http://localhost:8000 --out ./data/dataset \
        --email admin@example.com --password ...
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000", help="Basis-URL des Backends")
    parser.add_argument("--out", default="./data/dataset", help="Zielverzeichnis für den Datensatz")
    parser.add_argument("--email", required=True, help="E-Mail eines Admin-Accounts")
    parser.add_argument("--password", required=True, help="Passwort des Admin-Accounts")
    args = parser.parse_args()

    out_dir = Path(args.out)
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    login_resp = requests.post(
        f"{args.api}/api/auth/login",
        data={"username": args.email, "password": args.password},
        timeout=30,
    )
    login_resp.raise_for_status()
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    export_resp = requests.get(f"{args.api}/api/documents/export/training-data", headers=headers, timeout=30)
    export_resp.raise_for_status()
    rows = export_resp.json()
    if not rows:
        print("Keine validierten Dokumente gefunden. Erst Verträge in der App reviewen.")
        return

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_doc[row["document_id"]].append(row)

    manifest = []
    for doc_id, fields in by_doc.items():
        filename = fields[0]["filename"]
        target = {f["field_key"]: (f["final_value"] or "") for f in fields}

        # Original-Dokument (für die Bild-Konvertierung durch train_donut.py) herunterladen
        file_resp = requests.get(f"{args.api}/api/documents/{doc_id}/file", headers=headers, timeout=30)
        file_resp.raise_for_status()
        dest_file = images_dir / f"{doc_id}_{filename}"
        dest_file.write_bytes(file_resp.content)

        manifest.append(
            {
                "document_id": doc_id,
                "source_file": str(dest_file),
                "ground_truth": {"gt_parse": target},
            }
        )

    manifest_path = out_dir / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for entry in manifest:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"{len(manifest)} Dokumente exportiert -> {manifest_path}")
    print("Weiter mit: python train_donut.py --manifest", manifest_path)


if __name__ == "__main__":
    main()
