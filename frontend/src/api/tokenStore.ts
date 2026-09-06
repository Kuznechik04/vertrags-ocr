/** Der Session-Token selbst liegt nicht mehr hier (bzw. in localStorage) -
 * er lebt als httpOnly-Cookie, das der Browser automatisch mitschickt und
 * das JS gar nicht erst lesen kann (schützt vor Diebstahl per XSS). Dieses
 * Modul übernimmt zwei kleinere, verwandte Aufgaben:
 * 1. Das CSRF-Cookie auslesen (bewusst NICHT httpOnly), damit client.ts es
 *    als `X-CSRF-Token`-Header auf verändernde Requests zurückschicken kann
 *    (Double-Submit-Cookie-Pattern, siehe backend/app/main.py CSRFMiddleware).
 * 2. Anderen Modulen (allen voran authStore.ts) signalisieren, wenn der
 *    Server einen Request mit 401 abgelehnt hat, die Session also nicht
 *    mehr gültig ist. */
const CSRF_COOKIE_NAME = "csrf_token";

const listeners = new Set<() => void>();

export function getCsrfToken(): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE_NAME}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function notifyUnauthenticated(): void {
  listeners.forEach((listener) => listener());
}

export function onUnauthenticated(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
