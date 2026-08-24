import { useState } from "react";
import type { ContractField } from "../types/document";

interface Props {
  fields: ContractField[];
  activeFieldId: string | null;
  drawingFieldId: string | null;
  onSelect: (id: string) => void;
  onSave: (fieldId: string, value: string) => Promise<void>;
  onValidate: (fieldId: string) => Promise<void>;
  onStartDrawing: (fieldId: string) => void;
  onCancelDrawing: () => void;
}

export default function FieldList({
  fields,
  activeFieldId,
  drawingFieldId,
  onSelect,
  onSave,
  onValidate,
  onStartDrawing,
  onCancelDrawing,
}: Props) {
  return (
    <div className="field-list">
      {fields.map((field) => (
        <FieldRow
          key={field.id}
          field={field}
          isActive={field.id === activeFieldId}
          isDrawing={field.id === drawingFieldId}
          onSelect={() => onSelect(field.id)}
          onSave={(value) => onSave(field.id, value)}
          onValidate={() => onValidate(field.id)}
          onStartDrawing={() => onStartDrawing(field.id)}
          onCancelDrawing={onCancelDrawing}
        />
      ))}
    </div>
  );
}

function FieldRow({
  field,
  isActive,
  isDrawing,
  onSelect,
  onSave,
  onValidate,
  onStartDrawing,
  onCancelDrawing,
}: {
  field: ContractField;
  isActive: boolean;
  isDrawing: boolean;
  onSelect: () => void;
  onSave: (value: string) => Promise<void>;
  onValidate: () => Promise<void>;
  onStartDrawing: () => void;
  onCancelDrawing: () => void;
}) {
  const [value, setValue] = useState(field.final_value ?? "");
  const [saving, setSaving] = useState(false);
  const dirty = value !== (field.final_value ?? "");

  const confidenceLevel =
    field.confidence >= 0.8 ? "high" : field.confidence >= 0.4 ? "medium" : "low";
  const hasPosition = field.bbox_x != null && field.bbox_y != null;

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(value);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className={`field-row ${isActive ? "active" : ""} ${field.is_validated ? "validated" : ""} ${
        isDrawing ? "drawing" : ""
      }`}
      onClick={onSelect}
    >
      <div className="field-row-header">
        <label>{field.field_label}</label>
        <span className={`confidence confidence-${confidenceLevel}`}>
          {field.predicted_value ? `${Math.round(field.confidence * 100)}%` : "kein Wert erkannt"}
        </span>
      </div>
      <input
        value={value}
        placeholder="—"
        onChange={(e) => setValue(e.target.value)}
        onClick={(e) => e.stopPropagation()}
      />
      <div className="field-row-actions" onClick={(e) => e.stopPropagation()}>
        {isDrawing ? (
          <>
            <span className="drawing-badge">Ziehe ein Rechteck im Dokument …</span>
            <button className="link-btn" onClick={onCancelDrawing}>
              Abbrechen
            </button>
          </>
        ) : (
          <>
            <button className="position-btn" onClick={onStartDrawing}>
              {hasPosition ? "Position korrigieren" : "Position markieren"}
            </button>
            {dirty ? (
              <button className="save-btn" disabled={saving} onClick={handleSave}>
                {saving ? "Speichere …" : "Korrektur speichern"}
              </button>
            ) : (
              <button className="validate-btn" disabled={field.is_validated} onClick={onValidate}>
                {field.is_validated ? "✓ Validiert" : "Als korrekt bestätigen"}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
