import { api } from "../../api/client.js";
import { h } from "../../lib/dom.js";
import type { FieldMatchStatus } from "../../types/document.js";

export type FieldValueType =
  | "freitext"
  | "datum"
  | "betrag"
  | "zahl"
  | "iban"
  | "email"
  | "telefon"
  | "plz"
  | "kennung"
  | "prozent"
  | "zeitraum"
  | "keins";

export const VALUE_TYPE_OPTIONS: { value: FieldValueType; label: string }[] = [
  { value: "freitext", label: "Freitext" },
  { value: "datum", label: "Datum (TT.MM.JJJJ)" },
  { value: "betrag", label: "Betrag (z.B. 99,00 €)" },
  { value: "zahl", label: "Zahl" },
  { value: "iban", label: "IBAN" },
  { value: "email", label: "E-Mail" },
  { value: "telefon", label: "Telefonnummer" },
  { value: "plz", label: "PLZ" },
  { value: "kennung", label: "Kennung/Code (z.B. Steuernummer, Kundennummer)" },
  { value: "prozent", label: "Prozentsatz" },
  { value: "zeitraum", label: "Zeitraum/Dauer (z.B. 3 Monate)" },
  { value: "keins", label: "Kein automatisches Muster (nur manuell ausfüllen)" },
];

export const VALUE_PATTERNS: Record<Exclude<FieldValueType, "keins">, string> = {
  freitext: String.raw`[^\n\.]{3,80}`,
  datum: String.raw`\d{1,2}\.\d{1,2}\.\d{2,4}`,
  betrag: String.raw`[\d\.,]+\s?(?:€|eur|euro)`,
  zahl: String.raw`\d+(?:[.,]\d+)?`,
  // Ländercode + Prüfziffer + Kontokennung, mit optionalen Leerzeichen alle
  // 4 Zeichen (übliche IBAN-Schreibweise) – bewusst enger als "Freitext",
  // damit nicht versehentlich der Text nach der IBAN mit erfasst wird.
  iban: String.raw`[A-Za-z]{2}\d{2}(?:\s?[A-Za-z0-9]{4}){2,6}(?:\s?[A-Za-z0-9]{1,4})?`,
  email: String.raw`[\w.+-]+@[\w-]+\.[a-z]{2,}`,
  telefon: String.raw`\+?\d[\d\s/()-]{5,20}\d`,
  plz: String.raw`\d{5}`,
  // Alphanumerische Kennungen wie Steuernummer/Kundennummer/Rechnungsnr. –
  // gleiches Muster wie das bisherige, fest codierte Versicherungsnummer-Feld.
  kennung: String.raw`[A-Za-z0-9\-\/]+`,
  prozent: String.raw`\d+(?:[.,]\d+)?\s?%`,
  zeitraum: String.raw`\d+\s*(?:Tage?|Wochen?|Monate?|Jahre?)`,
};

/** Baut aus einem Suchbegriff + Werttyp ein Regex-Muster, damit Admins ohne
 * Regex-Kenntnisse automatische Erkennung konfigurieren können. Folgt exakt
 * dem Schema der bestehenden Muster (siehe `backend/app/main.py`, z.B.
 * `kuendigungsfrist\s*:?\s*([^\n\.]{3,40})`). */
export function buildPattern(anchor: string, type: Exclude<FieldValueType, "keins">): string {
  const escaped = anchor.trim().toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return `${escaped}\\s*:?\\s*(${VALUE_PATTERNS[type]})`;
}

const UMLAUT_MAP: Record<string, string> = { ä: "ae", ö: "oe", ü: "ue", ß: "ss" };

/** Leitet einen technischen Feld-Key aus dem Anzeigenamen ab (z.B. "IBAN" ->
 * "iban", "E-Mail Adresse" -> "email_adresse"), damit man ihn im Normalfall
 * nicht mehr selbst eintippen muss. */
