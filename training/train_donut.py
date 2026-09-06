"""Fine-Tuning von Donut (naver-clova-ix/donut-base) auf den exportierten Vertragsdaten.

Voraussetzung: `prepare_dataset.py` wurde bereits ausgeführt und hat ein
`manifest.jsonl` erzeugt (Bild -> Ziel-JSON mit den Vertragsfeldern).

WICHTIG: Für brauchbare Ergebnisse werden üblicherweise mind. 200-500 validierte
Verträge benötigt. Mit wenigen Dutzend Beispielen dient dieses Skript vor allem
dazu, die Pipeline end-to-end zu verifizieren.

Nutzung:
    python train_donut.py --manifest ./data/dataset/manifest.jsonl \
        --output ./output/contract-donut --epochs 10

Jeder Lauf landet in einem eigenen, zeitgestempelten Unterordner unter
--output (nichts wird stillschweigend überschrieben) mit einer
`metadata.json` (Manifest, Vertragstypen, Val-Feld-Exact-Match). "Promotion"
ist bewusst ein manueller Schritt: erst die Metrik prüfen, dann `MODEL_PATH`
in `backend/.env` auf den gewünschten Ordner setzen - ältere Läufe bleiben
als impliziter Rollback erhalten. Für Weitertraining auf neuen Daten (statt
immer neu ab dem Basismodell) `--continue-from <vorheriger-Ordner>` nutzen.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from datetime import datetime
from pathlib import Path

import torch
from pdf2image import convert_from_path
from PIL import Image
from torch.utils.data import Dataset
from transformers import DonutProcessor, VisionEncoderDecoderModel, VisionEncoderDecoderConfig
from transformers import Seq2SeqTrainer, Seq2SeqTrainingArguments

# Anteil des Manifests, der als Val-Split zurückgehalten wird (fester Seed für
# reproduzierbare Splits zwischen Trainingsläufen).
VAL_FRACTION = 0.15
SPLIT_SEED = 42
# Unterhalb dieser Dokumentzahl ist ein Train/Val-Split nicht sinnvoll (siehe
# Docstring oben: wenige Dutzend Beispiele dienen nur der Pipeline-Verifikation).
MIN_DOCUMENTS_FOR_SPLIT = 4

MODEL_ID = "naver-clova-ix/donut-base"
MAX_LENGTH = 768
IMAGE_SIZE = [1280, 960]
# Deckelt, wie viele Seiten maximal ins zusammengesetzte Bild einfließen -
# muss mit backend/app/ocr/donut_model.py's DonutOCRModel.MAX_PAGES
# übereinstimmen, sonst sieht das Modell beim Training eine andere
# Bildform/-verteilung als bei der späteren Inferenz.
MAX_PAGES = 4


def build_task_token(template_key: str) -> str:
    return f"<s_{template_key}>"


def load_image(path: str, max_pages: int = MAX_PAGES) -> Image.Image:
    """Rendert bis zu `max_pages` Seiten und fügt sie vertikal zu einem
    einzigen Bild zusammen. Vorher wurde ausschließlich Seite 1 genutzt,
    wodurch Vertragsinhalt auf späteren Seiten fürs Training komplett
    verloren ging (siehe auch backend/app/ocr/donut_model.py - derselbe Fix
    dort für die Inferenz)."""
    if path.lower().endswith(".pdf"):
        images = [image.convert("RGB") for image in convert_from_path(path, dpi=200)[:max_pages]]
    else:
        images = [Image.open(path).convert("RGB")]

    if len(images) == 1:
        return images[0]

    width = max(image.width for image in images)
    total_height = sum(image.height for image in images)
    composite = Image.new("RGB", (width, total_height), color="white")
    y = 0
    for image in images:
        composite.paste(image, (0, y))
        y += image.height
    return composite


def json2token(obj, sort_json_key: bool = False) -> str:
    """Serialisiert Ziel-JSON in Donuts Token-Zielformat (<s_key>wert</s_key>,
    verschachtelt) - das Gegenstück zu `DonutProcessor.token2json` bei der
    Inferenz. Ist nicht Teil von `transformers`, muss selbst mitgeliefert werden."""
    if isinstance(obj, dict):
        keys = sorted(obj.keys(), reverse=True) if sort_json_key else obj.keys()
        return "".join(f"<s_{k}>{json2token(obj[k], sort_json_key)}</s_{k}>" for k in keys)
    if isinstance(obj, list):
        return r"<sep/>".join(json2token(item, sort_json_key) for item in obj)
    return "" if obj is None else str(obj)


class ContractDataset(Dataset):
    def __init__(self, entries: list[dict], processor: DonutProcessor):
        self.entries = entries
        self.processor = processor

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, idx: int):
        entry = self.entries[idx]
        image = load_image(entry["source_file"])
        pixel_values = self.processor(image, random_padding=True, return_tensors="pt").pixel_values.squeeze()

        # Eigener Task-Token pro Vertragstyp (Fallback "contract" für
        # Manifeste aus einer Version von prepare_dataset.py, die
        # template_key noch nicht mitschreibt) - sonst würden Felder aus
        # allen Vertragstypen in ein gemeinsames Vokabular/Prompt gemischt.
        task_token = build_task_token(entry.get("template_key", "contract"))
        target_json = entry["ground_truth"]["gt_parse"]
        target_sequence = task_token + json2token(target_json, sort_json_key=False) + self.processor.tokenizer.eos_token

        labels = self.processor.tokenizer(
            target_sequence,
            add_special_tokens=False,
            max_length=MAX_LENGTH,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        ).input_ids.squeeze(0)
        labels[labels == self.processor.tokenizer.pad_token_id] = -100
        return {"pixel_values": pixel_values, "labels": labels}


def _decoder_input_ids_for(processor: DonutProcessor, model, task_token: str):
    """Baut den Start-Decoder-Input für ein Task-Token passend zu der beim
    Training gewählten decoder_start_token_id (siehe main(): entweder ist das
    Task-Token selbst der Start (genau ein Vertragstyp im Manifest), oder ein
    gemeinsames BOS geht dem Task-Token voraus (mehrere Vertragstypen)) -
    muss mit backend/app/ocr/donut_model.py's Inferenz-Logik übereinstimmen."""
    task_token_ids = processor.tokenizer(task_token, add_special_tokens=False, return_tensors="pt").input_ids
    if model.config.decoder_start_token_id == task_token_ids[0, 0].item():
        return task_token_ids
    bos_token = processor.tokenizer.bos_token or ""
    return processor.tokenizer(bos_token + task_token, add_special_tokens=False, return_tensors="pt").input_ids


