import { api } from "../../api/client.js";
import { h } from "../../lib/dom.js";
import type { TemplateField } from "../../types/document.js";
import { createPatternTypeFields, resolvePatterns } from "./patternTypeFields.js";
import type { FieldValueType } from "./patternTypeFields.js";

export function createEditFieldForm(
  templateId: string,
  field: TemplateField,
  onSaved: () => Promise<void>,
  onError: (message: string | null) => void
): HTMLElement {
  let fieldLabel = field.field_label;

  const initialValueType: FieldValueType = field.patterns && field.patterns.length > 0 ? "freitext" : "keins";
  // Bestehende Muster landen direkt im "Erweitert"-Feld (aufgeklappt), damit
  // man sieht/anpasst, was aktuell wirklich gespeichert ist, statt zu raten,
  // welcher Preset+Suchbegriff das ursprünglich erzeugt hat.
  const patternFields = createPatternTypeFields({
    initialValueType,
    initialPatternsText: field.patterns?.join("\n") ?? "",
    anchorPlaceholder: fieldLabel,
    detailsOpen: true,
  });

  const fieldLabelInput = h("input", {
    required: true,
    oninput: (e: Event) => {
      fieldLabel = (e.target as HTMLInputElement).value;
      patternFields.setAnchorPlaceholder(fieldLabel);
    },
  }) as HTMLInputElement;
  fieldLabelInput.value = fieldLabel;

  const submitBtn = h("button", { class: "primary-btn", type: "submit" }, "Änderungen speichern");

  async function handleSubmit(e: Event): Promise<void> {
    e.preventDefault();
    onError(null);
    submitBtn.disabled = true;
    submitBtn.textContent = "Speichere …";
    try {
      const patterns = resolvePatterns(
        fieldLabel,
        patternFields.getValueType(),
        patternFields.getAnchor(),
        patternFields.getPatternsText()
      );
      await api.updateTemplateField(templateId, field.id, { field_label: fieldLabel.trim(), patterns });
      await onSaved();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Feld konnte nicht gespeichert werden");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Änderungen speichern";
    }
  }

  return h(
    "form",
    { class: "add-field-form", onsubmit: handleSubmit },
    h("div", { class: "template-form-row" }, h("label", {}, "Anzeigename", fieldLabelInput)),
    patternFields.el,
    submitBtn
  );
}
