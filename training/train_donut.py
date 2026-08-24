"""Fine-Tuning von Donut (naver-clova-ix/donut-base) auf den exportierten Vertragsdaten.

Voraussetzung: `prepare_dataset.py` wurde bereits ausgeführt und hat ein
`manifest.jsonl` erzeugt (Bild -> Ziel-JSON mit den Vertragsfeldern).

WICHTIG: Für brauchbare Ergebnisse werden üblicherweise mind. 200-500 validierte
Verträge benötigt. Mit wenigen Dutzend Beispielen dient dieses Skript vor allem
dazu, die Pipeline end-to-end zu verifizieren.

Nutzung:
    python train_donut.py --manifest ./data/dataset/manifest.jsonl \
        --output ./output/contract-donut --epochs 10
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from pdf2image import convert_from_path
from PIL import Image
from torch.utils.data import Dataset
from transformers import DonutProcessor, VisionEncoderDecoderModel, VisionEncoderDecoderConfig
from transformers import Seq2SeqTrainer, Seq2SeqTrainingArguments

MODEL_ID = "naver-clova-ix/donut-base"
TASK_TOKEN = "<s_contract>"
MAX_LENGTH = 768
IMAGE_SIZE = [1280, 960]


def load_image(path: str) -> Image.Image:
    if path.lower().endswith(".pdf"):
        return convert_from_path(path, dpi=200)[0].convert("RGB")
    return Image.open(path).convert("RGB")


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

        target_json = entry["ground_truth"]["gt_parse"]
        target_sequence = TASK_TOKEN + json2token(target_json, sort_json_key=False) + self.processor.tokenizer.eos_token

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default="./output/contract-donut")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--lr", type=float, default=3e-5)
    args = parser.parse_args()

    config = VisionEncoderDecoderConfig.from_pretrained(MODEL_ID)
    config.encoder.image_size = IMAGE_SIZE
    config.decoder.max_length = MAX_LENGTH

    entries = [json.loads(line) for line in Path(args.manifest).open(encoding="utf-8")]
    field_keys = sorted({k for e in entries for k in e["ground_truth"]["gt_parse"]})

    processor = DonutProcessor.from_pretrained(MODEL_ID)
    processor.image_processor.size = {"height": IMAGE_SIZE[0], "width": IMAGE_SIZE[1]}
    special_tokens = [TASK_TOKEN] + [f"<s_{k}>" for k in field_keys] + [f"</s_{k}>" for k in field_keys]
    processor.tokenizer.add_special_tokens({"additional_special_tokens": special_tokens})

    model = VisionEncoderDecoderModel.from_pretrained(MODEL_ID, config=config)
    model.decoder.resize_token_embeddings(len(processor.tokenizer))
    model.config.pad_token_id = processor.tokenizer.pad_token_id
    model.config.decoder_start_token_id = processor.tokenizer.convert_tokens_to_ids([TASK_TOKEN])[0]

    dataset = ContractDataset(entries, processor)

    training_args = Seq2SeqTrainingArguments(
        output_dir=args.output,
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

    model.save_pretrained(args.output)
    processor.save_pretrained(args.output)
    print(f"Modell gespeichert unter: {args.output}")
    print("In backend/.env setzen: OCR_BACKEND=donut  MODEL_PATH=" + args.output)


if __name__ == "__main__":
    main()
