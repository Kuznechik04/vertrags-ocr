import { api } from "../api/client.js";
import { createAddFieldForm } from "../components/templateAdmin/addFieldForm.js";
import { createEditFieldForm } from "../components/templateAdmin/editFieldForm.js";
import { h } from "../lib/dom.js";
import { navigate } from "../lib/router.js";
import type { ContractTemplate } from "../types/document.js";

interface TemplateCardController {
  el: HTMLElement;
  update(template: ContractTemplate): void;
}

/** Wie components/fieldList.ts: offene Add-/Edit-Formulare werden bei einem
 * Reload (ausgelöst durch eine ANDERE Karte oder ein ANDERES Feld) wieder-
 * verwendet statt neu gebaut, damit dort laufende, noch nicht gespeicherte
 * Eingaben nicht verloren gehen. */
function createTemplateCard(
  initial: ContractTemplate,
  onFieldAdded: () => Promise<void>,
  onError: (message: string | null) => void
): TemplateCardController {
  let current = initial;
  let showAddField = false;
  let editingFieldId: string | null = null;
  let lastShowAddField = false;
  let lastEditingFieldId: string | null = null;
  let addFormEl: HTMLElement | null = null;
  let editFormEl: HTMLElement | null = null;

  const nameEl = h("strong", {}, current.name);
  const keyEl = h("span", { class: "template-key" }, current.key);
  const fieldListEl = h("ul", { class: "template-field-list" });
  const addFieldSlot = h("div", {});

  const toggleAddBtn = h(
    "button",
    {
      class: "secondary-btn",
      onclick: () => {
        editingFieldId = null;
        showAddField = !showAddField;
        renderToggleState();
      },
    },
    "+ Feld hinzufügen"
  );

  const card = h(
    "div",
    { class: "template-card" },
    h("div", { class: "template-card-header" }, h("div", {}, nameEl, keyEl), toggleAddBtn),
    fieldListEl,
    addFieldSlot
  );

  function renderFieldList(): void {
    fieldListEl.replaceChildren();
    if (current.fields.length === 0) {
      fieldListEl.appendChild(h("li", { class: "empty" }, "Noch keine Felder."));
    }
    for (const f of current.fields) {
      const isEditing = editingFieldId === f.id;
      const editBtn = h(
        "button",
        {
          class: "link-btn",
          onclick: () => {
            showAddField = false;
            editingFieldId = editingFieldId === f.id ? null : f.id;
            renderToggleState();
          },
        },
        isEditing ? "Abbrechen" : "Bearbeiten"
      );

      let formNode: HTMLElement | null = null;
      if (isEditing) {
        if (editingFieldId === lastEditingFieldId && editFormEl) {
          formNode = editFormEl;
        } else {
          editFormEl = createEditFieldForm(
            current.id,
            f,
            async () => {
              editingFieldId = null;
              lastEditingFieldId = null;
              editFormEl = null;
              await onFieldAdded();
            },
            onError
          );
          formNode = editFormEl;
        }
      }

      fieldListEl.appendChild(
        h(
          "li",
          { class: "template-field-row" },
          h(
            "div",
            { class: "template-field-row-main" },
            h("span", { class: "field-key" }, f.field_label),
            h("span", { class: "field-subkey" }, f.field_key),
            h(
              "span",
              { class: `pattern-badge ${f.patterns && f.patterns.length > 0 ? "auto" : "manual"}` },
              f.patterns && f.patterns.length > 0 ? `${f.patterns.length} Muster` : "keine Muster (nur manuell)"
            ),
            editBtn
          ),
          formNode
        )
      );
    }
    lastEditingFieldId = editingFieldId;
  }

  function renderAddFieldSlot(): void {
    if (showAddField) {
      if (!(lastShowAddField && addFormEl)) {
        addFormEl = createAddFieldForm(
          current.id,
          async () => {
            showAddField = false;
            lastShowAddField = false;
            addFormEl = null;
            await onFieldAdded();
          },
          onError
        );
      }
      addFieldSlot.replaceChildren(addFormEl);
    } else {
      addFieldSlot.replaceChildren();
      addFormEl = null;
    }
    lastShowAddField = showAddField;
  }

  function renderToggleState(): void {
    toggleAddBtn.textContent = showAddField ? "Abbrechen" : "+ Feld hinzufügen";
    renderFieldList();
    renderAddFieldSlot();
  }

  function update(template: ContractTemplate): void {
    current = template;
    nameEl.textContent = current.name;
    keyEl.textContent = current.key;
    renderToggleState();
  }

  update(initial);
  return { el: card, update };
}

function createNewTemplateForm(onCreated: () => Promise<void>, onError: (message: string | null) => void): HTMLElement {
  let key = "";
  let name = "";

  const keyInput = h("input", {
    placeholder: "z.B. miete",
    required: true,
    oninput: (e: Event) => {
      key = (e.target as HTMLInputElement).value;
    },
  }) as HTMLInputElement;
  const nameInput = h("input", {
    placeholder: "z.B. Mietvertrag",
    required: true,
    oninput: (e: Event) => {
      name = (e.target as HTMLInputElement).value;
    },
  }) as HTMLInputElement;
  const submitBtn = h("button", { class: "primary-btn", type: "submit" }, "Anlegen");

  async function handleSubmit(e: Event): Promise<void> {
    e.preventDefault();
    onError(null);
    submitBtn.disabled = true;
    submitBtn.textContent = "Anlegen …";
    try {
      await api.createTemplate(key.trim(), name.trim());
      key = "";
      name = "";
      keyInput.value = "";
      nameInput.value = "";
      await onCreated();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Vertragstyp konnte nicht angelegt werden");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Anlegen";
    }
  }

  return h(
    "form",
    { class: "template-form", onsubmit: handleSubmit },
    h("h3", {}, "Neuen Vertragstyp anlegen"),
    h(
      "div",
      { class: "template-form-row" },
      h("label", {}, "Key", keyInput),
      h("label", {}, "Anzeigename", nameInput),
      submitBtn
    )
  );
}

export function renderTemplateAdminPage(container: HTMLElement): void {
  const cards = new Map<string, TemplateCardController>();

  const errorSlot = h("div", {});
  const listSlot = h("div", { class: "template-list" });
  const newFormSlot = h("div", {});

  const page = h(
    "div",
    { class: "page" },
    h("button", { class: "link-btn", onclick: () => navigate("/") }, "← Zurück zur Übersicht"),
    h("h2", {}, "Vertragstypen verwalten"),
    errorSlot,
    newFormSlot,
    listSlot
  );
  container.appendChild(page);

  function setError(message: string | null): void {
    errorSlot.replaceChildren();
    if (message) errorSlot.appendChild(h("div", { class: "error-banner" }, message));
  }

  async function load(): Promise<void> {
    const templates = await api.listTemplates();
    const seen = new Set<string>();
    for (const t of templates) {
      seen.add(t.id);
      let card = cards.get(t.id);
      if (!card) {
        card = createTemplateCard(t, load, setError);
        cards.set(t.id, card);
      } else {
        card.update(t);
      }
      listSlot.appendChild(card.el);
    }
    for (const [id, card] of cards) {
      if (!seen.has(id)) {
        card.el.remove();
        cards.delete(id);
      }
    }
  }

  newFormSlot.appendChild(createNewTemplateForm(load, setError));
  load();
}
