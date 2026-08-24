import { api } from "../api/client.js";
import { createDocumentPreview } from "../components/documentPreview.js";
import { createFieldList } from "../components/fieldList.js";
import { renderStatusBadge } from "../components/statusBadge.js";
import { h, mount } from "../lib/dom.js";
import { navigate } from "../lib/router.js";
import type { RouteContext, Teardown } from "../lib/router.js";
import type { DocumentDetail } from "../types/document.js";

export function renderDocumentReviewPage(container: HTMLElement, ctx: RouteContext): Teardown {
  const id = ctx.params.id;

  let doc: DocumentDetail | null = null;
  let activeFieldId: string | null = null;
  let drawingFieldId: string | null = null;
  let finalizeError: string | null = null;
  let exportError: string | null = null;
  let exporting = false;
  let preview: ReturnType<typeof createDocumentPreview> | null = null;

  const fieldList = createFieldList({
    onSelect: (fid) => {
      activeFieldId = fid;
      updateBody();
    },
    onSave: async (fid, value) => {
      doc = await api.updateField(id, fid, { corrected_value: value });
      updateAll();
    },
    onValidate: async (fid) => {
      doc = await api.updateField(id, fid, { is_validated: true });
      updateAll();
    },
    onStartDrawing: (fid) => {
      drawingFieldId = fid;
      updateBody();
    },
    onCancelDrawing: () => {
      drawingFieldId = null;
      updateBody();
    },
  });

  const loadingEl = h("div", { class: "page" }, "Lade Dokument …");
  container.appendChild(loadingEl);

  const toolbarSlot = h("div", { class: "review-toolbar" });
  const errorSlot = h("div", {});
  const bodySlot = h("div", { class: "review-body" });
  const page = h("div", { class: "page review-page" }, toolbarSlot, errorSlot, bodySlot);

  async function handleDrawComplete(pageNumber: number, bbox: [number, number, number, number]): Promise<void> {
    if (!drawingFieldId) return;
    const fieldId = drawingFieldId;
    const [bbox_x, bbox_y, bbox_w, bbox_h] = bbox;
    drawingFieldId = null;
    doc = await api.updateField(id, fieldId, { page: pageNumber, bbox_x, bbox_y, bbox_w, bbox_h });
    activeFieldId = fieldId;
    updateAll();
  }

  async function load(): Promise<void> {
    doc = await api.getDocument(id);
    preview = createDocumentPreview(doc, handleDrawComplete);
    bodySlot.append(preview.el, fieldList.el);
    mount(container, page);
    updateAll();
  }

  function updateAll(): void {
    updateToolbar();
    updateBody();
  }

  function updateToolbar(): void {
    if (!doc) return;
    const validatedCount = doc.fields.filter((f) => f.is_validated).length;
    const allValidated = validatedCount === doc.fields.length;

    toolbarSlot.replaceChildren(
      h("button", { class: "link-btn", onclick: () => navigate("/") }, "← Zurück zur Übersicht"),
      h("h2", {}, doc.filename),
      renderStatusBadge(doc.status),
      h("div", { class: "spacer" }),
      h("span", { class: "progress-label" }, `${validatedCount}/${doc.fields.length} Felder validiert`),
      h(
        "button",
        { class: "secondary-btn", disabled: exporting, onclick: () => handleExport() },
        exporting ? "Exportiere …" : "Als Excel exportieren"
      ),
      h(
        "button",
        {
          class: "primary-btn",
          disabled: !allValidated || doc.status === "reviewed",
          onclick: () => handleFinalize(),
        },
        doc.status === "reviewed" ? "Abgeschlossen" : "Prüfung abschließen"
      )
    );

    errorSlot.replaceChildren();
    if (finalizeError) errorSlot.appendChild(h("div", { class: "error-banner" }, finalizeError));
    if (exportError) errorSlot.appendChild(h("div", { class: "error-banner" }, exportError));
  }

  function updateBody(): void {
    if (!doc || !preview) return;
    preview.update(doc, activeFieldId, drawingFieldId);
    fieldList.render(doc.fields, activeFieldId, drawingFieldId);
  }

  async function handleFinalize(): Promise<void> {
    finalizeError = null;
    try {
      doc = await api.finalizeDocument(id);
      updateAll();
    } catch (err) {
      finalizeError = err instanceof Error ? err.message : "Fehler beim Abschließen";
      updateToolbar();
    }
  }

  async function handleExport(): Promise<void> {
    if (!doc) return;
    exportError = null;
    exporting = true;
    updateToolbar();
    try {
      const base = doc.filename.replace(/\.[^.]+$/, "") || "vertrag";
      await api.exportDocumentXlsx(id, `${base}.xlsx`);
    } catch (err) {
      exportError = err instanceof Error ? err.message : "Export fehlgeschlagen";
    } finally {
      exporting = false;
      updateToolbar();
    }
  }

  load();

  return () => {
    preview?.destroy();
  };
}
