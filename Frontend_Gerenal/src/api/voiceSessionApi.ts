/**
 * Mint an ephemeral OpenAI Realtime translation client secret via Backend.
 * The long-lived OPENAI_API_KEY never reaches the browser.
 */

import { withAuthHeaders, getAuthUserId } from "@/store/authStore";

export interface VoiceSessionResponse {
  client_secret: string;
  expires_at: number | null;
}

export class VoiceSessionApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, opts: { status: number; code: string }) {
    super(message);
    this.name = "VoiceSessionApiError";
    this.status = opts.status;
    this.code = opts.code;
  }
}

export async function createVoiceSession(opts: {
  sessionId?: string | null;
  timeoutMs?: number;
}): Promise<VoiceSessionResponse> {
  const body: Record<string, string> = {};
  const sessionId = (opts.sessionId ?? "").trim();
  if (sessionId) body.session_id = sessionId;
  const userId = getAuthUserId();
  if (userId) body.user_id = userId;

  const timeoutMs = opts.timeoutMs ?? 15_000;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch("/api/realtime/voice-session", {
      method: "POST",
      credentials: "same-origin",
      headers: withAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    const aborted =
      (err instanceof DOMException && err.name === "AbortError") ||
      (err instanceof Error && err.name === "AbortError");
    throw new VoiceSessionApiError(
      aborted
        ? "Voice service timed out. Check that the Backend is running, then try again."
        : "Could not reach the voice service.",
      { status: 0, code: aborted ? "timeout" : "network_error" },
    );
  } finally {
    window.clearTimeout(timer);
  }

  if (!res.ok) {
    let code = "voice_error";
    let message = "Voice is unavailable.";
    try {
      const payload = (await res.json()) as {
        detail?: { code?: string; message?: string } | string;
      };
      const detail = payload.detail;
      if (detail && typeof detail === "object") {
        if (typeof detail.code === "string") code = detail.code;
        if (typeof detail.message === "string" && detail.message.trim()) {
          message = detail.message;
        }
      } else if (typeof detail === "string" && detail.trim()) {
        message = detail;
      }
    } catch {
      /* keep defaults */
    }
    if (res.status === 429) {
      message = "Too many voice requests. Please wait and try again.";
      code = "rate_limited";
    } else if (res.status === 503) {
      // Prefer server detail when present (e.g. missing OPENAI_API_KEY).
      if (code === "voice_unavailable") {
        message =
          "Voice isn’t configured on the server (set OPENAI_API_KEY in Backend/.env and restart).";
      } else if (!message.trim()) {
        message = "Voice is unavailable.";
      }
    }
    throw new VoiceSessionApiError(message, { status: res.status, code });
  }

  const data = (await res.json()) as Partial<VoiceSessionResponse>;
  const secret = typeof data.client_secret === "string" ? data.client_secret.trim() : "";
  if (!secret) {
    throw new VoiceSessionApiError("Voice session was incomplete.", {
      status: res.status,
      code: "invalid_response",
    });
  }

  return {
    client_secret: secret,
    expires_at:
      typeof data.expires_at === "number" && Number.isFinite(data.expires_at)
        ? data.expires_at
        : null,
  };
}
