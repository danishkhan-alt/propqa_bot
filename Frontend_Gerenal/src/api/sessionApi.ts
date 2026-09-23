/**
 * Session management API client — typed port of sessionApi.js.
 */

import { withAuthHeaders } from "@/store/authStore";
import { randomUUID } from "@/lib/uuid";

async function _safeJson<T>(res: Response): Promise<T | null> {
  if (!res.ok) {
    console.warn(`[sessionApi] ${res.url} → HTTP ${res.status}`);
    return null;
  }
  try { return await res.json() as T; } catch { return null; }
}

export interface SessionSummary {
  session_id: string;
  last_active: string | null;
  created_at: string | null;
  user_turns: number;
  title: string;
}

export interface TurnRecord {
  turn_id: string;
  ts: number | null;
  user_message: string;
  assistant_message: string;
  cards: unknown[];
  envelope: Record<string, unknown> | null;
  steps?: unknown[];
  recall_hits?: unknown[];
  /** Mode B agent contacts shown for this turn (Redis-persisted) */
  agent_contacts?: unknown[];
  /** "none" | "agents_shown" | "submitted" | "dismissed" */
  lead_status?: string;
  /** Thumbs feedback — null/undefined until the user votes */
  thumbs_up?: boolean | null;
  thumbs_down?: boolean | null;
}

export interface SessionRestore {
  session_id: string;
  turns: TurnRecord[];
  messages: Array<{ role: string; content: string; ts: number | null }>;
  knowledge: Record<string, unknown>;
  summary: string;
  /** False when the restore request failed (non-2xx / network) — callers must
   *  NOT treat this as "no history" and wipe the session. */
  ok: boolean;
}

export function sortSessionsByCreatedAt(sessions: SessionSummary[]): SessionSummary[] {
  return [...sessions].sort((a, b) => {
    const aTs = a.created_at ? Date.parse(a.created_at) : 0;
    const bTs = b.created_at ? Date.parse(b.created_at) : 0;
    if (bTs !== aTs) return bTs - aTs;
    return (b.session_id ?? "").localeCompare(a.session_id ?? "");
  });
}

export async function listSessions({ userId, limit = 30 }: { userId?: string; limit?: number } = {}): Promise<SessionSummary[]> {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  if (Number.isFinite(limit)) params.set("limit", String(limit));
  try {
    const res = await fetch(`/api/sessions?${params}`, {
      credentials: "same-origin",
      headers: withAuthHeaders(),
    });
    const data = await _safeJson<{ sessions: SessionSummary[] } | SessionSummary[]>(res);
    if (!data) return [];
    const sessions = Array.isArray(data) ? data : (data as { sessions: SessionSummary[] }).sessions ?? [];
    return sortSessionsByCreatedAt(
      sessions.filter((s) => (s.user_turns ?? 0) > 0 && (s.title ?? "").trim() && s.title !== "(empty session)"),
    );
  } catch (err) {
    console.warn("[sessionApi] listSessions failed:", err);
    return [];
  }
}

export async function getSessionRestore(sessionId: string, { limit = 30 } = {}): Promise<SessionRestore> {
  // ``ok: false`` signals a transient failure (network / non-2xx) — distinct
  // from a successful response that genuinely has no history (``ok: true`` with
  // empty turns). Callers use this to avoid wiping a live session on a blip.
  const failed: SessionRestore = { session_id: sessionId, turns: [], messages: [], knowledge: {}, summary: "", ok: false };
  if (!sessionId) return { ...failed, ok: true };
  try {
    const res = await fetch(
      `/api/sessions/${encodeURIComponent(sessionId)}/turns?limit=${limit}`,
      { credentials: "same-origin", headers: withAuthHeaders() },
    );
    if (!res.ok) {
      console.warn(`[sessionApi] getSessionRestore → HTTP ${res.status}`);
      return failed;
    }
    let data: SessionRestore | null = null;
    try { data = await res.json() as SessionRestore; } catch { data = null; }
    if (!data || typeof data !== "object") return failed;
    return {
      session_id: data.session_id || sessionId,
      turns: Array.isArray(data.turns) ? data.turns : [],
      messages: Array.isArray(data.messages) ? data.messages : [],
      knowledge: data.knowledge && typeof data.knowledge === "object" ? data.knowledge : {},
      summary: typeof data.summary === "string" ? data.summary : "",
      ok: true,
    };
  } catch (err) {
    console.warn("[sessionApi] getSessionRestore failed:", err);
    return failed;
  }
}

export async function forgetSession(sessionId: string, { userId }: { userId?: string } = {}): Promise<boolean> {
  if (!sessionId) return false;
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/forget`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...withAuthHeaders() },
      credentials: "same-origin",
      body: JSON.stringify(userId ? { user_id: userId } : {}),
    });
    return res.ok;
  } catch { return false; }
}

/** Bulk forget — one Backend round-trip for Clear all (avoids N× /forget). */
export async function forgetSessions(
  sessionIds: string[],
  { userId }: { userId?: string } = {},
): Promise<boolean> {
  const ids = [...new Set(sessionIds.map((s) => s.trim()).filter(Boolean))];
  if (ids.length === 0) return true;
  if (ids.length === 1) return forgetSession(ids[0], { userId });
  try {
    const body: Record<string, unknown> = { session_ids: ids };
    if (userId) body.user_id = userId;
    const res = await fetch("/api/sessions/forget_many", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...withAuthHeaders() },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function newChat({
  previousSessionId,
  userId,
  carryOverLongTerm = true,
}: {
  previousSessionId?: string | null;
  userId?: string | null;
  carryOverLongTerm?: boolean;
} = {}): Promise<{ session_id: string; carried_over: string[] }> {
  try {
    const res = await fetch("/api/sessions/new", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...withAuthHeaders() },
      credentials: "same-origin",
      body: JSON.stringify({
        previous_session_id: previousSessionId,
        user_id: userId,
        carry_over_long_term: carryOverLongTerm,
      }),
    });
    const data = await _safeJson<{ session_id: string; carried_over: string[] }>(res);
    return data ?? { session_id: randomUUID(), carried_over: [] };
  } catch {
    return { session_id: randomUUID(), carried_over: [] };
  }
}

export async function getSessionQuota(sessionId: string): Promise<{ used: number; limit: number; remaining: number | null; exhausted: boolean }> {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/quota`, {
      credentials: "same-origin",
      headers: withAuthHeaders(),
    });
    const data = await _safeJson<{ used: number; limit: number; remaining: number | null; exhausted: boolean }>(res);
    return data ?? { used: 0, limit: 10, remaining: 10, exhausted: false };
  } catch { return { used: 0, limit: 10, remaining: 10, exhausted: false }; }
}

export async function getContextUsage(sessionId: string) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/context`, {
      credentials: "same-origin",
      headers: withAuthHeaders(),
    });
    return await _safeJson(res);
  } catch { return null; }
}

export async function compactContext(sessionId: string) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/context/compact`, {
      method: "POST",
      credentials: "same-origin",
      headers: withAuthHeaders(),
    });
    return await _safeJson(res);
  } catch { return null; }
}

export async function forgetAll(
  sessionId: string,
  { userId }: { userId?: string } = {},
): Promise<boolean> {
  if (!sessionId) return false;
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/forget_all`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...withAuthHeaders() },
      credentials: "same-origin",
      body: JSON.stringify(userId ? { user_id: userId } : {}),
    });
    return res.ok;
  } catch { return false; }
}