def _normalize_value(value) -> str:
    return str(value if value is not None else "").strip().lower()


def evaluate(model, processor: DonutProcessor, entries: list[dict], device: str) -> float:
    """Einfache Feld-Exact-Match-Rate über den Val-Split (kein BLEU/Edit-
    Distance/Kalibrierung - das wäre für diesen Zweck unverhältnismäßig).
    Ohne diese Zahl lässt sich nie objektiv sagen, ob ein neues Modell besser
    ist als der vorherige Checkpoint oder als das Mock-Backend (TODO.md
    Punkt 3)."""
    was_training = model.training
    model.eval()
    correct = 0
    total = 0
    try:
        with torch.no_grad():
            for entry in entries:
                image = load_image(entry["source_file"])
                pixel_values = processor(image, return_tensors="pt").pixel_values.to(device)
                task_token = build_task_token(entry.get("template_key", "contract"))
                decoder_input_ids = _decoder_input_ids_for(processor, model, task_token).to(device)

                outputs = model.generate(
                    pixel_values,
                    decoder_input_ids=decoder_input_ids,
                    max_length=MAX_LENGTH,
                    pad_token_id=processor.tokenizer.pad_token_id,
                    eos_token_id=processor.tokenizer.eos_token_id,
                    use_cache=True,
                )
                sequence = processor.batch_decode(outputs)[0]
                sequence = sequence.replace(processor.tokenizer.eos_token, "").replace(
                    processor.tokenizer.pad_token, ""
                )
                sequence = re.sub(r"<.*?>", "", sequence, count=1).strip()  # Task-Token entfernen
                try:
                    predicted = processor.token2json(sequence)
                except Exception:
                    predicted = {}

                ground_truth = entry["ground_truth"]["gt_parse"]
                for field_key, expected in ground_truth.items():
                    total += 1
                    if _normalize_value(predicted.get(field_key)) == _normalize_value(expected):
                        correct += 1
    finally:
        model.train(was_training)

    return correct / total if total else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--output",
        default="./output/contract-donut",
        help="Basisverzeichnis - der eigentliche Lauf landet in einem "
        "zeitgestempelten Unterordner darunter (siehe Ausgabe am Ende).",
    )
    parser.add_argument(
        "--continue-from",
        default=None,
        help="Pfad zu einem bereits fine-getunten Checkpoint (z.B. ein vorheriger "
        "zeitgestempelter Output-Ordner), um darauf weiterzutrainieren statt immer "
        f"neu von {MODEL_ID} zu starten.",
    )
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--lr", type=float, default=3e-5)
    args = parser.parse_args()

    entries = [json.loads(line) for line in Path(args.manifest).open(encoding="utf-8")]
    field_keys = sorted({k for e in entries for k in e["ground_truth"]["gt_parse"]})
    template_keys = sorted({e.get("template_key", "contract") for e in entries})
    task_tokens = [build_task_token(key) for key in template_keys]
    print(f"Vertragstypen im Manifest: {', '.join(template_keys)}")

    if len(entries) < MIN_DOCUMENTS_FOR_SPLIT:
        print(
            f"Nur {len(entries)} Dokument(e) im Manifest - zu wenig für einen "
            "sinnvollen Train/Val-Split, trainiere auf allen Beispielen ohne Eval-Metrik."
        )
        train_entries, val_entries = entries, []
    else:
        shuffled = list(entries)
        random.Random(SPLIT_SEED).shuffle(shuffled)
        val_size = max(1, round(len(shuffled) * VAL_FRACTION))
        val_entries, train_entries = shuffled[:val_size], shuffled[val_size:]
        print(f"{len(train_entries)} Trainings-/{len(val_entries)} Val-Dokument(e) (Split-Seed {SPLIT_SEED})")

    base_model_path = args.continue_from or MODEL_ID

    processor = DonutProcessor.from_pretrained(base_model_path)
    if not args.continue_from:
        processor.image_processor.size = {"height": IMAGE_SIZE[0], "width": IMAGE_SIZE[1]}
    # add_special_tokens ist idempotent für bereits vorhandene Tokens (z.B.
    # beim Weitertrainieren mit --continue-from) - nur wirklich neue
    # Vertragstyp-/Feld-Tokens werden ergänzt.
    special_tokens = task_tokens + [f"<s_{k}>" for k in field_keys] + [f"</s_{k}>" for k in field_keys]
    processor.tokenizer.add_special_tokens({"additional_special_tokens": special_tokens})

    if args.continue_from:
        model = VisionEncoderDecoderModel.from_pretrained(base_model_path)
    else:
        config = VisionEncoderDecoderConfig.from_pretrained(MODEL_ID)
        config.encoder.image_size = IMAGE_SIZE
        config.decoder.max_length = MAX_LENGTH
        model = VisionEncoderDecoderModel.from_pretrained(MODEL_ID, config=config)

    model.decoder.resize_token_embeddings(len(processor.tokenizer))
    model.config.pad_token_id = processor.tokenizer.pad_token_id
    # Bei genau einem Vertragstyp im Manifest ist decoder_start_token_id wie
    # bisher gleich dem (einzigen) Task-Token selbst. Bei mehreren
    # Vertragstypen kann das nicht mehr funktionieren (decoder_start_token_id
    # ist ein einzelner, für alle Trainingsbeispiele geltender Wert) - dann
    # der vom Tokenizer bereitgestellte, von allen Vertragstypen unabhängige
    # BOS-Token als Start, mit dem jeweiligen Task-Token als erstem "echten"
    # Label-Token direkt danach (siehe ContractDataset.__getitem__,
    # _decoder_input_ids_for sowie backend/app/ocr/donut_model.py, das
    # denselben Aufbau bei der Inferenz spiegeln muss).
    if len(task_tokens) == 1:
        model.config.decoder_start_token_id = processor.tokenizer.convert_tokens_to_ids(task_tokens)[0]
    else:
        decoder_start_token_id = processor.tokenizer.bos_token_id
        if decoder_start_token_id is None:
            raise RuntimeError(
                "Der Tokenizer hat keinen bos_token - bei mehreren Vertragstypen im "
                "Manifest wird er als gemeinsamer decoder_start_token_id benötigt."
            )
        model.config.decoder_start_token_id = decoder_start_token_id

    dataset = ContractDataset(train_entries, processor)

    run_dir = Path(args.output) / datetime.now().strftime("%Y%m%d-%H%M%S")

    training_args = Seq2SeqTrainingArguments(
        output_dir=str(run_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.lr,
        fp16=torch.cuda.is_available(),
        logging_steps=10,
        save_strategy="epoch",
        save_total_limit=2,
        remove_unused_columns=False,
    )

    trainer = Seq2SeqTrainer(model=model, args=training_args, train_dataset=dataset)
    trainer.train()

    model.save_pretrained(run_dir)
    processor.save_pretrained(run_dir)

    val_accuracy = None
    if val_entries:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        val_accuracy = evaluate(model, processor, val_entries, device)
        print(f"Val-Feld-Exact-Match: {val_accuracy:.1%} (über {len(val_entries)} Dokument(e))")

    metadata = {
        "manifest": str(Path(args.manifest).resolve()),
        "continued_from": args.continue_from,
        "template_keys": template_keys,
        "field_keys": field_keys,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.lr,
        "train_documents": len(train_entries),
        "val_documents": len(val_entries),
        "val_field_exact_match": val_accuracy,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Modell gespeichert unter: {run_dir}")
    print(f"Metadaten (u.a. Val-Metrik): {run_dir / 'metadata.json'}")
    print("Nach Prüfung der Metrik in backend/.env setzen: OCR_BACKEND=donut  MODEL_PATH=" + str(run_dir))
    print(f"Für weiteres Training auf neuen Daten: --continue-from {run_dir}")


if __name__ == "__main__":
    main()
