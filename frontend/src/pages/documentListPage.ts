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
  let pendingFiles: File[] | null = null;
  let suggesting = false;
  let suggestionHint: string | null = null;

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

  /** Wird ausgelöst, sobald Dateien gewählt wurden (Datei-Dialog oder Drop) -
   * lädt noch NICHT direkt hoch, sondern holt zuerst einen
   * Vertragstyp-Vorschlag anhand des Dokumentinhalts (reiner Vorschlag, das
   * Dropdown bleibt änderbar) und wartet auf den expliziten
   * "Hochladen"-Klick. Vorher wurde beim Auswählen sofort mit dem zuletzt
   * eingestellten Dropdown-Wert hochgeladen - ein falsch stehen gebliebener
   * Vertragstyp führte dann zu stiller Fehlextraktion. */
  async function handleFilesChosen(files: FileList | null): Promise<void> {
    if (!files || files.length === 0) return;
    pendingFiles = Array.from(files);
    suggestionHint = null;
    error = null;
    suggesting = true;
    rerender();
    try {
      const suggestions = await api.suggestTemplate(pendingFiles[0]);
      const best = suggestions[0];
      if (best && best.score > 0) {
        selectedTemplateId = best.template_id;
        suggestionHint = `Vorschlag: „${best.template_name}“ (basierend auf Dokumentinhalt) – bei Bedarf oben ändern.`;
      }
    } catch {
      // Der Vorschlag ist nur ein Komfort-Feature - schlägt er fehl (z.B.
      // Datei nicht lesbar), einfach ohne Vorschlag weitermachen; die
      // eigentliche Fehlerbehandlung passiert beim tatsächlichen Upload.
    } finally {
      suggesting = false;
      rerender();
    }
  }

  function handleCancelPending(): void {
    pendingFiles = null;
    suggestionHint = null;
    rerender();
  }

  async function handleUploadClick(): Promise<void> {
    if (!pendingFiles || pendingFiles.length === 0) return;
    if (!selectedTemplateId) {
      error = "Kein Vertragstyp verfügbar – Upload nicht möglich.";
      rerender();
      return;
    }
    loading = true;
    error = null;
    rerender();
    try {
      for (const file of pendingFiles) {
        await api.uploadDocument(file, selectedTemplateId);
      }
      await loadDocuments();
      pendingFiles = null;
      suggestionHint = null;
    } catch (err) {
      error = err instanceof Error ? err.message : "Upload fehlgeschlagen";
    } finally {
      loading = false;
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
      onchange: (e: Event) => handleFilesChosen((e.target as HTMLInputElement).files),
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
            handleFilesChosen(e.dataTransfer?.files ?? null);
          },
          onclick: () => fileInput.click(),
        },
        fileInput,
        loading ? "Lade hoch …" : "Vertrag(e) hierher ziehen oder klicken zum Auswählen"
      ),
      pendingFiles
        ? h(
            "div",
            { class: "pending-upload" },
            h(
              "span",
              {},
              `${pendingFiles.length} Datei(en) ausgewählt${suggesting ? " – prüfe Vertragstyp …" : ""}`
            ),
            suggestionHint ? h("span", { class: "suggestion-hint" }, suggestionHint) : null,
            h(
              "button",
              { class: "primary-btn", disabled: loading || suggesting, onclick: () => handleUploadClick() },
              loading ? "Lade hoch …" : "Hochladen"
            ),
            h(
              "button",
              { class: "link-btn", disabled: loading, onclick: () => handleCancelPending() },
              "Abbrechen"
            )
          )
        : null,
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
