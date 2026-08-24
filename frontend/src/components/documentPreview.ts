import { api } from "../api/client.js";
import { h } from "../lib/dom.js";
import type { ContractField, DocumentDetail } from "../types/document.js";
import { createImageViewer } from "./imageViewer.js";
import { createPdfViewer } from "./pdfViewer.js";

export interface DocumentPreviewInstance {
  el: HTMLElement;
  update(doc: DocumentDetail, activeFieldId: string | null, drawingFieldId: string | null): void;
  destroy(): void;
}

/** Wählt ImageViewer/PdfViewer nach content_type, reicht Teardown durch.
 * Wird einmal pro Dokument erstellt (siehe imageViewer.ts/pdfViewer.ts). */
export function createDocumentPreview(
  doc: DocumentDetail,
  onDrawComplete: (page: number, bbox: [number, number, number, number]) => void
): DocumentPreviewInstance {
  const fileUrl = api.fileUrl(doc.id);
  const isImage = doc.content_type.startsWith("image/");
  const viewer = isImage
    ? createImageViewer(fileUrl, doc.filename, onDrawComplete)
    : createPdfViewer(fileUrl, onDrawComplete);

  const hintSlot = h("p", { class: "preview-hint" });
  hintSlot.style.display = "none";

  const el = h("div", { class: "document-preview" }, viewer.el, hintSlot);

  function update(currentDoc: DocumentDetail, activeFieldId: string | null, drawingFieldId: string | null): void {
    const drawingActive = drawingFieldId != null;
    const activeField: ContractField | null =
      currentDoc.fields.find((f) => f.id === (drawingFieldId ?? activeFieldId)) ?? null;
    const hasPosition = activeField != null && activeField.bbox_x != null && activeField.bbox_y != null;

    viewer.update(drawingActive ? null : activeField, drawingActive);

    if (!drawingActive && activeField && !hasPosition) {
      hintSlot.style.display = "";
      hintSlot.textContent =
        "Keine Positionsangabe für dieses Feld verfügbar. Über „Position markieren“ in der Feldliste kannst du sie selbst im Dokument einzeichnen.";
    } else {
      hintSlot.style.display = "none";
    }
  }

  function destroy(): void {
    viewer.destroy();
  }

  return { el, update, destroy };
}
