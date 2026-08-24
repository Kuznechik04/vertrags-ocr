import { api } from "../api/client";
import type { ContractField, DocumentDetail } from "../types/document";
import ImageViewer from "./ImageViewer";
import PdfViewer from "./PdfViewer";

interface Props {
  document: DocumentDetail;
  activeFieldId: string | null;
  /** Feld, für das der Nutzer gerade per Klick+Ziehen eine Position markiert
   * (siehe FieldList "Position markieren/korrigieren"). `null` = kein Zeichenmodus. */
  drawingFieldId: string | null;
  onDrawComplete: (page: number, bbox: [number, number, number, number]) => void;
}

/**
 * Zeigt das hochgeladene Dokument an. Für Felder mit Bounding-Box-Koordinaten
 * wird bei Auswahl automatisch zur Fundstelle gescrollt und ein Rahmen darum
 * gezeichnet (PDF-Seiten werden dafür über pdf.js auf <canvas> gerendert,
 * damit wir die exakte Scroll-Position und Overlay-Position kontrollieren
 * können – ein <iframe> mit dem systemeigenen PDF-Viewer erlaubt das nicht).
 * Liefert das aktive OCR-Backend keine Position (z.B. das Mock-Backend bei
 * ungetroffenen Feldern), erscheint einfach kein Rahmen – der Nutzer kann die
 * Position dann über den Zeichenmodus selbst markieren.
 */
export default function DocumentPreview({ document, activeFieldId, drawingFieldId, onDrawComplete }: Props) {
  const activeField: ContractField | null =
    document.fields.find((f) => f.id === (drawingFieldId ?? activeFieldId)) ?? null;
  const hasPosition = activeField && activeField.bbox_x != null && activeField.bbox_y != null;

  const isImage = document.content_type.startsWith("image/");
  const fileUrl = api.fileUrl(document.id);
  const drawingActive = drawingFieldId != null;

  return (
    <div className="document-preview">
      {isImage ? (
        <ImageViewer
          fileUrl={fileUrl}
          alt={document.filename}
          activeField={drawingActive ? null : activeField}
          drawingActive={drawingActive}
          onDrawComplete={onDrawComplete}
        />
      ) : (
        <PdfViewer
          fileUrl={fileUrl}
          activeField={drawingActive ? null : activeField}
          drawingActive={drawingActive}
          onDrawComplete={onDrawComplete}
        />
      )}
      {!drawingActive && activeField && !hasPosition && (
        <p className="preview-hint">
          Keine Positionsangabe für dieses Feld verfügbar. Über „Position markieren“ in der
          Feldliste kannst du sie selbst im Dokument einzeichnen.
        </p>
      )}
    </div>
  );
}
