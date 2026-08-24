/** Pub-Sub-Store als Ersatz für den bisherigen React-Context. */
import { api } from "../api/client.js";
import { getToken, onTokenChange, setToken } from "../api/tokenStore.js";
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
  if (!getToken()) {
    setState({ user: null, loading: false });
    return;
  }
  try {
    const user = await api.me();
    setState({ user, loading: false });
  } catch {
    setToken(null);
    setState({ user: null, loading: false });
  }
}

let initialized = false;

/** Einmal beim App-Start aufrufen. */
export function init(): void {
  if (initialized) return;
  initialized = true;
  refreshUser();
  onTokenChange(() => {
    refreshUser();
  });
}

export async function login(email: string, password: string): Promise<void> {
  const res = await api.login(email, password);
  setToken(res.access_token);
  setState({ user: res.user, loading: false });
}

export async function register(email: string, password: string): Promise<void> {
  const res = await api.register(email, password);
  setToken(res.access_token);
  setState({ user: res.user, loading: false });
}

export function logout(): void {
  setToken(null);
  setState({ user: null, loading: false });
}
