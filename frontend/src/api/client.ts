import type { ContractTemplate, DocumentDetail, DocumentSummary } from "../types/document";
import type { AuthResponse, CurrentUser } from "../types/auth";
import { getToken, setToken } from "./tokenStore";

// Basis-URL für das Backend; in der HTML-Datei kann sie per window.__APP_CONFIG__
// gesetzt werden. So wird kein Vite-Env-Setup mehr benötigt.
const BASE_URL = window.__APP_CONFIG__?.apiBaseUrl ?? "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (!(options?.body instanceof FormData) && !(options?.body instanceof URLSearchParams)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers: { ...headers, ...options?.headers } });

  if (res.status === 401) {
    // Token ist abgelaufen/ungültig -> Nutzer muss sich neu anmelden
    setToken(null);
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `Fehler ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Lädt eine Datei (z.B. Excel-Export) authentifiziert herunter und stößt den
 * Browser-Download an – ein einfacher `<a href>` würde den Authorization-Header
 * nicht mitschicken können. */
async function downloadFile(path: string, fallbackFilename: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });

  if (res.status === 401) {
    setToken(null);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `Fehler ${res.status}`);
  }

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition");
  const match = disposition?.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] ?? fallbackFilename;

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  register: (email: string, password: string) =>
    request<AuthResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  login: (email: string, password: string) => {
    const form = new URLSearchParams();
    form.set("username", email);
    form.set("password", password);
    return request<AuthResponse>("/api/auth/login", { method: "POST", body: form });
  },

  me: () => request<CurrentUser>("/api/auth/me"),

  listDocuments: () => request<DocumentSummary[]>("/api/documents"),

  getDocument: (id: string) => request<DocumentDetail>(`/api/documents/${id}`),

  listTemplates: () => request<ContractTemplate[]>("/api/templates"),

  createTemplate: (key: string, name: string) =>
    request<ContractTemplate>("/api/templates", {
      method: "POST",
      body: JSON.stringify({ key, name }),
    }),

  addTemplateField: (
    templateId: string,
    payload: { field_key: string; field_label: string; patterns: string[] | null }
  ) =>
    request<ContractTemplate>(`/api/templates/${templateId}/fields`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateTemplateField: (
    templateId: string,
    fieldId: string,
    payload: { field_label: string; patterns: string[] | null }
  ) =>
    request<ContractTemplate>(`/api/templates/${templateId}/fields/${fieldId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  uploadDocument: (file: File, templateId: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("template_id", templateId);
    return request<DocumentDetail>("/api/documents/upload", { method: "POST", body: form });
  },

  fileUrl: (id: string) => {
    const token = getToken();
    return `${BASE_URL}/api/documents/${id}/file${token ? `?token=${encodeURIComponent(token)}` : ""}`;
  },

  updateField: (
    documentId: string,
    fieldId: string,
    payload: {
      corrected_value?: string;
      is_validated?: boolean;
      page?: number;
      bbox_x?: number;
      bbox_y?: number;
      bbox_w?: number;
      bbox_h?: number;
    }
  ) =>
    request<DocumentDetail>(`/api/documents/${documentId}/fields/${fieldId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  finalizeDocument: (id: string) =>
    request<DocumentDetail>(`/api/documents/${id}/finalize`, { method: "POST" }),

  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),

  exportDocumentXlsx: (id: string, filename: string) =>
    downloadFile(`/api/documents/${id}/export/xlsx`, filename),

  exportAllXlsx: () => downloadFile("/api/documents/export/xlsx", "vertraege_export.xlsx"),
};
