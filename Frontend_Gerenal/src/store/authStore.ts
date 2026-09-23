/**
 * Zustand auth store.
 *
 * Manages:
 *  - user (authenticated user object or null for guest)
 *  - accessToken / refreshToken
 *  - isGuest / isAuthenticated flags
 *  - login / register / logout / refresh / claimSession actions
 *
 * Token storage:
 *  - accessToken: in-memory only (not persisted — short TTL)
 *  - refreshToken: localStorage['propqa_refresh_token']
 *  - userId:       localStorage['propqa_user_id'] (anon-* for guests)
 */

import { create } from "zustand";
import { randomUUID } from "@/lib/uuid";

const STORAGE_KEYS = {
  userId: "propqa_user_id",
  refreshToken: "propqa_refresh_token",
  theme: "propqa_theme",
} as const;

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  phone?: string | null;
  role: "user" | "admin";
}

export interface AuthState {
  user: AuthUser | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isGuest: boolean;
  isLoading: boolean;
  error: string | null;

  // Stable browser user id — anon-* for guests, real id for authenticated users
  userId: string;

  // Actions
  initialize: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  logout: () => Promise<void>;
  refreshTokens: () => Promise<boolean>;
  claimSession: (sessionId: string) => Promise<void>;
  continueAsGuest: () => void;
  clearError: () => void;
  setError: (msg: string) => void;
}

export interface RegisterData {
  name: string;
  email: string;
  password: string;
  phone?: string;
}

// ── Local storage helpers ──────────────────────────────────────────────────

function getGuestUserId(): string {
  try {
    let id = localStorage.getItem(STORAGE_KEYS.userId);
    if (!id) {
      id = "anon-" + randomUUID();
      localStorage.setItem(STORAGE_KEYS.userId, id);
    }
    return id;
  } catch {
    return "anon-" + Math.random().toString(36).slice(2);
  }
}

function persistRefreshToken(token: string | null) {
  try {
    if (token) localStorage.setItem(STORAGE_KEYS.refreshToken, token);
    else localStorage.removeItem(STORAGE_KEYS.refreshToken);
  } catch { /* ignore */ }
}

function getStoredRefreshToken(): string | null {
  try { return localStorage.getItem(STORAGE_KEYS.refreshToken); } catch { return null; }
}

function persistUserId(id: string | null) {
  try {
    if (id) localStorage.setItem(STORAGE_KEYS.userId, id);
    else localStorage.removeItem(STORAGE_KEYS.userId);
  } catch { /* ignore */ }
}

// ── API helpers ────────────────────────────────────────────────────────────

interface AuthApiResponse {
  user: AuthUser;
  access_token: string;
  refresh_token: string;
}

async function authFetch(path: string, body: Record<string, unknown>): Promise<AuthApiResponse> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
          ? data.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ")
          : detail;
    } catch { /* ignore */ }
    if (res.status === 405) {
      detail =
        "Authentication API is unavailable (server returned Method Not Allowed). "
        + "Restart the backend after installing auth dependencies: "
        + "pip install -r Backend/requirements.txt";
    }
    throw new Error(detail);
  }
  return res.json();
}

async function fetchMe(token: string): Promise<AuthUser> {
  const res = await fetch("/api/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "same-origin",
  });
  if (!res.ok) throw new Error("token_invalid");
  return res.json();
}

// ── Window token sync helper ──────────────────────────────────────────────
// Keeps window.__propqa_access_token__ in sync so legacy code (analyticsApi.ts)
// that reads the global can find a valid token without a direct store import.

function syncWindowToken(token: string | null): void {
  try {
    if (token) {
      (window as Window & { __propqa_access_token__?: string }).__propqa_access_token__ = token;
    } else {
      delete (window as Window & { __propqa_access_token__?: string }).__propqa_access_token__;
    }
  } catch {
    /* window not available (SSR / test env) */
  }
}

