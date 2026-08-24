const STORAGE_KEY = "vertrags_ocr_token";

let token: string | null = localStorage.getItem(STORAGE_KEY);
const listeners = new Set<(token: string | null) => void>();

export function getToken(): string | null {
  return token;
}

export function setToken(next: string | null) {
  token = next;
  if (next) {
    localStorage.setItem(STORAGE_KEY, next);
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
  listeners.forEach((listener) => listener(token));
}

export function onTokenChange(listener: (token: string | null) => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
