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
            import fitz  # PyMuPDF

            with fitz.open(file_path) as doc:
                return doc.page_count
        return 1

    def predict(
        self, file_path: str, fields: list[FieldSpec], template_key: str | None = None
    ) -> list[FieldPrediction]:
        image = self._load_page_images(file_path)

        # Ein eigener Decoder-Prompt pro Vertragstyp-Template (statt eines
        # einzigen fixen "<s_contract>" für alle) - sonst würde ein auf
        # mehreren Vertragstypen trainiertes Modell deren Feld-Vokabular in
        # einem gemeinsamen, nicht unterscheidbaren Prompt vermischen (siehe
        # training/train_donut.py, TODO.md Punkt 1). "contract" als Fallback
        # hält ältere, vor diesem Feature trainierte Modelle lauffähig.
        task_prompt = f"<s_{template_key or 'contract'}>"
        task_token_ids = self.processor.tokenizer(
            task_prompt, add_special_tokens=False, return_tensors="pt"
        ).input_ids
        # Ein mit genau einem Vertragstyp trainiertes Modell (auch ältere,
        # vor diesem Feature trainierte Checkpoints) hat decoder_start_token_id
        # exakt auf das Task-Token selbst gesetzt - dort darf kein
        # zusätzliches BOS vorangestellt werden. Ein mit mehreren
        # Vertragstypen trainiertes Modell nutzt stattdessen den (von allen
        # Vertragstypen unabhängigen) Tokenizer-BOS als gemeinsamen Start,
        # mit dem Task-Token direkt danach (siehe train_donut.py). Welcher
        # Fall vorliegt, lässt sich am geladenen Modell selbst ablesen, statt
        # es zu erraten.
        decoder_start_token_id = self.model.config.decoder_start_token_id
        if decoder_start_token_id is not None and decoder_start_token_id == task_token_ids[0, 0].item():
            decoder_input_ids = task_token_ids
        else:
            bos_token = self.processor.tokenizer.bos_token or ""
            decoder_input_ids = self.processor.tokenizer(
                bos_token + task_prompt, add_special_tokens=False, return_tensors="pt"
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
                    # Donut generiert direkt strukturiertes JSON ohne Anker/Label-
                    # Konzept – anders als beim Mock-Backend (siehe mock_model.py)
                    # lässt sich hier nicht unterscheiden, ob das Feld im Dokument
                    # gar nicht vorkam oder nur kein Wert extrahiert wurde.
                    match_status="matched" if value is not None else "field_not_found",
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

    # Deckelt, wie viele Seiten maximal ins zusammengesetzte Bild einfließen -
    # muss mit training/train_donut.py's MAX_PAGES übereinstimmen, sonst
    # sieht das Modell bei der Inferenz eine andere Bildform/-verteilung als
    # beim Training.
    MAX_PAGES = 4

    def _load_page_images(self, file_path: str):
        """Rendert bis zu `MAX_PAGES` Seiten und fügt sie vertikal zu einem
        einzigen Bild zusammen (Donut nimmt nur ein Bild pro Vorhersage
        entgegen). Vorher wurde ausschließlich Seite 1 genutzt, wodurch
        Vertragsinhalt auf späteren Seiten komplett verloren ging - sowohl
        hier als auch beim Training (siehe training/train_donut.py,
        load_image)."""
        from PIL import Image

        if file_path.lower().endswith(".pdf"):
            import fitz  # PyMuPDF

            dpi = 200
            zoom = dpi / 72  # PyMuPDFs Basisauflösung ist 72 DPI
            matrix = fitz.Matrix(zoom, zoom)
            with fitz.open(file_path) as doc:
                images = [
                    Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    for pix in (page.get_pixmap(matrix=matrix) for page in doc[: self.MAX_PAGES])
                ]
        else:
            images = [Image.open(file_path).convert("RGB")]

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
