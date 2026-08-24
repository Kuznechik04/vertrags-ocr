import type { DocumentStatus } from "../types/document";

const LABELS: Record<DocumentStatus, string> = {
  uploaded: "Hochgeladen",
  processing: "Wird verarbeitet",
  needs_review: "Prüfung erforderlich",
  reviewed: "Geprüft",
  failed: "Fehlgeschlagen",
};

export default function StatusBadge({ status }: { status: DocumentStatus }) {
  return <span className={`status-badge status-${status}`}>{LABELS[status]}</span>;
}
