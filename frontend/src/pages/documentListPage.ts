import { api } from "../api/client.js";
import { getState } from "../auth/authStore.js";
import { renderStatusBadge } from "../components/statusBadge.js";
import { h, mount } from "../lib/dom.js";
import { navigate } from "../lib/router.js";
import type { ContractTemplate, DocumentSummary } from "../types/document.js";

export function renderDocumentListPage(container: HTMLElement): void {
  const isAdmin = getState().user?.role === "admin";

  let documents: DocumentSummary[] = [];
  let templates: ContractTemplate[] = [];
  let selectedTemplateId = "";
  let loading = false;
  let error: string | null = null;
  let exporting = false;

  const page = h("div", { class: "page" });
  container.appendChild(page);

  async function loadDocuments(): Promise<void> {
    documents = await api.listDocuments();
    rerender();
  }

  async function loadTemplates(): Promise<void> {
    templates = await api.listTemplates();
    const preferred = templates.find((t) => t.key === "versicherung") ?? templates[0];
    if (preferred) selectedTemplateId = preferred.id;
    rerender();
  }

  async function handleUpload(files: FileList | null, fileInput: HTMLInputElement): Promise<void> {
    if (!files || files.length === 0) return;
    if (!selectedTemplateId) {
      error = "Kein Vertragstyp verfügbar – Upload nicht möglich.";
      rerender();
      return;
    }
    loading = true;
    error = null;
    rerender();
    try {
      for (const file of Array.from(files)) {
        await api.uploadDocument(file, selectedTemplateId);
      }
      await loadDocuments();
    } catch (err) {
      error = err instanceof Error ? err.message : "Upload fehlgeschlagen";
    } finally {
      loading = false;
      fileInput.value = "";
      rerender();
    }
  }

  async function handleDelete(id: string, evt: Event): Promise<void> {
    evt.stopPropagation();
    if (!confirm("Dokument wirklich löschen?")) return;
    await api.deleteDocument(id);
    await loadDocuments();
  }

  async function handleExportAll(): Promise<void> {
    error = null;
    exporting = true;
    rerender();
    try {
      await api.exportAllXlsx();
    } catch (err) {
      error = err instanceof Error ? err.message : "Export fehlgeschlagen";
    } finally {
      exporting = false;
      rerender();
    }
  }

  function rerender(): void {
    const fileInput = h("input", {
      type: "file",
      accept: ".pdf,.png,.jpg,.jpeg",
      multiple: true,
      hidden: true,
      onchange: (e: Event) => handleUpload((e.target as HTMLInputElement).files, e.target as HTMLInputElement),
    }) as HTMLInputElement;

    const templateSelect = h(
      "select",
      {
        id: "template-select",
        onchange: (e: Event) => {
          selectedTemplateId = (e.target as HTMLSelectElement).value;
        },
        onclick: (e: Event) => e.stopPropagation(),
      },
      templates.map((t) => h("option", { value: t.id }, t.name))
    ) as HTMLSelectElement;
    templateSelect.value = selectedTemplateId;

    const node = h(
      "div",
      {},
      h(
        "div",
        { class: "list-toolbar" },
        isAdmin ? h("div", { class: "admin-hint" }, "Admin-Ansicht: Du siehst die Verträge aller Nutzer.") : null,
        h("div", { class: "spacer" }),
        h(
          "button",
          {
            class: "secondary-btn",
            disabled: exporting || documents.length === 0,
            onclick: handleExportAll,
          },
          exporting ? "Exportiere …" : "Alle als Excel exportieren"
        )
      ),
      h("div", { class: "upload-toolbar" }, h("label", { for: "template-select" }, "Vertragstyp"), templateSelect),
      h(
        "div",
        {
          class: "dropzone",
          ondragover: (e: Event) => e.preventDefault(),
          ondrop: (e: DragEvent) => {
            e.preventDefault();
            handleUpload(e.dataTransfer?.files ?? null, fileInput);
          },
          onclick: () => fileInput.click(),
        },
        fileInput,
        loading ? "Verarbeite Upload …" : "Vertrag(e) hierher ziehen oder klicken zum Hochladen"
      ),
      error ? h("div", { class: "error-banner" }, error) : null,
      h(
        "table",
        { class: "doc-table" },
        h(
          "thead",
          {},
          h(
            "tr",
            {},
            h("th", {}, "Datei"),
            isAdmin ? h("th", {}, "Hochgeladen von") : null,
            h("th", {}, "Status"),
            h("th", {}, "Hochgeladen"),
            h("th", {})
          )
        ),
        h(
          "tbody",
          {},
          documents.map((doc) =>
            h(
              "tr",
              { onclick: () => navigate(`/documents/${doc.id}`) },
              h("td", {}, doc.filename),
              isAdmin ? h("td", {}, doc.owner_email ?? doc.owner_id) : null,
              h("td", {}, renderStatusBadge(doc.status)),
              h("td", {}, new Date(doc.uploaded_at).toLocaleString("de-DE")),
              h(
                "td",
                {},
                h("button", { class: "link-btn", onclick: (e: Event) => handleDelete(doc.id, e) }, "Löschen")
              )
            )
          ),
          documents.length === 0
            ? h("tr", {}, h("td", { colSpan: isAdmin ? 5 : 4, class: "empty" }, "Noch keine Verträge hochgeladen."))
            : null
        )
      )
    );

    mount(page, node);
  }

  rerender();
  loadDocuments();
  loadTemplates();
}
