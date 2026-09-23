/**
 * analyticsApi.ts — Analytics, engagement, and feedback API client.  🔮
 *
 * All methods degrade gracefully — when the backend returns 503 / X-Status: planned
 * the functions return empty data instead of throwing so the UI stays stable.
 *
 * Backend routes:
 *   GET  /api/analytics/funnels
 *   GET  /api/analytics/engagement
 *   POST /api/feedback/thumbs
 *   POST /api/feedback/correction
 *   GET  /api/feedback/stats
 *   GET  /api/admin/eval-runs
 *   GET  /api/admin/prompt-versions
 */

// ── Types ────────────────────────────────────────────────────────────────────

export interface FunnelStage {
  name: string;
  count: number;
  rate: number;
}

export interface FunnelData {
  funnel: string;
  stages: FunnelStage[];
  period_days: number;
}

export interface EngagementMetrics {
  sessions: number;
  queries_per_session: number;
  lead_conversion_rate: number;
  avg_session_duration_s: number;
}

export interface EngagementData {
  metrics: EngagementMetrics;
  days: number;
}

export interface EvalRun {
  run_id: string;
  dataset: string;
  pass_rate: number;
  avg_groundedness: number;
  avg_relevance: number;
  created_at: string;
}

export interface PromptVersion {
  name: string;
  version: string;
  status: "draft" | "active" | "archived";
  created_at: string;
}

export interface FeedbackStats {
  thumbs_up: number;
  thumbs_down: number;
  corrections: number;
  days: number;
}

// ── Shared helper ─────────────────────────────────────────────────────────────

async function apiFetch<T>(
  url: string,
  options: RequestInit = {},
  fallback: T
): Promise<T> {
  try {
    const res = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
    });
    if (!res.ok) return fallback;
    const body = await res.json();
    if (body?.status === "no_data" || body?.status === "unavailable") return fallback;
    return body as T;
  } catch {
    return fallback;
  }
}

function getAuthHeader(): Record<string, string> {
  let token: string | null = null;
  // Primary: read directly from Zustand authStore (no stale closure risk)
  try {
    // Dynamic import to avoid circular dependency at module parse time
    const { useAuthStore } = require("../store/authStore");
    token = useAuthStore.getState().accessToken ?? null;
  } catch {
    // Fallback: legacy window global set by syncWindowToken in authStore.ts
    token =
      typeof window !== "undefined"
        ? (window.__propqa_access_token__ ?? null)
        : null;
  }
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ── Analytics ────────────────────────────────────────────────────────────────

export const analyticsApi = {
  /**
   * Fetch lead conversion funnel data for the last *days* days.
   * Returns [] when the backend has no data yet.
   */
  async getFunnels(days = 30): Promise<FunnelData[]> {
    const body = await apiFetch<{ data: FunnelData[] }>(
      `/api/analytics/funnels?days=${days}`,
      {},
      { data: [] }
    );
    return body.data ?? [];
  },

  /**
   * Fetch per-session engagement metrics.
   * Returns zeroed metrics when the backend has no data yet.
   */
  async getEngagement(days = 7): Promise<EngagementData> {
    const fallback: EngagementData = {
      metrics: { sessions: 0, queries_per_session: 0, lead_conversion_rate: 0, avg_session_duration_s: 0 },
      days,
    };
    const body = await apiFetch<{ metrics: EngagementMetrics; days: number }>(
      `/api/analytics/engagement?days=${days}`,
      {},
      { metrics: fallback.metrics, days }
    );
    return { metrics: body.metrics ?? fallback.metrics, days: body.days ?? days };
  },

  /**
   * Submit a thumbs up/down rating for a chatbot response.
   *
   * ``turnId``/``userMessage``/``assistantMessage`` let the backend locate the
   * exact conversation row to persist the vote on — ``turnId`` when known,
   * falling back to matching on message text for older turns.
   */
  async submitFeedback(
    thumbs: "up" | "down",
    messageId: string,
    sessionId?: string,
    comment?: string,
    turnContext?: { turnId?: string; userMessage?: string; assistantMessage?: string }
  ): Promise<void> {
    await apiFetch<unknown>(
      "/api/feedback/thumbs",
      {
        method: "POST",
        body: JSON.stringify({
          thumbs,
          message_id: messageId,
          session_id: sessionId,
          comment,
          turn_id: turnContext?.turnId,
          user_message: turnContext?.userMessage,
          assistant_message: turnContext?.assistantMessage,
        }),
      },
      null
    );
  },

  /**
   * Submit a corrected answer for the evaluation golden set.
   */
  async submitCorrection(
    messageId: string,
    originalAnswer: string,
    correctedAnswer: string,
    options?: { sessionId?: string; reason?: string }
  ): Promise<void> {
    await apiFetch<unknown>(
      "/api/feedback/correction",
      {
        method: "POST",
        body: JSON.stringify({
          message_id: messageId,
          original_answer: originalAnswer,
          corrected_answer: correctedAnswer,
          session_id: options?.sessionId,
          reason: options?.reason,
        }),
      },
      null
    );
  },

  /**
   * Fetch aggregated feedback statistics (admin).
   */
  async getFeedbackStats(days = 7): Promise<FeedbackStats> {
    const fallback: FeedbackStats = { thumbs_up: 0, thumbs_down: 0, corrections: 0, days };
    return apiFetch<FeedbackStats>(
      `/api/feedback/stats?days=${days}`,
      { headers: getAuthHeader() },
      fallback
    );
  },

  /**
   * Fetch recent evaluation run records (admin).
   */
  async getEvalRuns(limit = 20): Promise<EvalRun[]> {
    const body = await apiFetch<{ data: EvalRun[] }>(
      `/api/admin/eval-runs?limit=${limit}`,
      { headers: getAuthHeader() },
      { data: [] }
    );
    return body.data ?? [];
  },

  /**
   * Fetch registered prompt versions (admin).
   */
  async getPromptVersions(name?: string): Promise<PromptVersion[]> {
    const url = name
      ? `/api/admin/prompt-versions?name=${encodeURIComponent(name)}`
      : "/api/admin/prompt-versions";
    const body = await apiFetch<{ data: PromptVersion[] }>(
      url,
      { headers: getAuthHeader() },
      { data: [] }
    );
    return body.data ?? [];
  },
};

// ── Global access token slot (set by authStore after login) ───────────────────

declare global {
  interface Window {
    __propqa_access_token__?: string;
  }
}
