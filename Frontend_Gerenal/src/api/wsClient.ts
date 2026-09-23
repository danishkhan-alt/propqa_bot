/**
 * Resilient WebSocket client — typed port of wsClient.js.
 * Passes access token as ?token= query param when authenticated.
 */

import { parseFrame, type ServerFrame } from "./frames";

const DEFAULT_UPGRADE_TIMEOUT_MS = 1500;
const MAX_RECONNECT_ATTEMPTS = 8;

function nextBackoff(prev: number): number {
  const base = prev <= 0 ? 250 : prev;
  const jitter = Math.random() * base * 0.5;
  return Math.min(base * 1.5 + jitter, 4000);
}

function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms));
}

function buildWsUrl(sessionId: string | null, userId: string | null, token: string | null): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(`${proto}//${window.location.host}/ws/chat`);
  if (sessionId) url.searchParams.set("session_id", sessionId);
  if (userId) url.searchParams.set("user_id", userId);
  if (token) url.searchParams.set("token", token);
  return url.toString();
}

export interface WsHandlers {
  onFrame: (frame: ServerFrame) => void;
  onClose?: (evt: CloseEvent) => void;
  onReconnect?: () => void;
  onGiveUp?: () => void;
  onError?: (evt: Event) => void;
}

export interface WsHandle {
  sendUserMessage: (
    prompt: string,
    buyerPreferences?: Record<string, unknown> | null,
    personaOpts?: { persona?: string | null; personaContext?: Record<string, unknown> | null },
    focusedPropertyIds?: number[] | null,
  ) => void;
  sendResume: (interruptId: string, decisions: unknown[]) => void;
  sendCancel: (runId?: string | null) => void;
  sendCompactNow: () => boolean;
  /** Send any arbitrary JSON frame to the server */
  sendRaw: (payload: Record<string, unknown>) => boolean;
  setSessionId: (newSid: string) => boolean;
  getSessionId: () => string | null;
  setHandlers: (next: Partial<WsHandlers>) => void;
  close: () => void;
  isOpen: () => boolean;
  getReadyState: () => number;
}

export async function openWs({
  sessionId,
  userId,
  token,
  handlers = {} as WsHandlers,
  upgradeTimeoutMs = DEFAULT_UPGRADE_TIMEOUT_MS,
}: {
  sessionId: string | null;
  userId: string | null;
  token: string | null;
  handlers?: Partial<WsHandlers>;
  upgradeTimeoutMs?: number;
}): Promise<WsHandle> {
  if (typeof WebSocket === "undefined") throw new Error("WebSocket not available");

  let activeHandlers = { ...handlers };
  let socket: WebSocket | null = null;
  let closed = false;
  let reconnectAttempts = 0;
  let lastDelay = 0;
  let activeSessionId = sessionId;

  function _safeFire<K extends keyof WsHandlers>(name: K, ...args: Parameters<NonNullable<WsHandlers[K]>>) {
    const fn = activeHandlers[name] as ((...a: unknown[]) => void) | undefined;
    if (typeof fn === "function") {
      try { (fn as (...a: unknown[]) => void)(...args); } catch (e) { console.error("[wsClient] handler threw:", e); }
    }
  }

  async function _connectOnce(): Promise<void> {
    return new Promise((resolve, reject) => {
      let settled = false;
      let timer: ReturnType<typeof setTimeout> | null = null;
      const url = buildWsUrl(activeSessionId, userId, token);
      let ws: WebSocket;
      try { ws = new WebSocket(url); } catch (err) { reject(err); return; }

      function _settleResolve() {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        socket = ws;
        resolve();
      }
      function _settleReject(err: Error) {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        try { ws.close(); } catch { /* ignore */ }
        reject(err);
      }

      timer = setTimeout(() => _settleReject(new Error("WebSocket upgrade timeout")), upgradeTimeoutMs);

      ws.addEventListener("open", () => _settleResolve());

      ws.addEventListener("message", (evt) => {
        const frame = parseFrame(evt.data);
        if (!frame) return;
        if (!settled) _settleResolve();
        _safeFire("onFrame", frame);
      });

      ws.addEventListener("error", (evt) => {
        if (!settled) _settleReject(new Error("WebSocket error"));
        _safeFire("onError", evt);
      });

      ws.addEventListener("close", (evt) => {
        if (!settled) { _settleReject(new Error(`WS closed before upgrade (code=${evt.code})`)); return; }
        socket = null;
        if (closed) { _safeFire("onClose", evt); return; }
        _scheduleReconnect();
        _safeFire("onClose", evt);
      });
    });
  }

  async function _scheduleReconnect() {
    if (closed) return;
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) { _safeFire("onGiveUp"); return; }
    reconnectAttempts++;
    lastDelay = nextBackoff(lastDelay);
    try {
      await sleep(lastDelay);
      if (closed) return;
      await _connectOnce();
      reconnectAttempts = 0;
      lastDelay = 0;
      _safeFire("onReconnect");
    } catch {
      _scheduleReconnect();
    }
  }

  await _connectOnce();
  reconnectAttempts = 0;

  function _send(payload: Record<string, unknown>) {
    if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error("WebSocket not open");
    socket.send(JSON.stringify(payload));
  }

  return {
    sendUserMessage: (prompt, buyerPreferences, personaOpts, focusedPropertyIds) => {
      const frame: Record<string, unknown> = {
        type: "user_message",
        content: prompt,
        client: "general",
      };
      if (buyerPreferences && Object.keys(buyerPreferences).length > 0) {
        frame.buyer_preferences = buyerPreferences;
      }
      if (personaOpts?.personaContext && Object.keys(personaOpts.personaContext).length > 0) {
        frame.persona_context = personaOpts.personaContext;
      } else if (personaOpts?.persona) {
        frame.persona = personaOpts.persona;
      }
      if (Array.isArray(focusedPropertyIds) && focusedPropertyIds.length > 0) {
        frame.focused_property_ids = focusedPropertyIds;
      } else {
        frame.focused_property_ids = [];
      }
      _send(frame);
    },
    sendResume: (interruptId, decisions) => _send({ type: "resume", interrupt_id: interruptId, decisions }),
    sendCancel: (runId?: string | null) => {
      const frame: Record<string, unknown> = { type: "cancel" };
      if (runId) frame.run_id = runId;
      _send(frame);
    },
    sendCompactNow: () => {
      if (!socket || socket.readyState !== WebSocket.OPEN) return false;
      try { socket.send(JSON.stringify({ type: "compact_now" })); return true; }
      catch { return false; }
    },
    sendRaw: (payload) => {
      if (!socket || socket.readyState !== WebSocket.OPEN) return false;
      try { socket.send(JSON.stringify(payload)); return true; }
      catch { return false; }
    },
    setSessionId: (newSid) => {
      const next = newSid ? String(newSid) : null;
      if (!next || next === activeSessionId) return false;
      activeSessionId = next;
      if (socket && socket.readyState === WebSocket.OPEN) {
        try {
          socket.send(JSON.stringify({ type: "hello", session_id: next, client: "general" }));
          return true;
        }
        catch { return false; }
      }
      return false;
    },
    getSessionId: () => activeSessionId,
    setHandlers: (next) => { activeHandlers = { ...activeHandlers, ...next }; },
    close: () => {
      closed = true;
      try { socket?.close(); } catch { /* ignore */ }
      socket = null;
    },
    isOpen: () => !!socket && socket.readyState === WebSocket.OPEN,
    getReadyState: () => socket ? socket.readyState : WebSocket.CLOSED,
  };
}
