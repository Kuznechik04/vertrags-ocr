import { cls, h } from "../lib/dom.js";
import type { ContractField } from "../types/document.js";

export interface FieldListHandlers {
  onSelect: (id: string) => void;
  onSave: (fieldId: string, value: string) => Promise<void>;
  onValidate: (fieldId: string) => Promise<void>;
  onStartDrawing: (fieldId: string) => void;
  onCancelDrawing: () => void;
}

export interface FieldListInstance {
  el: HTMLElement;
  render(fields: ContractField[], activeFieldId: string | null, drawingFieldId: string | null): void;
}

interface RowController {
  el: HTMLElement;
  update(field: ContractField, isActive: boolean, isDrawing: boolean): void;
}

/** Eine Zeile wird genau einmal pro Feld gebaut und danach nur noch
 * aktualisiert (nie neu erstellt) – so bleibt eine laufende, noch nicht
 * gespeicherte Eingabe in einer Zeile unangetastet, wenn eine ANDERE Zeile
 * gespeichert wird und der Server das komplette Dokument zurückgibt. Das
 * `<input>` wird nach dem Erstellen nie programmatisch überschrieben; der
 * Server-Wert (`final_value`) wird nur zur Anzeige (Badges, "dirty"-Check)
 * herangezogen, nie in den Eingabewert zurückgeschrieben. */
function createFieldRow(initialField: ContractField, handlers: FieldListHandlers): RowController {
  let saving = false;
  let currentField: ContractField = initialField;
  let currentIsDrawing = false;

  const labelEl = h("label", {}, initialField.field_label);
  const confidenceEl = h("span", { class: "confidence" });

  const input = h("input", {
    placeholder: "—",
    onclick: (e: Event) => e.stopPropagation(),
    oninput: () => renderActions(),
  }) as HTMLInputElement;
  input.value = initialField.final_value ?? "";

  const actionsEl = h("div", { class: "field-row-actions", onclick: (e: Event) => e.stopPropagation() });

  const row = h(
    "div",
    { onclick: () => handlers.onSelect(currentField.id) },
    h("div", { class: "field-row-header" }, labelEl, confidenceEl),
    input,
    actionsEl
  );

  function computeDirty(): boolean {
    return input.value !== (currentField.final_value ?? "");
  }

  async function handleSave(): Promise<void> {
    saving = true;
    renderActions();
    try {
      await handlers.onSave(currentField.id, input.value);
    } finally {
      saving = false;
      renderActions();
    }
  }

  function renderActions(): void {
    actionsEl.replaceChildren();
    if (currentIsDrawing) {
      actionsEl.append(
        h("span", { class: "drawing-badge" }, "Ziehe ein Rechteck im Dokument …"),
        h("button", { class: "link-btn", onclick: () => handlers.onCancelDrawing() }, "Abbrechen")
      );
      return;
    }

    const hasPosition = currentField.bbox_x != null && currentField.bbox_y != null;
    const dirty = computeDirty();

    actionsEl.append(
      h(
        "button",
        { class: "position-btn", onclick: () => handlers.onStartDrawing(currentField.id) },
        hasPosition ? "Position korrigieren" : "Position markieren"
      )
    );

    if (dirty) {
      actionsEl.append(
        h(
          "button",
          { class: "save-btn", disabled: saving, onclick: () => handleSave() },
          saving ? "Speichere …" : "Korrektur speichern"
        )
      );
    } else {
      actionsEl.append(
        h(
          "button",
          {
            class: "validate-btn",
            disabled: currentField.is_validated,
            onclick: () => handlers.onValidate(currentField.id),
          },
          currentField.is_validated ? "✓ Validiert" : "Als korrekt bestätigen"
        )
      );
    }
  }

  function update(field: ContractField, isActive: boolean, isDrawing: boolean): void {
    currentField = field;
    currentIsDrawing = isDrawing;
    row.className = cls("field-row", isActive && "active", field.is_validated && "validated", isDrawing && "drawing");
    labelEl.textContent = field.field_label;
    const confidenceLevel = field.confidence >= 0.8 ? "high" : field.confidence >= 0.4 ? "medium" : "low";
    confidenceEl.className = `confidence confidence-${confidenceLevel}`;
    confidenceEl.textContent = field.predicted_value ? `${Math.round(field.confidence * 100)}%` : "kein Wert erkannt";
    renderActions();
  }

  return { el: row, update };
}

export function createFieldList(handlers: FieldListHandlers): FieldListInstance {
  const el = h("div", { class: "field-list" });
  const controllers = new Map<string, RowController>();

  function render(fields: ContractField[], activeFieldId: string | null, drawingFieldId: string | null): void {
    const seen = new Set<string>();
    for (const field of fields) {
      seen.add(field.id);
      let controller = controllers.get(field.id);
      if (!controller) {
        controller = createFieldRow(field, handlers);
        controllers.set(field.id, controller);
      }
      controller.update(field, field.id === activeFieldId, field.id === drawingFieldId);
      el.appendChild(controller.el); // bestehenden Knoten an Ende verschieben (stabile Reihenfolge, kein Datenverlust)
    }
    for (const [id, controller] of controllers) {
      if (!seen.has(id)) {
        controller.el.remove();
        controllers.delete(id);
      }
    }
  }

  return { el, render };
}
