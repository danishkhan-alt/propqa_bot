/**
 * SSE chat client — typed port of the vanilla JS sseClient.js.
 * Injects Authorization header when an access token is present.
 */

import { legacyEventToFrames, type ServerFrame } from "./frames";
import { withAuthHeaders } from "@/store/authStore";

interface SendSSEOpts {
  prompt: string;
  sessionId: string | null;
  userId: string | null;
  accessToken?: string | null;
  buyerPreferences?: Record<string, unknown> | null;
  persona?: string | null;
  personaContext?: Record<string, unknown> | null;
  /** Listing-scoped FAQ: property IDs attached in the composer. */
  focusedPropertyIds?: number[] | null;
  sessionProfile?: object | null;
  signal?: AbortSignal | null;
  onFrame: (frame: ServerFrame) => void;
  onError?: (err: Error) => void;
}

interface ResumeSSEOpts {
  sessionId: string;
  interruptId: string;
  decisions: unknown[];
  accessToken?: string | null;
  signal?: AbortSignal | null;
  onFrame: (frame: ServerFrame) => void;
  onError?: (err: Error) => void;
}

function _isAbortError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const name = (err as { name?: string }).name;
  return name === "AbortError" || name === "TimeoutError";
}

async function _streamSSE(
  path: string,
  body: Record<string, unknown>,
  headers: Record<string, string>,
  onFrame: (frame: ServerFrame) => void,
  onError?: (err: Error) => void,
  signal?: AbortSignal | null,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      credentials: "same-origin",
      body: JSON.stringify(body),
      signal: signal ?? undefined,
    });
  } catch (err) {
    if (_isAbortError(err) || signal?.aborted) {
      return;
    }
    const e = err instanceof Error ? err : new Error(String(err));
    onError?.(e);
    throw e;
  }

  if (!res.body) {
    const e = new Error("No response body");
    onError?.(e);
    throw e;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      if (signal?.aborted) {
        try {
          await reader.cancel();
        } catch {
          /* ignore */
        }
        return;
      }
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        if (!raw) continue;
        let parsed: Record<string, unknown>;
        try {
          parsed = JSON.parse(raw);
        } catch {
          continue;
        }
        for (const frame of legacyEventToFrames(parsed)) {
          onFrame(frame);
        }
      }
    }
  } catch (err) {
    if (_isAbortError(err) || signal?.aborted) {
      return;
    }
    const e = err instanceof Error ? err : new Error(String(err));
    onError?.(e);
    throw e;
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* ignore */
    }
  }
}

export async function sendSSE(opts: SendSSEOpts): Promise<void> {
  const headers = withAuthHeaders(opts.accessToken);
  const body: Record<string, unknown> = {
    message: opts.prompt,
    session_id: opts.sessionId,
    user_id: opts.userId,
  };
  if (opts.buyerPreferences && Object.keys(opts.buyerPreferences).length > 0) {
    body.buyer_preferences = opts.buyerPreferences;
  }
  if (opts.personaContext && Object.keys(opts.personaContext).length > 0) {
    body.persona_context = opts.personaContext;
  } else if (opts.persona) {
    body.persona = opts.persona;
  }
  // An empty profile is sent too: it is how a removed chip clears the server's copy.
  if (opts.sessionProfile) {
    body.session_profile = opts.sessionProfile;
  }
  if (Array.isArray(opts.focusedPropertyIds) && opts.focusedPropertyIds.length > 0) {
    body.focused_property_ids = opts.focusedPropertyIds;
  }
  await _streamSSE("/api/chat", body, headers, opts.onFrame, opts.onError, opts.signal);
}

export async function resumeSSE(opts: ResumeSSEOpts): Promise<void> {
  const headers = withAuthHeaders(opts.accessToken);
  await _streamSSE(
    "/api/chat/resume",
    {
      session_id: opts.sessionId,
      interrupt_id: opts.interruptId,
      decisions: opts.decisions,
    },
    headers,
    opts.onFrame,
    opts.onError,
    opts.signal,
  );
}

/** Fire-and-forget cross-worker cancel for an SSE pump. */
export function postCancelRun(
  runId: string,
  sessionId: string | null,
  accessToken?: string | null,
): void {
  if (!runId) return;
  const headers = withAuthHeaders(accessToken);
  void fetch(`/api/chat/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    credentials: "same-origin",
    body: JSON.stringify({ session_id: sessionId }),
  }).catch(() => {
    /* best-effort */
  });
}
