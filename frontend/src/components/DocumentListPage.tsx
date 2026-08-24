import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { ContractTemplate, DocumentSummary } from "../types/document";
import StatusBadge from "./StatusBadge";

export default function DocumentListPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [templates, setTemplates] = useState<ContractTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setDocuments(await api.listDocuments());
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    api.listTemplates().then((loaded) => {
      setTemplates(loaded);
      const preferred = loaded.find((t) => t.key === "versicherung") ?? loaded[0];
      if (preferred) setSelectedTemplateId(preferred.id);
    });
  }, []);

  async function handleUpload(files: FileList | null) {
    if (!files || files.length === 0) return;
    if (!selectedTemplateId) {
      setError("Kein Vertragstyp verfügbar – Upload nicht möglich.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        await api.uploadDocument(file, selectedTemplateId);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload fehlgeschlagen");
    } finally {
      setLoading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function handleDelete(id: string, evt: React.MouseEvent) {
    evt.stopPropagation();
    if (!confirm("Dokument wirklich löschen?")) return;
    await api.deleteDocument(id);
    await load();
  }

  async function handleExportAll() {
    setError(null);
    setExporting(true);
    try {
      await api.exportAllXlsx();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export fehlgeschlagen");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="page">
      <div className="list-toolbar">
        {isAdmin && (
          <div className="admin-hint">
            Admin-Ansicht: Du siehst die Verträge aller Nutzer.
          </div>
        )}
        <div className="spacer" />
        <button
          className="secondary-btn"
          disabled={exporting || documents.length === 0}
          onClick={handleExportAll}
        >
          {exporting ? "Exportiere …" : "Alle als Excel exportieren"}
        </button>
      </div>

      <div className="upload-toolbar">
        <label htmlFor="template-select">Vertragstyp</label>
        <select
          id="template-select"
          value={selectedTemplateId}
          onChange={(e) => setSelectedTemplateId(e.target.value)}
          onClick={(e) => e.stopPropagation()}
        >
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </div>

      <div
        className="dropzone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          handleUpload(e.dataTransfer.files);
        }}
        onClick={() => fileInput.current?.click()}
      >
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg"
          multiple
          hidden
          onChange={(e) => handleUpload(e.target.files)}
        />
        {loading ? "Verarbeite Upload …" : "Vertrag(e) hierher ziehen oder klicken zum Hochladen"}
      </div>
      {error && <div className="error-banner">{error}</div>}

      <table className="doc-table">
        <thead>
          <tr>
            <th>Datei</th>
            {isAdmin && <th>Hochgeladen von</th>}
            <th>Status</th>
            <th>Hochgeladen</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => (
            <tr key={doc.id} onClick={() => navigate(`/documents/${doc.id}`)}>
              <td>{doc.filename}</td>
              {isAdmin && <td>{doc.owner_email ?? doc.owner_id}</td>}
              <td>
                <StatusBadge status={doc.status} />
              </td>
              <td>{new Date(doc.uploaded_at).toLocaleString("de-DE")}</td>
              <td>
                <button className="link-btn" onClick={(e) => handleDelete(doc.id, e)}>
                  Löschen
                </button>
              </td>
            </tr>
          ))}
          {documents.length === 0 && (
            <tr>
              <td colSpan={isAdmin ? 5 : 4} className="empty">
                Noch keine Verträge hochgeladen.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
