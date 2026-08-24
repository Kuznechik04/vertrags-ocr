import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { DocumentDetail } from "../types/document";
import DocumentPreview from "./DocumentPreview";
import FieldList from "./FieldList";
import StatusBadge from "./StatusBadge";

export default function DocumentReviewPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [activeFieldId, setActiveFieldId] = useState<string | null>(null);
  const [drawingFieldId, setDrawingFieldId] = useState<string | null>(null);
  const [finalizeError, setFinalizeError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setDoc(await api.getDocument(id));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (!doc) return <div className="page">Lade Dokument …</div>;

  const validatedCount = doc.fields.filter((f) => f.is_validated).length;
  const allValidated = validatedCount === doc.fields.length;

  async function handleFieldSave(fieldId: string, correctedValue: string) {
    if (!id) return;
    const updated = await api.updateField(id, fieldId, { corrected_value: correctedValue });
    setDoc(updated);
  }

  async function handleValidate(fieldId: string) {
    if (!id) return;
    const updated = await api.updateField(id, fieldId, { is_validated: true });
    setDoc(updated);
  }

  async function handleDrawComplete(page: number, bbox: [number, number, number, number]) {
    if (!id || !drawingFieldId) return;
    const [bbox_x, bbox_y, bbox_w, bbox_h] = bbox;
    const fieldId = drawingFieldId;
    setDrawingFieldId(null);
    const updated = await api.updateField(id, fieldId, { page, bbox_x, bbox_y, bbox_w, bbox_h });
    setDoc(updated);
    setActiveFieldId(fieldId);
  }

  async function handleFinalize() {
    if (!id) return;
    setFinalizeError(null);
    try {
      const updated = await api.finalizeDocument(id);
      setDoc(updated);
    } catch (err) {
      setFinalizeError(err instanceof Error ? err.message : "Fehler beim Abschließen");
    }
  }

  async function handleExport() {
    if (!id || !doc) return;
    setExportError(null);
    setExporting(true);
    try {
      const base = doc.filename.replace(/\.[^.]+$/, "") || "vertrag";
      await api.exportDocumentXlsx(id, `${base}.xlsx`);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Export fehlgeschlagen");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="page review-page">
      <div className="review-toolbar">
        <button className="link-btn" onClick={() => navigate("/")}>
          ← Zurück zur Übersicht
        </button>
        <h2>{doc.filename}</h2>
        <StatusBadge status={doc.status} />
        <div className="spacer" />
        <span className="progress-label">
          {validatedCount}/{doc.fields.length} Felder validiert
        </span>
        <button className="secondary-btn" disabled={exporting} onClick={handleExport}>
          {exporting ? "Exportiere …" : "Als Excel exportieren"}
        </button>
        <button className="primary-btn" disabled={!allValidated || doc.status === "reviewed"} onClick={handleFinalize}>
          {doc.status === "reviewed" ? "Abgeschlossen" : "Prüfung abschließen"}
        </button>
      </div>
      {finalizeError && <div className="error-banner">{finalizeError}</div>}
      {exportError && <div className="error-banner">{exportError}</div>}

      <div className="review-body">
        <DocumentPreview
          document={doc}
          activeFieldId={activeFieldId}
          drawingFieldId={drawingFieldId}
          onDrawComplete={handleDrawComplete}
        />
        <FieldList
          fields={doc.fields}
          activeFieldId={activeFieldId}
          drawingFieldId={drawingFieldId}
          onSelect={setActiveFieldId}
          onSave={handleFieldSave}
          onValidate={handleValidate}
          onStartDrawing={setDrawingFieldId}
          onCancelDrawing={() => setDrawingFieldId(null)}
        />
      </div>
    </div>
  );
}
