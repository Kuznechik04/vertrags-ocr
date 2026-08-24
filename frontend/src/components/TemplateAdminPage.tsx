import { useCallback, useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { ContractTemplate, TemplateField } from "../types/document";

type FieldValueType =
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

const VALUE_TYPE_OPTIONS: { value: FieldValueType; label: string }[] = [
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

const VALUE_PATTERNS: Record<Exclude<FieldValueType, "keins">, string> = {
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
function buildPattern(anchor: string, type: Exclude<FieldValueType, "keins">): string {
  const escaped = anchor.trim().toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return `${escaped}\\s*:?\\s*(${VALUE_PATTERNS[type]})`;
}

const UMLAUT_MAP: Record<string, string> = { ä: "ae", ö: "oe", ü: "ue", ß: "ss" };

/** Leitet einen technischen Feld-Key aus dem Anzeigenamen ab (z.B. "IBAN" ->
 * "iban", "E-Mail Adresse" -> "email_adresse"), damit man ihn im Normalfall
 * nicht mehr selbst eintippen muss. */
function slugify(text: string): string {
  const withoutUmlauts = text
    .toLowerCase()
    .replace(/[äöüß]/g, (c) => UMLAUT_MAP[c] ?? c);
  return withoutUmlauts
    .trim()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/** Löst die tatsächlich zu speichernden Muster auf: eigenes Regex (falls im
 * "Erweitert"-Bereich ausgefüllt) hat Vorrang vor der Preset-Auswahl. */
function resolvePatterns(
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

/** Gemeinsame Eingaben für Preset-Auswahl + optionales eigenes Regex, genutzt
 * beim Anlegen und beim Bearbeiten eines Feldes. */
function PatternTypeFields({
  valueType,
  setValueType,
  anchor,
  setAnchor,
  anchorPlaceholder,
  patternsText,
  setPatternsText,
  detailsOpen,
}: {
  valueType: FieldValueType;
  setValueType: (v: FieldValueType) => void;
  anchor: string;
  setAnchor: (v: string) => void;
  anchorPlaceholder: string;
  patternsText: string;
  setPatternsText: (v: string) => void;
  detailsOpen?: boolean;
}) {
  return (
    <>
      <div className="template-form-row">
        <label>
          Art des Werts
          <select
            value={valueType}
            onChange={(e) => {
              // Auswahl ändern setzt ein evtl. vorausgefülltes eigenes Regex
              // zurück – sonst würde die neue Auswahl von der Vorrang-Regel
              // unten (eigenes Regex schlägt Preset) stillschweigend ignoriert.
              setValueType(e.target.value as FieldValueType);
              setPatternsText("");
            }}
          >
            {VALUE_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        {valueType !== "keins" && (
          <label>
            Suchbegriff im Dokument (Standard: Anzeigename)
            <input
              value={anchor}
              onChange={(e) => setAnchor(e.target.value)}
              placeholder={anchorPlaceholder || "z.B. Mietobjekt"}
            />
          </label>
        )}
      </div>
      <details open={detailsOpen}>
        <summary>Erweitert: eigenes Regex-Muster</summary>
        <label>
          Regex-Muster (eins pro Zeile, überschreibt die Auswahl oben – nur für Sonderfälle nötig)
          <textarea
            value={patternsText}
            onChange={(e) => setPatternsText(e.target.value)}
            rows={2}
            placeholder={String.raw`mietobjekt\s*:?\s*([^\n\.]{3,80})`}
          />
        </label>
      </details>
    </>
  );
}

export default function TemplateAdminPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<ContractTemplate[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setTemplates(await api.listTemplates());
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (user?.role !== "admin") return <Navigate to="/" replace />;

  return (
    <div className="page">
      <button className="link-btn" onClick={() => navigate("/")}>
        ← Zurück zur Übersicht
      </button>
      <h2>Vertragstypen verwalten</h2>
      {error && <div className="error-banner">{error}</div>}

      <NewTemplateForm onCreated={load} onError={setError} />

      <div className="template-list">
        {templates.map((t) => (
          <TemplateCard key={t.id} template={t} onFieldAdded={load} onError={setError} />
        ))}
      </div>
    </div>
  );
}

function NewTemplateForm({
  onCreated,
  onError,
}: {
  onCreated: () => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onError(null);
    setSubmitting(true);
    try {
      await api.createTemplate(key.trim(), name.trim());
      setKey("");
      setName("");
      await onCreated();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Vertragstyp konnte nicht angelegt werden");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="template-form" onSubmit={handleSubmit}>
      <h3>Neuen Vertragstyp anlegen</h3>
      <div className="template-form-row">
        <label>
          Key
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="z.B. miete"
            required
          />
        </label>
        <label>
          Anzeigename
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="z.B. Mietvertrag"
            required
          />
        </label>
        <button className="primary-btn" type="submit" disabled={submitting}>
          {submitting ? "Anlegen …" : "Anlegen"}
        </button>
      </div>
    </form>
  );
}

function TemplateCard({
  template,
  onFieldAdded,
  onError,
}: {
  template: ContractTemplate;
  onFieldAdded: () => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const [showAddField, setShowAddField] = useState(false);
  const [editingFieldId, setEditingFieldId] = useState<string | null>(null);

  return (
    <div className="template-card">
      <div className="template-card-header">
        <div>
          <strong>{template.name}</strong>
          <span className="template-key">{template.key}</span>
        </div>
        <button
          className="secondary-btn"
          onClick={() => {
            setEditingFieldId(null);
            setShowAddField((v) => !v);
          }}
        >
          {showAddField ? "Abbrechen" : "+ Feld hinzufügen"}
        </button>
      </div>

      <ul className="template-field-list">
        {template.fields.map((f) => (
          <li key={f.id} className="template-field-row">
            <div className="template-field-row-main">
              <span className="field-key">{f.field_label}</span>
              <span className="field-subkey">{f.field_key}</span>
              <span className={`pattern-badge ${f.patterns && f.patterns.length > 0 ? "auto" : "manual"}`}>
                {f.patterns && f.patterns.length > 0
                  ? `${f.patterns.length} Muster`
                  : "keine Muster (nur manuell)"}
              </span>
              <button
                className="link-btn"
                onClick={() => {
                  setShowAddField(false);
                  setEditingFieldId((id) => (id === f.id ? null : f.id));
                }}
              >
                {editingFieldId === f.id ? "Abbrechen" : "Bearbeiten"}
              </button>
            </div>
            {editingFieldId === f.id && (
              <EditFieldForm
                templateId={template.id}
                field={f}
                onSaved={async () => {
                  setEditingFieldId(null);
                  await onFieldAdded();
                }}
                onError={onError}
              />
            )}
          </li>
        ))}
        {template.fields.length === 0 && <li className="empty">Noch keine Felder.</li>}
      </ul>

      {showAddField && (
        <AddFieldForm
          templateId={template.id}
          onAdded={async () => {
            setShowAddField(false);
            await onFieldAdded();
          }}
          onError={onError}
        />
      )}
    </div>
  );
}

function AddFieldForm({
  templateId,
  onAdded,
  onError,
}: {
  templateId: string;
  onAdded: () => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const [fieldKey, setFieldKey] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const [fieldLabel, setFieldLabel] = useState("");
  const [valueType, setValueType] = useState<FieldValueType>("freitext");
  const [anchor, setAnchor] = useState("");
  const [patternsText, setPatternsText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function handleLabelChange(value: string) {
    setFieldLabel(value);
    if (!keyTouched) setFieldKey(slugify(value));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onError(null);
    setSubmitting(true);
    try {
      const patterns = resolvePatterns(fieldLabel, valueType, anchor, patternsText);
      await api.addTemplateField(templateId, {
        field_key: fieldKey.trim(),
        field_label: fieldLabel.trim(),
        patterns,
      });
      setFieldKey("");
      setKeyTouched(false);
      setFieldLabel("");
      setValueType("freitext");
      setAnchor("");
      setPatternsText("");
      await onAdded();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Feld konnte nicht hinzugefügt werden");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="add-field-form" onSubmit={handleSubmit}>
      <div className="template-form-row">
        <label>
          Anzeigename
          <input
            value={fieldLabel}
            onChange={(e) => handleLabelChange(e.target.value)}
            placeholder="z.B. Mietobjekt"
            required
          />
        </label>
        <label>
          Feld-Key (automatisch, bei Bedarf änderbar)
          <input
            value={fieldKey}
            onChange={(e) => {
              setKeyTouched(true);
              setFieldKey(e.target.value);
            }}
            placeholder="wird aus dem Anzeigenamen abgeleitet"
            required
          />
        </label>
      </div>
      <PatternTypeFields
        valueType={valueType}
        setValueType={setValueType}
        anchor={anchor}
        setAnchor={setAnchor}
        anchorPlaceholder={fieldLabel}
        patternsText={patternsText}
        setPatternsText={setPatternsText}
      />
      <button className="primary-btn" type="submit" disabled={submitting}>
        {submitting ? "Speichere …" : "Feld hinzufügen"}
      </button>
    </form>
  );
}

function EditFieldForm({
  templateId,
  field,
  onSaved,
  onError,
}: {
  templateId: string;
  field: TemplateField;
  onSaved: () => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const [fieldLabel, setFieldLabel] = useState(field.field_label);
  const [valueType, setValueType] = useState<FieldValueType>(field.patterns?.length ? "freitext" : "keins");
  const [anchor, setAnchor] = useState("");
  // Bestehende Muster landen direkt im "Erweitert"-Feld (aufgeklappt), damit
  // man sieht/anpasst, was aktuell wirklich gespeichert ist, statt zu raten,
  // welcher Preset+Suchbegriff das ursprünglich erzeugt hat.
  const [patternsText, setPatternsText] = useState(field.patterns?.join("\n") ?? "");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onError(null);
    setSubmitting(true);
    try {
      const patterns = resolvePatterns(fieldLabel, valueType, anchor, patternsText);
      await api.updateTemplateField(templateId, field.id, {
        field_label: fieldLabel.trim(),
        patterns,
      });
      await onSaved();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Feld konnte nicht gespeichert werden");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="add-field-form" onSubmit={handleSubmit}>
      <div className="template-form-row">
        <label>
          Anzeigename
          <input value={fieldLabel} onChange={(e) => setFieldLabel(e.target.value)} required />
        </label>
      </div>
      <PatternTypeFields
        valueType={valueType}
        setValueType={setValueType}
        anchor={anchor}
        setAnchor={setAnchor}
        anchorPlaceholder={fieldLabel}
        patternsText={patternsText}
        setPatternsText={setPatternsText}
        detailsOpen
      />
      <button className="primary-btn" type="submit" disabled={submitting}>
        {submitting ? "Speichere …" : "Änderungen speichern"}
      </button>
    </form>
  );
}
