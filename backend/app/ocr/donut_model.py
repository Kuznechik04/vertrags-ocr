"""Backend für ein auf eure Verträge fine-getuntes Donut-Modell.

Donut (Document Understanding Transformer, huggingface.co/naver-clova-ix/donut-base)
liest das Dokument als Bild und generiert direkt strukturiertes JSON mit den Feldwerten
(kein separater OCR-Schritt nötig). Das passt gut, wenn Layout-Varianz hoch ist.

Erwartet ein Modellverzeichnis (siehe `training/train_donut.py`), das mit
`DonutProcessor` + `VisionEncoderDecoderModel` geladen werden kann.

Hinweis: Dieses Modul importiert torch/transformers nur bei tatsächlicher Nutzung
(lazy import), damit das Mock-Backend auch ohne diese schweren Abhängigkeiten läuft.
"""
from __future__ import annotations

import json
import re

from app.ocr.base import BaseOCRModel, FieldPrediction, FieldSpec


class DonutOCRModel(BaseOCRModel):
    def __init__(self, model_path: str):
        # Lazy import: torch/transformers werden erst geladen, wenn dieses Backend
        # tatsächlich instanziiert wird (OCR_BACKEND=donut).
        import torch
        from transformers import DonutProcessor, VisionEncoderDecoderModel

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.processor = DonutProcessor.from_pretrained(model_path)
        self.model = VisionEncoderDecoderModel.from_pretrained(model_path).to(self.device)
        self.model.eval()

    def page_count(self, file_path: str) -> int:
        if file_path.lower().endswith(".pdf"):
            from pdf2image import convert_from_path

            return len(convert_from_path(file_path))
        return 1

    def predict(self, file_path: str, fields: list[FieldSpec]) -> list[FieldPrediction]:
        image = self._load_first_page_as_image(file_path)

        task_prompt = "<s_contract>"
        decoder_input_ids = self.processor.tokenizer(
            task_prompt, add_special_tokens=False, return_tensors="pt"
        ).input_ids

        pixel_values = self.processor(image, return_tensors="pt").pixel_values

        outputs = self.model.generate(
            pixel_values.to(self.device),
            decoder_input_ids=decoder_input_ids.to(self.device),
            max_length=self.model.decoder.config.max_position_embeddings,
            pad_token_id=self.processor.tokenizer.pad_token_id,
            eos_token_id=self.processor.tokenizer.eos_token_id,
            use_cache=True,
            return_dict_in_generate=True,
            output_scores=True,
        )

        sequence = self.processor.batch_decode(outputs.sequences)[0]
        sequence = sequence.replace(self.processor.tokenizer.eos_token, "").replace(
            self.processor.tokenizer.pad_token, ""
        )
        sequence = re.sub(r"<.*?>", "", sequence, count=1).strip()  # task-prompt entfernen

        try:
            parsed: dict = self.processor.token2json(sequence)
        except Exception:
            parsed = {}

        # Grobe Sequenz-Confidence aus den Generation-Scores ableiten
        confidence = self._sequence_confidence(outputs)

        predictions: list[FieldPrediction] = []
        for field in fields:
            value = parsed.get(field.field_key)
            predictions.append(
                FieldPrediction(
                    field_key=field.field_key,
                    field_label=field.field_label,
                    value=str(value) if value is not None else None,
                    confidence=confidence if value is not None else 0.0,
                    page=1,
                    bbox=None,  # Donut liefert standardmäßig keine Bounding Boxes;
                                # für Bounding Boxes ggf. LayoutLMv3 (Token-Klassifikation) nutzen.
                )
            )
        return predictions

    def _sequence_confidence(self, outputs) -> float:
        try:
            scores = outputs.scores  # tuple of logits per generation step
            probs = [self.torch.softmax(s, dim=-1).max().item() for s in scores]
            return round(sum(probs) / len(probs), 3) if probs else 0.0
        except Exception:
            return 0.0

    def _load_first_page_as_image(self, file_path: str):
        from PIL import Image

        if file_path.lower().endswith(".pdf"):
            from pdf2image import convert_from_path

            pages = convert_from_path(file_path, dpi=200)
            return pages[0].convert("RGB")
        return Image.open(file_path).convert("RGB")
