/**
 * Lightweight /api/health probe — cached, singleton inflight.
 */

import type { HealthFlags } from "@/store/chatStore";

interface HealthResponse {
  status: string;
  flags: HealthFlags;
  version: string;
}

let _cached: HealthResponse | null = null;
let _inflight: Promise<HealthResponse | null> | null = null;

export async function probeHealth({ force = false, timeoutMs = 2000 } = {}): Promise<HealthResponse | null> {
  if (!force && _cached) return _cached;
  if (_inflight) return _inflight;

  _inflight = (async () => {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        const res = await fetch("/api/health", { signal: ctrl.signal });
        clearTimeout(timer);
        if (!res.ok) return null;
        const body: HealthResponse = await res.json();
        if (body?.flags) {
          _cached = body;
          return body;
        }
        return null;
      } finally {
        clearTimeout(timer);
      }
    } catch {
      return null;
    } finally {
      _inflight = null;
    }
  })();

  return _inflight;
}

export function getCachedHealth(): HealthResponse | null {
  return _cached;
}

export function pickTransport(healthFlags: HealthFlags | undefined): "ws" | "sse" {
  if (!healthFlags) return "sse";
  if (
    healthFlags.ws_mounted &&
    (healthFlags.hitl_transport === "ws" || healthFlags.cognitive_pipeline)
  ) {
    return "ws";
  }
  return "sse";
}
