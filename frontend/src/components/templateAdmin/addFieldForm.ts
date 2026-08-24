import { api } from "../../api/client.js";
import { h } from "../../lib/dom.js";
import { createPatternTypeFields, resolvePatterns, slugify } from "./patternTypeFields.js";

export function createAddFieldForm(
  templateId: string,
  onAdded: () => Promise<void>,
  onError: (message: string | null) => void
): HTMLElement {
  let fieldKey = "";
  let keyTouched = false;
  let fieldLabel = "";

  const patternFields = createPatternTypeFields({ initialValueType: "freitext", anchorPlaceholder: "" });

  const fieldKeyInput = h("input", {
    placeholder: "wird aus dem Anzeigenamen abgeleitet",
    required: true,
    oninput: (e: Event) => {
      keyTouched = true;
      fieldKey = (e.target as HTMLInputElement).value;
    },
  }) as HTMLInputElement;

  const fieldLabelInput = h("input", {
    placeholder: "z.B. Mietobjekt",
    required: true,
    oninput: (e: Event) => {
      fieldLabel = (e.target as HTMLInputElement).value;
      if (!keyTouched) {
        fieldKey = slugify(fieldLabel);
        fieldKeyInput.value = fieldKey;
      }
      patternFields.setAnchorPlaceholder(fieldLabel);
    },
  }) as HTMLInputElement;

  const submitBtn = h("button", { class: "primary-btn", type: "submit" }, "Feld hinzufügen");

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
      await api.addTemplateField(templateId, { field_key: fieldKey.trim(), field_label: fieldLabel.trim(), patterns });
      fieldKey = "";
      keyTouched = false;
      fieldLabel = "";
      fieldKeyInput.value = "";
      fieldLabelInput.value = "";
      patternFields.reset("freitext");
      await onAdded();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Feld konnte nicht hinzugefügt werden");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Feld hinzufügen";
    }
  }

  return h(
    "form",
    { class: "add-field-form", onsubmit: handleSubmit },
    h(
      "div",
      { class: "template-form-row" },
      h("label", {}, "Anzeigename", fieldLabelInput),
      h("label", {}, "Feld-Key (automatisch, bei Bedarf änderbar)", fieldKeyInput)
    ),
    patternFields.el,
    submitBtn
  );
}
