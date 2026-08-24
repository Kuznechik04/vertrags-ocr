import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { pdfjsLib } from "../lib/pdfjs";
import { getToken } from "../api/tokenStore";
import type { ContractField } from "../types/document";

interface Props {
  fileUrl: string;
  activeField: ContractField | null;
  /** Wenn true: Klick+Ziehen auf einer Seite meldet die Auswahl über `onDrawComplete`,
   * statt nur zur aktiven Fundstelle zu scrollen. */
  drawingActive: boolean;
  onDrawComplete: (page: number, bbox: [number, number, number, number]) => void;
}

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

/**
 * Rendert alle Seiten eines PDFs (via pdf.js) auf <canvas>-Elemente statt es
 * per <iframe> dem systemeigenen PDF-Viewer zu überlassen. Nur so lässt sich
 * die Fundstelle eines Feldes exakt markieren und automatisch dorthin
 * scrollen – ein <iframe> gibt uns keine Kontrolle über Zoom/Scroll-Position
 * des eingebetteten Viewers. Im "drawingActive"-Modus kann der Nutzer außerdem
 * per Klick+Ziehen selbst ein Rechteck über die tatsächliche Fundstelle eines
 * (ggf. nicht erkannten) Feldes ziehen.
 */
export default function PdfViewer({ fileUrl, activeField, drawingActive, onDrawComplete }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const pdfRef = useRef<PDFDocumentProxy | null>(null);

  const [numPages, setNumPages] = useState<number | null>(null);
  const [pageSizes, setPageSizes] = useState<Record<number, PageSize>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [drag, setDrag] = useState<DragState | null>(null);
  const dragRef = useRef<DragState | null>(null);
  useEffect(() => {
    dragRef.current = drag;
  }, [drag]);

  // Stufe 1: Dokument laden und Seitenzahl ermitteln
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setNumPages(null);
    setPageSizes({});
    pageRefs.current = {};

    async function load() {
      try {
        const token = getToken();
        const loadingTask = pdfjsLib.getDocument({
          url: fileUrl,
          httpHeaders: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        const pdf = await loadingTask.promise;
        if (cancelled) return;
        pdfRef.current = pdf;
        setNumPages(pdf.numPages);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "PDF konnte nicht geladen werden");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [fileUrl]);

  // Stufe 2: sobald die Seiten-Wrapper im DOM sind (numPages bekannt), jede
  // Seite auf ein Canvas rendern.
  useEffect(() => {
    if (!numPages || !pdfRef.current) return;
    let cancelled = false;

    async function renderPages() {
      const pdf = pdfRef.current!;
      const containerWidth = containerRef.current?.clientWidth ?? 800;
      const sizes: Record<number, PageSize> = {};

      for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
        if (cancelled) return;
        const page = await pdf.getPage(pageNumber);
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = containerWidth / baseViewport.width;
        const viewport = page.getViewport({ scale });

        const wrapper = pageRefs.current[pageNumber];
        if (!wrapper) continue;

        const canvas = document.createElement("canvas");
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.className = "pdf-page-canvas";
        const context = canvas.getContext("2d");
        if (!context) continue;

        wrapper.innerHTML = "";
        wrapper.appendChild(canvas);

        await page.render({ canvasContext: context, viewport }).promise;
        if (cancelled) return;
        sizes[pageNumber] = { width: viewport.width, height: viewport.height };
      }

      if (!cancelled) setPageSizes(sizes);
    }

    renderPages();
    return () => {
      cancelled = true;
    };
  }, [numPages]);

  // Springt automatisch zur Seite der aktuell ausgewählten Feld-Fundstelle.
  useEffect(() => {
    if (!activeField || activeField.bbox_x == null) return;
    const wrapper = pageRefs.current[activeField.page];
    wrapper?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activeField?.id, activeField?.page, activeField?.bbox_x]);

  // Maus-Handling für den Zeichenmodus: global lauschen, damit Ziehen auch
  // funktioniert, wenn der Mauszeiger kurz die Seite verlässt.
  useEffect(() => {
    if (!drawingActive) return;

    function handleMove(e: MouseEvent) {
      const current = dragRef.current;
      if (!current) return;
      const wrapper = pageRefs.current[current.page];
      if (!wrapper) return;
      const rect = wrapper.getBoundingClientRect();
      const x = Math.min(Math.max(e.clientX - rect.left, 0), rect.width);
      const y = Math.min(Math.max(e.clientY - rect.top, 0), rect.height);
      setDrag({ ...current, curX: x, curY: y });
    }

    function handleUp() {
      const current = dragRef.current;
      setDrag(null);
      if (!current) return;
      const size = pageSizes[current.page];
      if (!size) return;

      const x0 = Math.min(current.startX, current.curX);
      const y0 = Math.min(current.startY, current.curY);
      const w = Math.abs(current.curX - current.startX);
      const h = Math.abs(current.curY - current.startY);
      if (w < 4 || h < 4) return; // versehentlichen Klick statt Ziehen ignorieren

      onDrawComplete(current.page, [x0 / size.width, y0 / size.height, w / size.width, h / size.height]);
    }

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
  }, [drawingActive, pageSizes, onDrawComplete]);

  function handleMouseDown(pageNumber: number, e: React.MouseEvent) {
    if (!drawingActive) return;
    e.preventDefault();
    const wrapper = pageRefs.current[pageNumber];
    if (!wrapper) return;
    const rect = wrapper.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setDrag({ page: pageNumber, startX: x, startY: y, curX: x, curY: y });
  }

  const activeSize = activeField ? pageSizes[activeField.page] : undefined;
  const showOverlay =
    activeField && activeField.bbox_x != null && activeField.bbox_y != null && activeSize;

  return (
    <div className={`pdf-scroll ${drawingActive ? "drawing" : ""}`} ref={containerRef}>
      {loading && <div className="preview-hint">Lade PDF …</div>}
      {error && <div className="error-banner">{error}</div>}
      {drawingActive && (
        <div className="drawing-hint">Ziehe mit der Maus ein Rechteck über die richtige Textstelle.</div>
      )}
      {numPages &&
        Array.from({ length: numPages }, (_, i) => i + 1).map((pageNumber) => (
          <div
            key={pageNumber}
            className="pdf-page-wrapper"
            ref={(el) => {
              pageRefs.current[pageNumber] = el;
            }}
            onMouseDown={(e) => handleMouseDown(pageNumber, e)}
          >
            {showOverlay && activeField!.page === pageNumber && (
              <div
                className="bbox-overlay"
                style={{
                  left: `${(activeField!.bbox_x ?? 0) * activeSize!.width}px`,
                  top: `${(activeField!.bbox_y ?? 0) * activeSize!.height}px`,
                  width: `${(activeField!.bbox_w ?? 0) * activeSize!.width}px`,
                  height: `${(activeField!.bbox_h ?? 0) * activeSize!.height}px`,
                }}
              />
            )}
            {drag && drag.page === pageNumber && (
              <div
                className="bbox-drawing"
                style={{
                  left: `${Math.min(drag.startX, drag.curX)}px`,
                  top: `${Math.min(drag.startY, drag.curY)}px`,
                  width: `${Math.abs(drag.curX - drag.startX)}px`,
                  height: `${Math.abs(drag.curY - drag.startY)}px`,
                }}
              />
            )}
          </div>
        ))}
    </div>
  );
}
