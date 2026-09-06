/** Pub-Sub-Store als Ersatz für den bisherigen React-Context. */
import { api } from "../api/client.js";
import { onUnauthenticated } from "../api/tokenStore.js";
import type { CurrentUser } from "../types/auth.js";

export interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
}

let state: AuthState = { user: null, loading: true };
const listeners = new Set<(state: AuthState) => void>();

function setState(patch: Partial<AuthState>): void {
  state = { ...state, ...patch };
  listeners.forEach((listener) => listener(state));
}

export function getState(): AuthState {
  return state;
}

export function subscribe(listener: (state: AuthState) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function refreshUser(): Promise<void> {
  // Der Session-Token liegt in einem httpOnly-Cookie - JS kann seine
  // Existenz nicht direkt prüfen, daher hier immer beim Server nachfragen.
  try {
    const user = await api.me();
    setState({ user, loading: false });
  } catch {
    setState({ user: null, loading: false });
  }
}

let initialized = false;

/** Einmal beim App-Start aufrufen. */
export function init(): void {
  if (initialized) return;
  initialized = true;
  refreshUser();
  onUnauthenticated(() => {
    // Ein 401 sagt uns bereits definitiv, dass die Session ungültig ist -
    // hier direkt auf "ausgeloggt" setzen statt erneut refreshUser() (also
    // wieder api.me()) aufzurufen. Das würde selbst bei jedem weiteren 401
    // erneut notifyUnauthenticated() auslösen und in eine Endlosschleife aus
    // /api/auth/me-Requests laufen (auch schon beim allerersten Laden ohne
    // bestehende Session).
    setState({ user: null, loading: false });
  });
}

export async function login(email: string, password: string): Promise<void> {
  const res = await api.login(email, password);
  setState({ user: res.user, loading: false });
}

export async function register(email: string, password: string): Promise<void> {
  const res = await api.register(email, password);
  setState({ user: res.user, loading: false });
}

export async function logout(): Promise<void> {
  try {
    await api.logout();
  } finally {
    setState({ user: null, loading: false });
  }
}
