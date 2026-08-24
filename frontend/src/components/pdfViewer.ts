import { getToken } from "../api/tokenStore.js";
import { h } from "../lib/dom.js";
import { pdfjsLib } from "../lib/pdfjs.js";
import type { ContractField } from "../types/document.js";
import type { ViewerInstance } from "./imageViewer.js";

interface PageSize {
  width: number;
  height: number;
}

interface DragState {
  page: number;
  startX: number;
  startY: number;
  curX: number;
  curY: number;
}

/** Rendert alle Seiten eines PDFs (via pdf.js) auf <canvas>-Elemente, mit
 * bbox-Overlay + Klick+Ziehen-Zeichenmodus pro Seite. Wird pro Dokument
 * einmal erstellt (asynchrones Laden + Rendern der Seiten läuft einmalig)
 * und danach nur per `update()` weitergereicht. */
export function createPdfViewer(
  fileUrl: string,
  onDrawComplete: (page: number, bbox: [number, number, number, number]) => void
): ViewerInstance {
  let cancelled = false;
  let drag: DragState | null = null;
  let currentDrawingActive = false;
  let lastScrollKey: string | null = null;

  const pageWrappers = new Map<number, HTMLDivElement>();
  const pageOverlays = new Map<number, HTMLDivElement>();
  const pageDragRects = new Map<number, HTMLDivElement>();
  const pageSizes = new Map<number, PageSize>();

  const hint = h("div", { class: "drawing-hint" }, "Ziehe mit der Maus ein Rechteck über die richtige Textstelle.");
  hint.style.display = "none";
  const loadingHint = h("div", { class: "preview-hint" }, "Lade PDF …");
  const errorSlot = h("div", {});
  const pagesSlot = h("div", {});

  const container = h("div", { class: "pdf-scroll" }, hint, loadingHint, errorSlot, pagesSlot) as HTMLDivElement;

  function handleMouseDown(page: number, e: MouseEvent): void {
    if (!currentDrawingActive) return;
    e.preventDefault();
    const wrapper = pageWrappers.get(page);
    if (!wrapper) return;
    const rect = wrapper.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    drag = { page, startX: x, startY: y, curX: x, curY: y };
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    renderDrag();
  }

  function handleMouseMove(e: MouseEvent): void {
    if (!drag) return;
    const wrapper = pageWrappers.get(drag.page);
    if (!wrapper) return;
    const rect = wrapper.getBoundingClientRect();
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
    const size = pageSizes.get(current.page);
    if (!size) return;
    const x0 = Math.min(current.startX, current.curX);
    const y0 = Math.min(current.startY, current.curY);
    const w = Math.abs(current.curX - current.startX);
    const h_ = Math.abs(current.curY - current.startY);
    if (w < 4 || h_ < 4) return; // versehentlichen Klick statt Ziehen ignorieren
    onDrawComplete(current.page, [x0 / size.width, y0 / size.height, w / size.width, h_ / size.height]);
  }

  function renderDrag(): void {
    for (const [page, dragRect] of pageDragRects) {
      if (drag && drag.page === page) {
        dragRect.style.display = "";
        dragRect.style.left = `${Math.min(drag.startX, drag.curX)}px`;
        dragRect.style.top = `${Math.min(drag.startY, drag.curY)}px`;
        dragRect.style.width = `${Math.abs(drag.curX - drag.startX)}px`;
        dragRect.style.height = `${Math.abs(drag.curY - drag.startY)}px`;
      } else {
        dragRect.style.display = "none";
      }
    }
  }

  let lastActiveField: ContractField | null = null;

  function renderOverlays(): void {
    const activeField = lastActiveField;
    for (const [page, overlay] of pageOverlays) {
      const size = pageSizes.get(page);
      const show =
        activeField != null && activeField.bbox_x != null && activeField.bbox_y != null && size != null && activeField.page === page;
      if (!show || !activeField || !size) {
        overlay.style.display = "none";
        continue;
      }
      overlay.style.display = "";
      overlay.style.left = `${(activeField.bbox_x ?? 0) * size.width}px`;
      overlay.style.top = `${(activeField.bbox_y ?? 0) * size.height}px`;
      overlay.style.width = `${(activeField.bbox_w ?? 0) * size.width}px`;
      overlay.style.height = `${(activeField.bbox_h ?? 0) * size.height}px`;
    }

    if (activeField && activeField.bbox_x != null) {
      const scrollKey = `${activeField.id}:${activeField.page}:${activeField.bbox_x}`;
      if (scrollKey !== lastScrollKey) {
        lastScrollKey = scrollKey;
        pageWrappers.get(activeField.page)?.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }

  async function load(): Promise<void> {
    try {
      const token = getToken();
      const loadingTask = pdfjsLib.getDocument({
        url: fileUrl,
        httpHeaders: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      const pdf = await loadingTask.promise;
      if (cancelled) return;

      const containerWidth = container.clientWidth || 800;

      for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
        if (cancelled) return;
        const page = await pdf.getPage(pageNumber);
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = containerWidth / baseViewport.width;
        const viewport = page.getViewport({ scale });

        const overlay = h("div", { class: "bbox-overlay" }) as HTMLDivElement;
        overlay.style.display = "none";
        const dragRect = h("div", { class: "bbox-drawing" }) as HTMLDivElement;
        dragRect.style.display = "none";

        const canvas = document.createElement("canvas");
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.className = "pdf-page-canvas";

        const wrapper = h(
          "div",
          { class: "pdf-page-wrapper", onmousedown: (e: MouseEvent) => handleMouseDown(pageNumber, e) },
          canvas,
          overlay,
          dragRect
        ) as HTMLDivElement;

        const ctx = canvas.getContext("2d");
        if (ctx) {
          await page.render({ canvasContext: ctx, viewport }).promise;
        }
        if (cancelled) return;

        pageWrappers.set(pageNumber, wrapper);
        pageOverlays.set(pageNumber, overlay);
        pageDragRects.set(pageNumber, dragRect);
        pageSizes.set(pageNumber, { width: viewport.width, height: viewport.height });
        pagesSlot.appendChild(wrapper);
      }

      loadingHint.remove();
      renderOverlays();
    } catch (err) {
      if (cancelled) return;
      loadingHint.remove();
      errorSlot.appendChild(
        h("div", { class: "error-banner" }, err instanceof Error ? err.message : "PDF konnte nicht geladen werden")
      );
    }
  }

  function update(activeField: ContractField | null, drawingActive: boolean): void {
    lastActiveField = activeField;
    currentDrawingActive = drawingActive;
    container.className = drawingActive ? "pdf-scroll drawing" : "pdf-scroll";
    hint.style.display = drawingActive ? "" : "none";
    renderOverlays();
  }

  function destroy(): void {
    cancelled = true;
    window.removeEventListener("mousemove", handleMouseMove);
    window.removeEventListener("mouseup", handleMouseUp);
  }

  load();

  return { el: container, update, destroy };
}
