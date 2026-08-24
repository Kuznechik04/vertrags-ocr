import { h } from "../lib/dom.js";
import type { ContractField } from "../types/document.js";

export interface ViewerInstance {
  el: HTMLElement;
  update(activeField: ContractField | null, drawingActive: boolean): void;
  destroy(): void;
}

interface DragState {
  startX: number;
  startY: number;
  curX: number;
  curY: number;
}

/** Zeigt ein hochgeladenes Bild an, mit bbox-Overlay + Klick+Ziehen-Zeichenmodus
 * (siehe pdfViewer.ts für die PDF-Variante). Wird pro Dokument einmal erstellt
 * und danach nur per `update()` weitergereicht (kein Neuladen des Bildes bei
 * jeder Feld-Auswahl). */
export function createImageViewer(
  fileUrl: string,
  alt: string,
  onDrawComplete: (page: number, bbox: [number, number, number, number]) => void
): ViewerInstance {
  let drag: DragState | null = null;
  let currentDrawingActive = false;
  let lastScrolledFieldId: string | null = null;

  const img = h("img", { src: fileUrl, alt, draggable: false }) as HTMLImageElement;
  const overlay = h("div", { class: "bbox-overlay" }) as HTMLDivElement;
  overlay.style.display = "none";
  const dragRect = h("div", { class: "bbox-drawing" }) as HTMLDivElement;
  dragRect.style.display = "none";

  const frame = h(
    "div",
    { class: "image-viewer-frame", onmousedown: handleMouseDown },
    img,
    overlay,
    dragRect
  ) as HTMLDivElement;

  const hint = h("div", { class: "drawing-hint" }, "Ziehe mit der Maus ein Rechteck über die richtige Textstelle.");
  hint.style.display = "none";

  const el = h("div", { class: "image-viewer-scroll" }, hint, frame);

  function handleMouseDown(e: MouseEvent): void {
    if (!currentDrawingActive) return;
    e.preventDefault();
    const rect = frame.getBoundingClientRect();
    drag = { startX: e.clientX - rect.left, startY: e.clientY - rect.top, curX: e.clientX - rect.left, curY: e.clientY - rect.top };
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    renderDrag();
  }

  function handleMouseMove(e: MouseEvent): void {
    if (!drag) return;
    const rect = frame.getBoundingClientRect();
    drag.curX = Math.min(Math.max(e.clientX - rect.left, 0), rect.width);
    drag.curY = Math.min(Math.max(e.clientY - rect.top, 0), rect.height);
    renderDrag();
  }

  function handleMouseUp(): void {
    const current = drag;
    drag = null;
    window.removeEventListener("mousemove", handleMouseMove);
    window.removeEventListener("mouseup", handleMouseUp);
    renderDrag();
    if (!current) return;
    const rect = frame.getBoundingClientRect();
    const x0 = Math.min(current.startX, current.curX);
    const y0 = Math.min(current.startY, current.curY);
    const w = Math.abs(current.curX - current.startX);
    const h_ = Math.abs(current.curY - current.startY);
    if (w < 4 || h_ < 4) return; // versehentlichen Klick statt Ziehen ignorieren
    onDrawComplete(1, [x0 / rect.width, y0 / rect.height, w / rect.width, h_ / rect.height]);
  }

  function renderDrag(): void {
    if (!drag) {
      dragRect.style.display = "none";
      return;
    }
    dragRect.style.display = "";
    dragRect.style.left = `${Math.min(drag.startX, drag.curX)}px`;
    dragRect.style.top = `${Math.min(drag.startY, drag.curY)}px`;
    dragRect.style.width = `${Math.abs(drag.curX - drag.startX)}px`;
    dragRect.style.height = `${Math.abs(drag.curY - drag.startY)}px`;
  }

  function renderOverlay(activeField: ContractField | null): void {
    const showOverlay = activeField && activeField.bbox_x != null && activeField.bbox_y != null;
    if (!showOverlay || !activeField) {
      overlay.style.display = "none";
      return;
    }
    overlay.style.display = "";
    overlay.style.left = `${(activeField.bbox_x ?? 0) * 100}%`;
    overlay.style.top = `${(activeField.bbox_y ?? 0) * 100}%`;
    overlay.style.width = `${(activeField.bbox_w ?? 0) * 100}%`;
    overlay.style.height = `${(activeField.bbox_h ?? 0) * 100}%`;

    if (activeField.id !== lastScrolledFieldId) {
      lastScrolledFieldId = activeField.id;
      overlay.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function update(activeField: ContractField | null, drawingActive: boolean): void {
    currentDrawingActive = drawingActive;
    frame.className = drawingActive ? "image-viewer-frame drawing" : "image-viewer-frame";
    hint.style.display = drawingActive ? "" : "none";
    renderOverlay(activeField);
  }

  function destroy(): void {
    window.removeEventListener("mousemove", handleMouseMove);
    window.removeEventListener("mouseup", handleMouseUp);
  }

  return { el, update, destroy };
}
