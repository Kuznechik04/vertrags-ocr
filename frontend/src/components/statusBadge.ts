import { h } from "../lib/dom.js";
import type { DocumentStatus } from "../types/document.js";

const LABELS: Record<DocumentStatus, string> = {
  uploaded: "Hochgeladen",
  processing: "Wird verarbeitet",
  needs_review: "Prüfung erforderlich",
  reviewed: "Geprüft",
  failed: "Fehlgeschlagen",
};

export function renderStatusBadge(status: DocumentStatus): HTMLElement {
  return h("span", { class: `status-badge status-${status}` }, LABELS[status]);
}
