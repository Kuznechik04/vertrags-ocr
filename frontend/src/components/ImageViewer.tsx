import { useEffect, useRef, useState } from "react";
import type { ContractField } from "../types/document";

interface Props {
  fileUrl: string;
  alt: string;
  activeField: ContractField | null;
  drawingActive: boolean;
  onDrawComplete: (page: number, bbox: [number, number, number, number]) => void;
}

interface DragState {
  startX: number;
  startY: number;
  curX: number;
  curY: number;
}

/**
 * Zeigt ein hochgeladenes Bild (statt PDF) an. Das Bild wird immer auf volle
 * Containerbreite skaliert (`width: 100%; height: auto`) statt mit
 * `object-fit: contain` in eine feste Box gepresst zu werden – so entsteht
 * kein Letterboxing, und die Bounding-Box-Prozentwerte des Modells lassen
 * sich 1:1 als CSS-Prozentwerte auf das Overlay übertragen. Im
 * "drawingActive"-Modus kann der Nutzer per Klick+Ziehen selbst ein Rechteck
 * über die tatsächliche Fundstelle eines Feldes markieren.
 */
export default function ImageViewer({ fileUrl, alt, activeField, drawingActive, onDrawComplete }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);

  const [drag, setDrag] = useState<DragState | null>(null);
  const dragRef = useRef<DragState | null>(null);
  useEffect(() => {
    dragRef.current = drag;
  }, [drag]);

  const showOverlay =
    activeField && activeField.bbox_x != null && activeField.bbox_y != null;

  useEffect(() => {
    if (showOverlay) {
      overlayRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeField?.id]);

  useEffect(() => {
    if (!drawingActive) return;

    function handleMove(e: MouseEvent) {
      if (!dragRef.current) return;
      const frame = frameRef.current;
      if (!frame) return;
      const rect = frame.getBoundingClientRect();
      const x = Math.min(Math.max(e.clientX - rect.left, 0), rect.width);
      const y = Math.min(Math.max(e.clientY - rect.top, 0), rect.height);
      setDrag((prev) => (prev ? { ...prev, curX: x, curY: y } : prev));
    }

    function handleUp() {
      const current = dragRef.current;
      setDrag(null);
      const frame = frameRef.current;
      if (!current || !frame) return;
      const rect = frame.getBoundingClientRect();

      const x0 = Math.min(current.startX, current.curX);
      const y0 = Math.min(current.startY, current.curY);
      const w = Math.abs(current.curX - current.startX);
      const h = Math.abs(current.curY - current.startY);
      if (w < 4 || h < 4) return; // versehentlichen Klick statt Ziehen ignorieren

      onDrawComplete(1, [x0 / rect.width, y0 / rect.height, w / rect.width, h / rect.height]);
    }

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
  }, [drawingActive, onDrawComplete]);

  function handleMouseDown(e: React.MouseEvent) {
    if (!drawingActive) return;
    e.preventDefault();
    const frame = frameRef.current;
    if (!frame) return;
    const rect = frame.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setDrag({ startX: x, startY: y, curX: x, curY: y });
  }

  return (
    <div className="image-viewer-scroll">
      {drawingActive && (
        <div className="drawing-hint">Ziehe mit der Maus ein Rechteck über die richtige Textstelle.</div>
      )}
      <div
        className={`image-viewer-frame ${drawingActive ? "drawing" : ""}`}
        ref={frameRef}
        onMouseDown={handleMouseDown}
      >
        <img src={fileUrl} alt={alt} draggable={false} />
        {showOverlay && (
          <div
            ref={overlayRef}
            className="bbox-overlay"
            style={{
              left: `${(activeField!.bbox_x ?? 0) * 100}%`,
              top: `${(activeField!.bbox_y ?? 0) * 100}%`,
              width: `${(activeField!.bbox_w ?? 0) * 100}%`,
              height: `${(activeField!.bbox_h ?? 0) * 100}%`,
            }}
          />
        )}
        {drag && (
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
    </div>
  );
}