// ── Store ──────────────────────────────────────────────────────────────────

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isGuest: true,
  isLoading: true,
  error: null,
  userId: getGuestUserId(),

  initialize: async () => {
    set({ isLoading: true });
    const refreshToken = getStoredRefreshToken();
    if (!refreshToken) {
      syncWindowToken(null);
      set({ isLoading: false, isGuest: true });
      return;
    }
    try {
      // Silently refresh access token from stored refresh token
      const data = await authFetch("/api/auth/refresh", { refresh_token: refreshToken });
      persistRefreshToken(data.refresh_token);
      persistUserId(data.user.id);
      syncWindowToken(data.access_token);
      set({
        user: data.user,
        accessToken: data.access_token,
        isAuthenticated: true,
        isGuest: false,
        userId: data.user.id,
        isLoading: false,
        error: null,
      });
    } catch {
      // Stored refresh token is expired/invalid — start as guest
      persistRefreshToken(null);
      syncWindowToken(null);
      set({ isLoading: false, isGuest: true });
    }
  },

  login: async (email: string, password: string) => {
    set({ isLoading: true, error: null });
    try {
      const data = await authFetch("/api/auth/login", { email, password });
      persistRefreshToken(data.refresh_token);
      persistUserId(data.user.id);
      syncWindowToken(data.access_token);
      set({
        user: data.user,
        accessToken: data.access_token,
        isAuthenticated: true,
        isGuest: false,
        userId: data.user.id,
        isLoading: false,
        error: null,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Login failed";
      set({ isLoading: false, error: msg });
      throw err;
    }
  },

  register: async (data: RegisterData) => {
    set({ isLoading: true, error: null });
    try {
      const resp = await authFetch("/api/auth/register", data as unknown as Record<string, unknown>);
      persistRefreshToken(resp.refresh_token);
      persistUserId(resp.user.id);
      syncWindowToken(resp.access_token);
      set({
        user: resp.user,
        accessToken: resp.access_token,
        isAuthenticated: true,
        isGuest: false,
        userId: resp.user.id,
        isLoading: false,
        error: null,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Registration failed";
      set({ isLoading: false, error: msg });
      throw err;
    }
  },

  logout: async () => {
    const rt = getStoredRefreshToken();
    if (rt) {
      try {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: rt }),
        });
      } catch { /* ignore */ }
    }
    persistRefreshToken(null);
    persistUserId(null); // mint fresh anon id on next access
    syncWindowToken(null);
    set({
      user: null,
      accessToken: null,
      isAuthenticated: false,
      isGuest: true,
      userId: getGuestUserId(),
      error: null,
    });
  },

  refreshTokens: async () => {
    const rt = getStoredRefreshToken();
    if (!rt) return false;
    try {
      const data = await authFetch("/api/auth/refresh", { refresh_token: rt });
      persistRefreshToken(data.refresh_token);
      syncWindowToken(data.access_token);
      set({ accessToken: data.access_token, user: data.user, isAuthenticated: true, isGuest: false });
      return true;
    } catch {
      persistRefreshToken(null);
      syncWindowToken(null);
      set({ user: null, accessToken: null, isAuthenticated: false, isGuest: true });
      return false;
    }
  },

  claimSession: async (sessionId: string) => {
    const { accessToken, userId, user } = get();
    if (!accessToken || !user) return;
    try {
      // The guest user_id before login
      const guestUserId = localStorage.getItem(STORAGE_KEYS.userId);
      await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/claim`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ guest_user_id: guestUserId, merge_ltm: true }),
      });
    } catch (err) {
      console.warn("[authStore] claimSession failed:", err);
    }
  },

  continueAsGuest: () => {
    // Always reset to a clean guest state — clears any partial auth state
    // that could cause isAuthenticated=true + isGuest=true simultaneously.
    set({
      user: null,
      accessToken: null,
      isAuthenticated: false,
      isGuest: true,
      isLoading: false,
      error: null,
    });
  },

  clearError: () => set({ error: null }),
  setError: (msg: string) => set({ error: msg }),
}));

// ── Fetch interceptor: auto-attach Bearer token ──────────────────────────
// Usage: call withAuth(headers) to inject Authorization header.

export function withAuthHeaders(base: Record<string, string> = {}): Record<string, string> {
  const token = useAuthStore.getState().accessToken;
  if (!token) return base;
  return { ...base, Authorization: `Bearer ${token}` };
}

export function getAuthUserId(): string {
  return useAuthStore.getState().userId;
}

export function getAccessToken(): string | null {
  return useAuthStore.getState().accessToken;
}