export function slugify(text: string): string {
  const withoutUmlauts = text.toLowerCase().replace(/[äöüß]/g, (c) => UMLAUT_MAP[c] ?? c);
  return withoutUmlauts
    .trim()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/** Löst die tatsächlich zu speichernden Muster auf: eigenes Regex (falls im
 * "Erweitert"-Bereich ausgefüllt) hat Vorrang vor der Preset-Auswahl. */
export function resolvePatterns(
  fallbackAnchor: string,
  valueType: FieldValueType,
  anchor: string,
  patternsText: string
): string[] | null {
  const customPatterns = patternsText
    .split("\n")
    .map((p) => p.trim())
    .filter(Boolean);
  if (customPatterns.length > 0) return customPatterns;
  if (valueType === "keins") return null;
  return [buildPattern(anchor.trim() || fallbackAnchor.trim(), valueType)];
}

function describeMatch(status: FieldMatchStatus, value: string | null, confidence: number): string {
  switch (status) {
    case "matched":
      return `Treffer: „${value}“ (${Math.round(confidence * 100)}%)`;
    case "data_not_found":
      return "Suchbegriff gefunden, aber kein Wert erkannt.";
    case "field_not_found":
      return "Nicht gefunden.";
    case "no_pattern":
      return "Kein automatisches Muster ausgewählt – nichts zu testen.";
  }
}

export interface PatternTypeFieldsInstance {
  el: HTMLElement;
  getValueType(): FieldValueType;
  getAnchor(): string;
  getPatternsText(): string;
  setAnchorPlaceholder(text: string): void;
  reset(valueType: FieldValueType): void;
}

/** Gemeinsame Eingaben für Preset-Auswahl + optionales eigenes Regex, genutzt
 * von addFieldForm.ts und editFieldForm.ts. Hält Wert-Typ/Suchbegriff/eigene
 * Muster als eigenen State (Getter statt kontrollierter Props). */
export function createPatternTypeFields(opts: {
  initialValueType: FieldValueType;
  initialPatternsText?: string;
  anchorPlaceholder: string;
  detailsOpen?: boolean;
  /** Anzeigename des Feldes, als Fallback-Suchbegriff für `resolvePatterns`
   * beim "Muster testen" (dieselbe Logik wie beim tatsächlichen Speichern). */
  getFallbackAnchor?: () => string;
}): PatternTypeFieldsInstance {
  let valueType = opts.initialValueType;
  let anchor = "";
  let patternsText = opts.initialPatternsText ?? "";

  const anchorInput = h("input", {
    placeholder: opts.anchorPlaceholder || "z.B. Mietobjekt",
    oninput: (e: Event) => {
      anchor = (e.target as HTMLInputElement).value;
    },
  }) as HTMLInputElement;

  const anchorLabel = h("label", {}, "Suchbegriff im Dokument (Standard: Anzeigename)", anchorInput);
  anchorLabel.style.display = valueType === "keins" ? "none" : "";

  const patternsTextarea = h("textarea", {
    rows: 2,
    placeholder: String.raw`mietobjekt\s*:?\s*([^\n\.]{3,80})`,
    oninput: (e: Event) => {
      patternsText = (e.target as HTMLTextAreaElement).value;
    },
  }) as HTMLTextAreaElement;
  patternsTextarea.value = patternsText;

  const select = h(
    "select",
    {
      onchange: (e: Event) => {
        valueType = (e.target as HTMLSelectElement).value as FieldValueType;
        patternsText = "";
        patternsTextarea.value = "";
        anchorLabel.style.display = valueType === "keins" ? "none" : "";
      },
    },
    VALUE_TYPE_OPTIONS.map((opt) => h("option", { value: opt.value }, opt.label))
  ) as HTMLSelectElement;
  select.value = valueType;

  const details = h(
    "details",
    { open: opts.detailsOpen ?? false },
    h("summary", {}, "Erweitert: eigenes Regex-Muster"),
    h(
      "label",
      {},
      "Regex-Muster (eins pro Zeile, überschreibt die Auswahl oben – nur für Sonderfälle nötig)",
      patternsTextarea
    )
  );

  // "Muster testen": schließt den bisher fehlenden Vorschau-Loop beim
  // Anlegen/Bearbeiten von Feldern - vorher gab es keine Rückmeldung, ob ein
  // Muster funktioniert, außer echte Verträge hochzuladen und die Review-UI
  // zu prüfen.
  const testFileInput = h("input", { type: "file", accept: ".pdf,.png,.jpg,.jpeg" }) as HTMLInputElement;
  const testResultEl = h("span", { class: "pattern-test-result" });

  async function handleTest(): Promise<void> {
    const file = testFileInput.files?.[0];
    if (!file) {
      testResultEl.className = "pattern-test-result pattern-test-error";
      testResultEl.textContent = "Bitte zuerst eine Testdatei auswählen.";
      return;
    }

    const patterns = resolvePatterns(opts.getFallbackAnchor?.() ?? "", valueType, anchor, patternsText);
    if (!patterns) {
      testResultEl.className = "pattern-test-result pattern-test-no_pattern";
      testResultEl.textContent = describeMatch("no_pattern", null, 0);
      return;
    }

    testBtn.disabled = true;
    testResultEl.className = "pattern-test-result";
    testResultEl.textContent = "Teste …";
    try {
      const result = await api.previewPattern(file, patterns);
      testResultEl.className = `pattern-test-result pattern-test-${result.match_status}`;
      testResultEl.textContent = describeMatch(result.match_status, result.value, result.confidence);
    } catch (err) {
      testResultEl.className = "pattern-test-result pattern-test-error";
      testResultEl.textContent = err instanceof Error ? err.message : "Test fehlgeschlagen";
    } finally {
      testBtn.disabled = false;
    }
  }

  const testBtn = h(
    "button",
    { type: "button", class: "secondary-btn", onclick: handleTest },
    "Muster testen"
  ) as HTMLButtonElement;

  const testRow = h(
    "div",
    { class: "pattern-test-row" },
    h("label", {}, "Testdatei", testFileInput),
    testBtn,
    testResultEl
  );

  const el = h(
    "div",
    {},
    h("div", { class: "template-form-row" }, h("label", {}, "Art des Werts", select), anchorLabel),
    details,
    testRow
  );

  return {
    el,
    getValueType: () => valueType,
    getAnchor: () => anchor,
    getPatternsText: () => patternsText,
    setAnchorPlaceholder(text: string) {
      anchorInput.placeholder = text || "z.B. Mietobjekt";
    },
    reset(newValueType: FieldValueType) {
      valueType = newValueType;
      anchor = "";
      patternsText = "";
      select.value = valueType;
      anchorInput.value = "";
      patternsTextarea.value = "";
      anchorLabel.style.display = valueType === "keins" ? "none" : "";
    },
  };
}
