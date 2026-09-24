/**
 * useChat — main chat orchestration hook.
 *
 * Manages:
 *  - Session state (session_id, user_id)
 *  - Transport selection (WS preferred, SSE fallback)
 *  - Message list (optimistic append, streaming update)
 *  - Turn lifecycle (start, token, cards, hitl, result, done, error)
 *  - Session management (new chat, load session, sidebar refresh)
 *  - Guest banner triggers (searchCount, agentClick)
 */

import { useState, useRef, useCallback, useEffect } from "react";
import { toast } from "sonner";
import { probeHealth, getCachedHealth, pickTransport } from "@/api/health";
import { sendSSE, resumeSSE, postCancelRun } from "@/api/sseClient";
import { openWs, type WsHandle } from "@/api/wsClient";
import { newChat as newChatApi, getSessionRestore, forgetSession, forgetAll } from "@/api/sessionApi";
import { getPreferences } from "@/api/preferencesApi";
import { syncFlowsRegistry, useChatStore, FLOWS_REGISTRY, type PropertyCard, type StepFrame, type ResultEnvelope } from "@/store/chatStore";
import { useAuthStore } from "@/store/authStore";
import { useSessionProfileStore } from "@/store/sessionProfileStore";
import { randomUUID } from "@/lib/uuid";
import {
  isTokenFrame,
  isStepFrame,
  isCardsFrame,
  isHitlFrame,
  isResultFrame,
  isDoneFrame,
  isErrorFrame,
  isCancelledFrame,
  isAgentContactsFrame,
  isLeadCaptureHitlFrame,
  isReplyFrame,
  type ServerFrame,
  type AgentContact,
} from "@/api/frames";
import type { Message } from "@/components/chat/MessageList";
import type { BannerTrigger } from "@/components/chat/GuestBanner";
import type { AgentCoverage } from "@/components/leads";
import { cardPropertyIds } from "@/lib/propertyIds";
import { parseEnvelopeSuggestions, type FollowUpSuggestion } from "@/lib/followUpSuggestions";
import { isYieldPublicStub, isYieldWorksheetOnly, pickRestoredAssistantText } from "@/lib/markdown";
import { usePrefsStore, selectOutgoingBuyerPreferences } from "@/store/prefsStore";

/** Steps that are observability-only — exclude from pipeline duration sum */
const PIPELINE_SKIP_STEPS = new Set([
  "connected",
  "context_usage",
  "session_rotated",
  "status",
  "hitl_skipped",
]);

/**
 * Wall-clock-ish sum of pipeline steps for "Thought for Xs" / history restore.
 *
 * - Skip parallel children (their parent, e.g. finalize_tail, owns the wall time).
 * - Skip propqa_core when search_domain reported ms — propqa_core wraps the
 *   legacy graph and double-counted search (was inflating "Thought for" toward
 *   2 minutes on cold/slow turns).
 */
function sumPipelineStepMs(steps: StepFrame[]): number {
  const hasSearchDomain = steps.some(
    (s) => s.step === "search_domain" && (s.ms ?? 0) > 0,
  );
  return steps
    .filter((s) => {
      if (!s.ms || s.ms <= 0) return false;
      if (PIPELINE_SKIP_STEPS.has(s.step)) return false;
      if (s.parallel) return false;
      if (s.step === "propqa_core" && hasSearchDomain) return false;
      return true;
    })
    .reduce((sum, s) => sum + (s.ms ?? 0), 0);
}

function resolveTurnDurationMs(turnId: string, wallMs: number): number {
  const record = useChatStore.getState().getTurnRecord(turnId);
  const pipelineMs = record?.steps?.length ? sumPipelineStepMs(record.steps) : 0;
  return wallMs > 0 ? wallMs : pipelineMs;
}

const SESSION_KEY = "propqa_chat_session_id";

// Track whether sessionStorage already had a session key when this tab first loaded.
// true  = same-tab reload  → allow history restore for guests
// false = new browser tab  → force startNewChat so each tab starts fresh for guests
let _tabInitialized = false;
let _wasRestoredFromTab = false;

function getStoredSessionId(): string {
  try {
    const tabId = sessionStorage.getItem(SESSION_KEY);
    if (tabId) {
      // sessionStorage was populated: this is a same-tab page reload
      if (!_tabInitialized) { _wasRestoredFromTab = true; _tabInitialized = true; }
      return tabId;
    }
    // sessionStorage is empty: this is a new browser tab
    if (!_tabInitialized) { _wasRestoredFromTab = false; _tabInitialized = true; }
    // For returning authenticated users, fall back to localStorage so they
    // don't lose their session on a new tab. Guests will be handled in
    // bootTransport by calling startNewChat() when !_wasRestoredFromTab.
    const fallback = localStorage.getItem(SESSION_KEY) || randomUUID();
    sessionStorage.setItem(SESSION_KEY, fallback);
    return fallback;
  } catch {
    if (!_tabInitialized) { _wasRestoredFromTab = false; _tabInitialized = true; }
    return randomUUID();
  }
}

/**
 * Read-only lookup of the current tab's active chat session id, for callers
 * outside this hook (e.g. PrefsPanel's "Reset" button, which needs to clear
 * this session's server-side `last_filter_spec` carry-forward memory too).
 * Unlike `getStoredSessionId()` this never mints or persists a new id as a
 * side effect — it simply returns whatever is already there, or `null`.
 */
export function getActiveSessionId(): string | null {
  try {
    return sessionStorage.getItem(SESSION_KEY) || localStorage.getItem(SESSION_KEY) || null;
  } catch {
    return null;
  }
}

function setStoredSessionId(id: string | null) {
  try {
    // Always write to sessionStorage (tab-scoped) so same-tab reloads work
    if (id) sessionStorage.setItem(SESSION_KEY, id);
    else    sessionStorage.removeItem(SESSION_KEY);

    // Write to localStorage only for authenticated users (cross-tab persistence).
    // For guests, actively clear localStorage to prevent old sessions bleeding
    // into new tabs.
    if (!useAuthStore.getState().isGuest) {
      if (id) localStorage.setItem(SESSION_KEY, id);
      else    localStorage.removeItem(SESSION_KEY);
    } else {
      localStorage.removeItem(SESSION_KEY);
    }
  } catch { /* ignore */ }
}

/**
 * Wait until the auth store has finished its initialisation (`isLoading → false`).
 * This ensures bootTransport can safely read `isGuest` before deciding whether to
 * restore or start fresh. Resolves immediately if auth is already done.
 */
function waitForAuth(timeoutMs = 3000): Promise<void> {
  if (!useAuthStore.getState().isLoading) return Promise.resolve();
  return new Promise((resolve) => {
    const unsub = useAuthStore.subscribe((s) => {
      if (!s.isLoading) { unsub(); resolve(); }
    });
    setTimeout(() => { unsub(); resolve(); }, timeoutMs);
  });
}

/** Build the React message list from backend turn records. Dedupes consecutive identical pairs. */
function buildMessagesFromTurns(turns: {
  turn_id: string;
  ts: number | null;
  user_message: string;
  assistant_message: string;
  cards: unknown[];
  envelope: Record<string, unknown> | null;
  steps?: unknown[];
  agent_contacts?: unknown[];
  lead_status?: string;
  thumbs_up?: boolean | null;
  thumbs_down?: boolean | null;
}[]): Message[] {
  const loaded: Message[] = [];
  let prevKey = "";
  for (const turn of turns) {
    const env = turn.envelope as Record<string, unknown> | null;
    const user = (turn.user_message || "").trim();
    // Fallback to envelope.answer_md when the assistant transcript text is
    // missing — otherwise turns that carry only cards/envelope are dropped
    // entirely on restore (message AND cards lost).
    const asst = pickRestoredAssistantText(
      turn.assistant_message || "",
      (env?.answer_md as string) || "",
    );
    const key = `${user}\0${asst}`;
    if (key === prevKey && user && asst) continue; // skip duplicate
    prevKey = key;

    if (user) {
      loaded.push({
        id: randomUUID(),
        role: "user",
        content: user,
        timestamp: turn.ts ? new Date(turn.ts) : undefined,
      });
    }

    // Resolve cards from direct field first, then envelope.cards
    const cards = (turn.cards?.length ? turn.cards : (env?.cards as unknown[]) ?? []) as PropertyCard[];
    const leadStatus = turn.lead_status as Message["leadStatus"] | undefined;
    const agentContacts =
      leadStatus === "dismissed"
        ? undefined
        : Array.isArray(turn.agent_contacts)
          ? (turn.agent_contacts as AgentContact[])
          : undefined;

    // Emit an assistant bubble when there's text OR cards (card-only turns must
    // still render so the PropertiesSidebar is rebuilt after a refresh).
    if (asst || cards.length) {
      const steps = (turn.steps ?? []) as StepFrame[];
      const pipelineMs = sumPipelineStepMs(steps);

      // Resolve searchUrl from envelope.metadata
      let searchUrl: Message["searchUrl"] | undefined;
      const meta = env?.metadata as Record<string, unknown> | undefined;
      if (typeof meta?.search_url === "string") {
        searchUrl = {
          url: meta.search_url as string,
          total: typeof meta.total_matches === "number" ? meta.total_matches : 0,
          shown: typeof meta.shown === "number" ? meta.shown : 0,
          strictUrl: typeof meta.strict_search_url === "string" ? meta.strict_search_url : null,
        };
      }

      const appliedFilters = Array.isArray(meta?.applied_filters)
        ? (meta.applied_filters as string[])
        : undefined;

      const suggestions = parseEnvelopeSuggestions(env);

      loaded.push({
        id: randomUUID(),
        role: "assistant",
        content: asst,
        isStreaming: false,
        timestamp: turn.ts ? new Date(turn.ts) : undefined,
        userPrompt: user,
        cards: cards.length ? cards : undefined,
        searchUrl,
        appliedFilters,
        turnId: turn.turn_id,
        durationMs: pipelineMs > 0 ? pipelineMs : undefined,
        agentContacts,
        leadStatus,
        suggestions: suggestions.length ? suggestions : [],
        thumbsUp: turn.thumbs_up,
        thumbsDown: turn.thumbs_down,
        steps: steps.length ? (steps as unknown as StepFrame[]) : undefined,
      });
    }
  }
  return loaded;
}

/** Build bubbles from the flat LangChain ``messages`` array (role/content) —
 *  used as a fallback when the turn index is gone but message history survives. */
function buildMessagesFromHistory(history: Array<{ role: string; content: string; ts: number | null }>): Message[] {
  const out: Message[] = [];
  for (const m of history) {
    const content = (m.content || "").trim();
    if (!content) continue;
    const role = m.role === "user" ? "user" : "assistant";
    out.push({
      id: randomUUID(),
      role,
      content,
      isStreaming: false,
      timestamp: m.ts ? new Date(m.ts) : undefined,
    });
  }
  return out;
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [loadingStatus, setLoadingStatus] = useState("");
  const [sessionId, setSessionId] = useState<string>(() => getStoredSessionId());
  const [guestBanner, setGuestBanner] = useState<BannerTrigger | null>(null);
  const [searchCount, setSearchCount] = useState(0);

  const chatStore = useChatStore.getState();
  const updateChatStore = useChatStore;

  const wsRef = useRef<WsHandle | null>(null);
  const transportRef = useRef<"ws" | "sse">("sse");
  const bootingRef = useRef(false); // mutex: prevent concurrent bootTransport calls
  // Prevent the [accessToken] effect from running on the very first render.
  // bootTransport() owns the initial WS connection; this effect only handles
  // genuine post-boot token changes (login / logout).
  const isFirstTokenMountRef = useRef(true);
  const currentTurnRef = useRef<{
    id: string;
    prompt: string;
    msgId: string;
    startedAt: number;
    cards: PropertyCard[] | null;
    searchUrl: Message["searchUrl"] | null;
    appliedFilters: string[] | null;
    runId?: string | null;
  } | null>(null);
  const sseAbortRef = useRef<AbortController | null>(null);

  // Auth-transition tracking — used by the isGuest effect below.
  // authBootedRef becomes true after the first time authLoading settles to false,
  // so we don't treat the initial bootstrap flip (isGuest: true → false on token
  // refresh) as a real login event.
  const authBootedRef = useRef(false);
  const prevIsGuestRef = useRef<boolean | null>(null);

  const { userId, accessToken, isGuest, isLoading: authLoading, claimSession } = useAuthStore();

  // ── Bootstrap ────────────────────────────────────────────────────────────

  useEffect(() => {
    syncFlowsRegistry().catch(() => {});
    bootTransport();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // One-time hydration of buyer preferences from the Redis-backed profile
  // when this browser's localStorage has none — covers a cleared cache or
  // a brand-new device/browser for a returning, SIGNED-IN user. Never
  // overwrites preferences the user already has locally. Preferences are a
  // signed-in-only feature — skip entirely for guests.
  useEffect(() => {
    if (usePrefsStore.getState().hasPreferences) return;
    waitForAuth().then(() => {
      const { isAuthenticated, userId: uid } = useAuthStore.getState();
      if (!isAuthenticated || !uid) return;
      getPreferences({ userId: uid }).then((prefs) => {
        if (prefs && !usePrefsStore.getState().hasPreferences) {
          usePrefsStore.getState().replacePreferences(prefs);
        }
      });
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-run on auth changes: reconnect WS with new token but DO NOT create a new session.
  // If a query is currently streaming, abort it gracefully so the UI is never stuck
  // at "Saving…" waiting for a done frame that will never arrive on the new socket.
  useEffect(() => {
    // Skip the initial mount — bootTransport() handles the first WS connection.
    // Without this guard the effect races with bootTransport() and opens a
    // second (duplicate) WebSocket on every page load.
    if (isFirstTokenMountRef.current) {
      isFirstTokenMountRef.current = false;
      return;
    }
    // When a guest→auth transition is in progress, skip the WS reconnect here.
    // The [isGuest] effect owns the full transition (session clear + fresh WS)
    // and will call reconnectWs() only after startNewChat() has committed the
    // new session ID. Reconnecting here would race and bind the WS to the stale
    // guest session ID, causing conversation bleed.
    if (prevIsGuestRef.current && !useAuthStore.getState().isGuest) return;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (currentTurnRef.current) {
      setIsStreaming(false);
      setLoadingStatus("");
      currentTurnRef.current = null;
      useChatStore.getState().reset();
    }
    // Only reconnect WS — don't touch session or messages
    reconnectWs();
  }, [accessToken]); // eslint-disable-line react-hooks/exhaustive-deps

  // Detect real Guest↔Authenticated transitions and reset chat so the previous
  // mode's conversation is never shown to the new mode.
  //
  // Guard: while authLoading is true the store is still initialising. The flag
  // flips isGuest true→false when a stored refresh token is silently exchanged
  // on page load — that is NOT a user-initiated login and must be ignored.
  // We only act after authLoading has settled to false for the first time.
  useEffect(() => {
    if (authLoading) return; // still bootstrapping — record nothing yet

    if (!authBootedRef.current) {
      // Auth just finished loading for the first time — snapshot stable state.
      authBootedRef.current = true;
      prevIsGuestRef.current = isGuest;
      // Clear guest-only UI state after initial auth load if authenticated.
      if (!isGuest) { setGuestBanner(null); setSearchCount(0); }
      return;
    }

    // Whenever isGuest becomes false (user authenticated), always clear the
    // guest banner — guards against a stale WS handler having set it after
    // the initial boot clear ran.
    if (!isGuest) { setGuestBanner(null); setSearchCount(0); }

    if (prevIsGuestRef.current === isGuest) return; // no real change
    prevIsGuestRef.current = isGuest;

    // ── Real auth-mode transition ──────────────────────────────────────────
    // Close the current WS immediately so no more frames arrive from the
    // previous mode's session. This effect now owns the full transition:
    // it creates the new session AND opens the new WS — the [accessToken]
    // effect is bypassed for this path (see its guest→auth guard above).
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }

    // Abort any in-flight streaming turn.
    if (currentTurnRef.current) {
      setIsStreaming(false);
      setLoadingStatus("");
      currentTurnRef.current = null;
      useChatStore.getState().reset();
    }

    // Wipe the message list immediately so old history is never visible.
    setMessages([]);
    setGuestBanner(null);
    setSearchCount(0);

    // Remove the previous mode's session ID from both storages so
    // startNewChat() mints a completely fresh session for the new mode.
    try {
      sessionStorage.removeItem(SESSION_KEY);
      localStorage.removeItem(SESSION_KEY);
    } catch { /* ignore */ }

    // Await startNewChat() so we have the fresh session ID before opening
    // the new WS. Passing the fresh ID explicitly to reconnectWs() prevents
    // the stale React-state closure from binding the WS to the old session.
    (async () => {
      const freshId = await startNewChat();
      // Open a new WS with the fresh session. Skip if bootTransport() is
      // still running — it will open the initial socket itself.
      if (freshId) {
        await reconnectWs(freshId);
      }
    })();
  }, [isGuest, authLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  async function bootTransport() {
    if (bootingRef.current) return; // prevent concurrent boots
    bootingRef.current = true;
    try {
      const health = await probeHealth();
      if (health) useChatStore.getState().setHealth(health);
      const preferred = pickTransport(health?.flags);
      if (preferred === "ws") {
        try {
          const handle = await openWs({
            sessionId,
            userId,
            token: accessToken,
            handlers: {
              onFrame: handleFrame,
              onGiveUp: () => {
                transportRef.current = "sse";
                useChatStore.getState().setTransportMode("sse");
              },
            },
          });
          wsRef.current = handle;
          transportRef.current = "ws";
          useChatStore.getState().setTransportMode("ws");
        } catch {
          transportRef.current = "sse";
          useChatStore.getState().setTransportMode("sse");
        }
      } else {
        transportRef.current = "sse";
        useChatStore.getState().setTransportMode("sse");
      }
      // Wait for auth to stabilise so we can reliably read isGuest below.
      // For guest users this resolves immediately (no HTTP call). For returning
      // authenticated users it waits up to 3 s for the refresh-token exchange.
      await waitForAuth(3000);

      // Resume the stored session — do NOT mint a new id on every page load.
      const storedSid = getStoredSessionId();
      const { isGuest: guestNow } = useAuthStore.getState();
      if (guestNow && !_wasRestoredFromTab) {
        // New browser tab as guest → always start fresh so each tab gets its
        // own isolated conversation and old history never bleeds across tabs.
        await startNewChat();
      } else {
        await restoreOrNewChat(storedSid);
      }
    } finally {
      bootingRef.current = false;
    }
  }

  /**
   * Restore history for an existing session, or start a fresh one if the
   * session has *genuinely* no history. A transient fetch failure must NOT
   * mint a new session — that wipes the screen even though the server still
   * has the conversation.
   */
  async function restoreOrNewChat(sid: string) {
    const restore = await getSessionRestore(sid, { limit: 30 });

    // Transient failure (network / non-2xx): keep the current session id and
    // whatever is on screen. Never start a new chat on a blip.
    if (!restore.ok) {
      setStoredSessionId(sid);
      setSessionId(sid);
      wsRef.current?.setSessionId?.(sid);
      setIsStreaming(false);
      setLoadingStatus("");
      return;
    }

    // Prefer full turn records (text + cards + lead state).
    if (restore.turns.length > 0) {
      setStoredSessionId(sid);
      setSessionId(sid);
      wsRef.current?.setSessionId?.(sid);
      useChatStore.getState().reset();
      currentTurnRef.current = null;
      setMessages(buildMessagesFromTurns(restore.turns));
      setIsStreaming(false);
      setLoadingStatus("");
      return;
    }

    // Turn index gone but flat message history survives — hydrate text bubbles
    // so the chat is not lost (cards can't be recovered from this path).
    if (restore.messages.length > 0) {
      setStoredSessionId(sid);
      setSessionId(sid);
      wsRef.current?.setSessionId?.(sid);
      useChatStore.getState().reset();
      currentTurnRef.current = null;
      setMessages(buildMessagesFromHistory(restore.messages));
      setIsStreaming(false);
      setLoadingStatus("");
      return;
    }

    // Confirmed empty (successful fetch, no turns, no messages) — fresh session.
    await startNewChat();
  }

  /**
   * Reconnect the WS socket only (no new session, no message reset).
   *
   * @param overrideSessionId - When supplied the WS opens with this session ID
   *   instead of the stale React-state closure value. Required when calling
   *   from the [isGuest] transition effect, where startNewChat() has already
   *   committed a fresh ID that hasn't propagated through React state yet.
   */
  async function reconnectWs(overrideSessionId?: string) {
    // If bootTransport() is still running, let it finish — it will open the
    // initial socket itself. Starting a second openWs() call here would create
    // a duplicate connection that races to set wsRef.current.
    if (bootingRef.current) return;
    const health = getCachedHealth() ?? await probeHealth();
    if (health) useChatStore.getState().setHealth(health);
    const preferred = pickTransport(health?.flags);
    if (preferred !== "ws") {
      transportRef.current = "sse";
      useChatStore.getState().setTransportMode("sse");
      return;
    }
    const sid = overrideSessionId ?? sessionId;
    const liveUserId = useAuthStore.getState().userId ?? userId;
    try {
      const handle = await openWs({
        sessionId: sid,
        userId: liveUserId,
        token: accessToken,
        handlers: {
          onFrame: handleFrame,
          onGiveUp: () => {
            transportRef.current = "sse";
            useChatStore.getState().setTransportMode("sse");
          },
        },
      });
      wsRef.current = handle;
      transportRef.current = "ws";
      useChatStore.getState().setTransportMode("ws");
    } catch {
      transportRef.current = "sse";
      useChatStore.getState().setTransportMode("sse");
    }
  }

  // ── Message helpers ──────────────────────────────────────────────────────

  function appendMessage(role: Message["role"], content: string, extra: Partial<Message> = {}): string {
    const id = randomUUID();
    setMessages((prev) => [...prev, { id, role, content, timestamp: new Date(), ...extra }]);
    return id;
  }

  function updateLastAssistant(updater: (msg: Message) => Message) {
    setMessages((prev) => {
      const idx = [...prev].reverse().findIndex((m) => m.role === "assistant");
      if (idx === -1) return prev;
      const realIdx = prev.length - 1 - idx;
      return prev.map((m, i) => i === realIdx ? updater(m) : m);
    });
  }

  function updateMessage(id: string, updater: (msg: Message) => Message) {
    setMessages((prev) => prev.map((m) => m.id === id ? updater(m) : m));
  }

  // ── Frame handler ────────────────────────────────────────────────────────

  function handleFrame(frame: ServerFrame) {
    if (isCancelledFrame(frame)) {
      const turn = currentTurnRef.current;
      setIsStreaming(false);
      setLoadingStatus("");
      if (turn) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === turn.msgId
              ? {
                  ...m,
                  isStreaming: false,
                  content: m.content || "",
                  statusText: m.content ? undefined : "Stopped",
                }
              : m,
          ),
        );
      }
      currentTurnRef.current = null;
      useChatStore.getState().reset();
      return;
    }

    if (isErrorFrame(frame)) {
      setIsStreaming(false);
      setLoadingStatus("");
      const turn = currentTurnRef.current;
      setMessages((prev) => {
        // If a streaming message already exists for this turn, finalize it.
        // When it already has content (tokens were streamed), keep that content.
        // When it is empty, fill in the error text so the bubble isn't blank.
        const idx = turn ? prev.findIndex((m) => m.id === turn.msgId) : -1;
        if (idx !== -1) {
          return prev.map((m, i) =>
            i === idx
              ? { ...m, isStreaming: false, content: m.content || frame.message }
              : m
          );
        }
        // No streaming message was started — create one with the error text.
        return [
          ...prev,
          {
            id: turn?.msgId ?? randomUUID(),
            role: "assistant" as const,
            content: frame.message,
            isStreaming: false,
            userPrompt: turn?.prompt,
            timestamp: new Date(),
          },
        ];
      });
      currentTurnRef.current = null;
      return;
    }

    if (isStepFrame(frame)) {
      const turn = currentTurnRef.current;
      const payloadRunId =
        frame.payload && typeof frame.payload.run_id === "string"
          ? frame.payload.run_id
          : null;
      if (turn && payloadRunId && !turn.runId) {
        turn.runId = payloadRunId;
      }
      useChatStore.getState().pushStep(frame);
      if (frame.step === "status" && frame.status) {
        setLoadingStatus(frame.status);
      } else if (frame.step && frame.status !== "skipped") {
        const labels: Record<string, string> = {
          boot: "Initialising…", think: "Thinking…", enhance: "Enhancing query…",
          rebuild: "Rebuilding…", reason: "Reasoning…", propqa_core: "Searching properties…",
          research_start: "Starting research…", commit: "Saving…",
          coverage_check: "Verifying coverage…", verify_gate: "Verifying answer…",
          answer_gate: "Verifying answer…", grounding_check: "Verifying listings…",
        };
        if (labels[frame.step]) setLoadingStatus(labels[frame.step]);
      }
      if ((frame.step === "boot" || frame.step === "think") && frame.payload?.flow_id) {
        const flowId = String(frame.payload.flow_id);
        const stages = FLOWS_REGISTRY[flowId] ?? [];
        useChatStore.getState().setActiveFlow(flowId, stages);
      }
      if (frame.step === "context_usage" && frame.payload) {
        useChatStore.getState().setContextUsage(frame.payload as { fraction?: number; prompt_tokens?: number });
      }
      if (frame.step === "lead_readiness" && frame.payload) {
        const p = frame.payload as {
          score?: number;
          offer_ready?: boolean;
          soft_ready?: boolean;
          recommended_mode?: "none" | "A" | "B" | "both";
        };
        useChatStore.getState().setLeadReadiness(
          p.score ?? 0,
          p.offer_ready ?? false,
          p.soft_ready ?? false,
          p.recommended_mode,
        );
      }
      return;
    }

    if (isReplyFrame(frame)) {
      const turn = currentTurnRef.current;
      if (!turn) return;
      const reply = frame.reply;
      const intro = typeof reply.intro_text === "string" ? reply.intro_text : "";
      const profile = reply.session_profile;
      if (profile && typeof profile === "object") {
        useSessionProfileStore.getState().merge(profile as Record<string, unknown>);
      }
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === turn.msgId);
        const next = {
          content: intro,
          structured: reply,
          isStreaming: true,
        };
        if (idx === -1) {
          return [
            ...prev,
            {
              id: turn.msgId,
              role: "assistant" as const,
              userPrompt: turn.prompt,
              timestamp: new Date(),
              ...next,
            },
          ];
        }
        return prev.map((m, i) => (i === idx ? { ...m, ...next } : m));
      });
      return;
    }

    if (isTokenFrame(frame)) {
      const turn = currentTurnRef.current;
      if (!turn) return;
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === turn.msgId);
        if (idx === -1) {
          // Create assistant bubble on first token
          return [
            ...prev,
            {
              id: turn.msgId,
              role: "assistant" as const,
              content: frame.token,
              isStreaming: true,
              userPrompt: turn.prompt,
              timestamp: new Date(),
            },
          ];
        }
        const updated = { ...prev[idx], content: prev[idx].content + frame.token };
        return prev.map((m, i) => i === idx ? updated : m);
      });
      return;
    }

    if (isCardsFrame(frame)) {
      const turn = currentTurnRef.current;
      if (turn) {
        turn.cards = frame.cards as PropertyCard[];
        if (frame.search_url) {
          turn.searchUrl = {
            url: frame.search_url,
            total: frame.total_matches ?? 0,
            shown: frame.shown ?? frame.cards.length,
            strictUrl: frame.strict_search_url ?? null,
          };
        }
        if (frame.applied_filters?.length) turn.appliedFilters = frame.applied_filters;
        useChatStore.getState().noteCardsRendered();
        setSearchCount((n) => {
          const next = n + 1;
          // Read isGuest from the store directly — avoids stale closure from
          // the WS handler that was captured before auth settled on page load.
          if (useAuthStore.getState().isGuest && next === 3) setGuestBanner("search_count");
          return next;
        });
      }
      return;
    }

    // Mode B: agent contact cards
    if (isAgentContactsFrame(frame)) {
      useChatStore.getState().setAgentContacts(frame.agents, frame.note);
      return;
    }

    if (isHitlFrame(frame)) {
      // Mode A: lead capture form — mark as a pending HITL so existing HitlPrompt
      // dispatch works, but also update lead capture status for the form component.
      if (isLeadCaptureHitlFrame(frame)) {
        useChatStore.getState().setLeadCaptureStatus("pending");
      }
      useChatStore.getState().addHitl(frame);
      return;
    }

    if (isResultFrame(frame)) {
      useChatStore.getState().setEnvelope(frame.envelope as { answer_md?: string });
      const envelope = frame.envelope as {
        answer_md?: string;
        cards?: unknown[];
      };
      // Prefer envelope cards (schema-coerced, includes agency_logo_url /
      // agent_image_url) over any earlier stream cards frame.
      if (
        currentTurnRef.current &&
        Array.isArray(envelope?.cards) &&
        envelope.cards.length > 0
      ) {
        currentTurnRef.current.cards = envelope.cards as PropertyCard[];
      }
      if (envelope?.answer_md && currentTurnRef.current) {
        const { msgId, prompt } = currentTurnRef.current;
        const incoming = envelope.answer_md as string;
        setMessages((prev) => {
          const idx = prev.findIndex((m) => m.id === msgId);
          if (idx === -1) {
            // No token frames arrived yet — create the bubble now from the envelope
            return [
              ...prev,
              {
                id: msgId,
                role: "assistant" as const,
                content: incoming,
                isStreaming: true,
                userPrompt: prompt,
                timestamp: new Date(),
              },
            ];
          }
          const existing = prev[idx].content || "";
          // A worksheet-only envelope must not overwrite the streamed
          // yield narrative — that is what made reload look "wrong".
          const keepStream =
            Boolean(existing) &&
            ((isYieldWorksheetOnly(incoming) && !isYieldWorksheetOnly(existing)) ||
              (isYieldPublicStub(incoming) &&
                !isYieldPublicStub(existing) &&
                existing.length > incoming.length));
          const content = keepStream ? existing : incoming;
          return prev.map((m, i) => (i === idx ? { ...m, content } : m));
        });
      }
      return;
    }

    if (isDoneFrame(frame)) {
      finishTurn();
      return;
    }
  }

  function finishTurn() {
    setIsStreaming(false);
    setLoadingStatus("");
    const turn = currentTurnRef.current;
    if (!turn) return;

    const durationMs = resolveTurnDurationMs(
      turn.id,
      Date.now() - turn.startedAt,
    );

    const suggestions = parseEnvelopeSuggestions(
      useChatStore.getState().envelope as Record<string, unknown> | null,
    );

    // Snapshot this turn's pipeline steps before reset() clears them, so the
    // collapsible "Thought for Xs" panel persists on the finished bubble.
    const turnSteps = useChatStore.getState().getTurnRecord(turn.id)?.steps ?? [];

    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === turn.msgId);
      if (idx === -1) {
        // Message was never created (no tokens, no result envelope yet)
        // Only add a bubble if there are cards or some content to show
        if (!turn.cards?.length) return prev;
        return [
          ...prev,
          {
            id: turn.msgId,
            role: "assistant" as const,
            content: "",
            isStreaming: false,
            cards: turn.cards,
            searchUrl: turn.searchUrl ?? undefined,
            appliedFilters: turn.appliedFilters ?? undefined,
            userPrompt: turn.prompt,
            turnId: turn.id,
            durationMs: durationMs > 0 ? durationMs : undefined,
            timestamp: new Date(),
            suggestions: suggestions.length ? suggestions : [],
            steps: turnSteps.length ? turnSteps : undefined,
          },
        ];
      }
      return prev.map((m, i) =>
        i === idx
          ? {
              ...m,
              isStreaming: false,
              turnId: turn.id,
              durationMs: durationMs > 0 ? durationMs : undefined,
              ...(turn.cards?.length
                ? {
                    cards: turn.cards,
                    searchUrl: turn.searchUrl ?? undefined,
                    appliedFilters: turn.appliedFilters ?? undefined,
                  }
                : {}),
              suggestions: suggestions.length ? suggestions : [],
              steps: turnSteps.length ? turnSteps : m.steps,
              timestamp: new Date(),
            }
          : m,
      );
    });

    currentTurnRef.current = null;
    useChatStore.getState().reset();
  }

  // ── Public actions ───────────────────────────────────────────────────────

  const sendMessage = useCallback(
    async (
      text: string,
      opts: { skipUserAppend?: boolean; focusedPropertyIds?: number[] | null } = {},
    ) => {
      const prompt = text.trim();
      if (!prompt || isStreaming) return;
      if (useChatStore.getState().pendingHitl.length > 0) return;

      const turnId = useChatStore.getState().startTurn({ transportMode: transportRef.current });
      const msgId = randomUUID();

      if (!opts.skipUserAppend) {
        appendMessage("user", prompt);
      }
      setIsStreaming(true);
      setLoadingStatus("Thinking…");

      currentTurnRef.current = {
        id: turnId,
        prompt,
        msgId,
        startedAt: Date.now(),
        cards: null,
        searchUrl: null,
        appliedFilters: null,
        runId: null,
      };

      try {
        // Buyer preferences are a signed-in-only feature — guests never get
        // the "For You" panel / Preferences dialog in the UI, so never
        // forward stale/leftover preferences for a guest session either.
        // For authenticated users, forward preferences once set regardless
        // of personalizationEnabled — see selectOutgoingBuyerPreferences.
        const buyerPrefs = useAuthStore.getState().isGuest
          ? null
          : (selectOutgoingBuyerPreferences(usePrefsStore.getState()) as
              | Record<string, unknown>
              | null);

        const focusedIds = Array.isArray(opts.focusedPropertyIds)
          ? opts.focusedPropertyIds
          : [];

        if (transportRef.current === "ws" && wsRef.current?.isOpen()) {
          wsRef.current.sendUserMessage(
            prompt,
            buyerPrefs ?? undefined,
            undefined,
            focusedIds,
          );
          return; // done frame arrives via handleFrame
        }
        const abort = new AbortController();
        sseAbortRef.current = abort;
        await sendSSE({
          prompt,
          sessionId,
          userId,
          accessToken,
          buyerPreferences: buyerPrefs,
          sessionProfile: useSessionProfileStore.getState().profile,
          focusedPropertyIds: focusedIds,
          signal: abort.signal,
          onFrame: handleFrame,
        });
        sseAbortRef.current = null;
        if (abort.signal.aborted) return;
        if (currentTurnRef.current) finishTurn();
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return;
        const msg = err instanceof Error ? err.message : "Connection error";
        if (currentTurnRef.current) {
          appendMessage("assistant", `Connection error: ${msg}`, {
            userPrompt: prompt,
            isStreaming: false,
          });
          currentTurnRef.current = null;
        }
        setIsStreaming(false);
        setLoadingStatus("");
      }
    },
    [isStreaming, sessionId, userId, accessToken],
  );

  const cancelResponse = useCallback(() => {
    const turn = currentTurnRef.current;
    const runId = turn?.runId ?? null;
    if (transportRef.current === "ws" && wsRef.current?.isOpen()) {
      try {
        wsRef.current.sendCancel(runId);
      } catch {
        /* ignore */
      }
    } else {
      try {
        sseAbortRef.current?.abort();
      } catch {
        /* ignore */
      }
      sseAbortRef.current = null;
      if (runId) {
        postCancelRun(runId, sessionId, accessToken);
      }
    }
    if (turn) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === turn.msgId
            ? {
                ...m,
                isStreaming: false,
                content: m.content || "",
                statusText: m.content ? undefined : "Stopped",
              }
            : m,
        ),
      );
    }
    currentTurnRef.current = null;
    setIsStreaming(false);
    setLoadingStatus("");
    useChatStore.getState().reset();
  }, [sessionId, accessToken]);

  const resumeHitl = useCallback(
    async (interruptId: string, decisions: unknown[]) => {
      useChatStore.getState().clearHitl(interruptId);
      const chosen = decisions
        .map((item) => {
          if (!item || typeof item !== "object") return "";
          const decision = item as { query?: string; answer?: string; selected?: string };
          return (decision.query || decision.answer || decision.selected || "").trim();
        })
        .filter(Boolean);
      if (chosen.length) appendMessage("user", chosen.join(", "));

      // Make the resumed continuation stream into a visible assistant bubble.
      // On WS the paused turn is still in-flight (currentTurnRef set), so we
      // reuse it.  On SSE the pause emitted {done:true} which finished the
      // turn, so open a fresh streaming turn for the continuation.
      if (!currentTurnRef.current) {
        const turnId = useChatStore.getState().startTurn({ transportMode: transportRef.current });
        currentTurnRef.current = {
          id: turnId,
          prompt: "",
          msgId: randomUUID(),
          startedAt: Date.now(),
          cards: null,
          searchUrl: null,
          appliedFilters: null,
        };
      }
      setIsStreaming(true);
      setLoadingStatus("Resuming…");

      if (wsRef.current?.isOpen()) {
        wsRef.current.sendResume(interruptId, decisions);
        return; // continuation + done frame arrive via handleFrame
      }
      try {
        await resumeSSE({
          sessionId,
          interruptId,
          decisions,
          accessToken,
          onFrame: handleFrame,
        });
        if (currentTurnRef.current) finishTurn();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Resume failed";
        appendMessage("assistant", `Resume error: ${msg}`);
        currentTurnRef.current = null;
        setIsStreaming(false);
        setLoadingStatus("");
      }
    },
    [sessionId, accessToken],
  );

  const startNewChat = useCallback(async () => {
    // Cancel any in-flight turn before rotating the session.
    if (currentTurnRef.current || isStreaming) {
      const turn = currentTurnRef.current;
      const runId = turn?.runId ?? null;
      if (transportRef.current === "ws" && wsRef.current?.isOpen()) {
        try { wsRef.current.sendCancel(runId); } catch { /* ignore */ }
      } else {
        try { sseAbortRef.current?.abort(); } catch { /* ignore */ }
        sseAbortRef.current = null;
        if (runId) postCancelRun(runId, sessionId, accessToken);
      }
    }
    const prevSid = getStoredSessionId();
    // Read userId live from the store so a guest→auth transition uses the
    // authenticated user's ID rather than the stale guest anon ID captured
    // by the closure at the time the callback was created.
    const currentUserId = useAuthStore.getState().userId ?? userId;
    let freshId = randomUUID();
    try {
      const res = await newChatApi({ previousSessionId: prevSid, userId: currentUserId, carryOverLongTerm: true });
      if (res.session_id) freshId = res.session_id;
    } catch { /* use local uuid */ }

    setStoredSessionId(freshId);
    setSessionId(freshId);
    wsRef.current?.setSessionId?.(freshId);
    setMessages([]);
    setIsStreaming(false);
    setLoadingStatus("");
    setGuestBanner(null);
    useChatStore.getState().reset();
    useChatStore.getState().resetLead();
    currentTurnRef.current = null;
    return freshId;
  }, [isStreaming, sessionId, accessToken, userId]); // userId sourced live from store — no stale closure dep needed

  const loadSession = useCallback(async (sid: string) => {
    if (currentTurnRef.current || isStreaming) {
      const turn = currentTurnRef.current;
      const runId = turn?.runId ?? null;
      if (transportRef.current === "ws" && wsRef.current?.isOpen()) {
        try { wsRef.current.sendCancel(runId); } catch { /* ignore */ }
      } else {
        try { sseAbortRef.current?.abort(); } catch { /* ignore */ }
        sseAbortRef.current = null;
        if (runId) postCancelRun(runId, sessionId, accessToken);
      }
      currentTurnRef.current = null;
      setIsStreaming(false);
      setLoadingStatus("");
    }
    if (!sid) return;
    setStoredSessionId(sid);
    setSessionId(sid);
    wsRef.current?.setSessionId?.(sid);
    setMessages([]);
    setIsStreaming(false);
    setLoadingStatus("Loading session…");
    useChatStore.getState().reset();
    useChatStore.getState().resetLead();
    currentTurnRef.current = null;

    const restore = await getSessionRestore(sid, { limit: 30 });
    if (!restore.ok) {
      // Couldn't reach the server — don't leave the panel blank silently.
      setLoadingStatus("");
      toast.error("Couldn't load this session. Please try again.");
      return;
    }
    if (restore.turns.length > 0) {
      setMessages(buildMessagesFromTurns(restore.turns));
    } else if (restore.messages.length > 0) {
      setMessages(buildMessagesFromHistory(restore.messages));
    }
    setLoadingStatus("");
  }, [isStreaming, sessionId, accessToken]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleForgetSession = useCallback(
    async (sid: string) => {
      // Never pass user_id — backend LTM cascade would wipe the whole user.
      await forgetSession(sid);
      if (sid === sessionId) await startNewChat();
    },
    [sessionId, startNewChat],
  );

  /**
   * Clear-all after the rail has already forgotten each listed session.
   * Guests: hard-wipe current sid STM + anon LTM, drop tab session key, mint fresh chat.
   * Authenticated: mint a fresh chat only (prefs / LTM stay).
   */
  const handleForgetAllConversations = useCallback(async () => {
    const { isGuest: guestNow, userId: liveUserId } = useAuthStore.getState();
    const currentSid = getActiveSessionId() || sessionId;

    if (guestNow && currentSid) {
      await forgetAll(currentSid, { userId: liveUserId ?? undefined });
      setStoredSessionId(null);
    }

    await startNewChat();
  }, [sessionId, startNewChat]);

  const dismissGuestBanner = useCallback(() => setGuestBanner(null), []);

  const triggerAgentClickBanner = useCallback(() => {
    // Read from store to avoid stale closure — this callback may be passed
    // to WS/SSE handlers that captured it before auth settled.
    if (useAuthStore.getState().isGuest) setGuestBanner("agent_click");
  }, []);

  /** Remove any pending Mode A lead-capture form(s) from pendingHitl.
   *  Needed because reset() now preserves lead_capture frames across the done
   *  frame, so they must be cleared explicitly once submitted or dismissed. */
  function clearLeadCaptureForms() {
    const { pendingHitl, clearHitl } = useChatStore.getState();
    pendingHitl
      .filter((f) => (f as { sub_type?: string }).sub_type === "lead_capture")
      .forEach((f) => clearHitl(f.interrupt_id));
  }

  /** Mode A: submit buyer contact details via WS or REST fallback */
  const sendLeadCaptureSubmit = useCallback(
    async (data: import("@/components/leads").LeadSubmitData) => {
      const ws = wsRef.current;
      const payload = {
        type: "lead_capture_submit" as const,
        buyer_name: data.buyer_name,
        buyer_email: data.buyer_email,
        buyer_phone: data.buyer_phone,
        property_ids: data.property_ids,
        ...(data.message_override ? { message_override: data.message_override } : {}),
        ...(data.message_html_override ? { message_html_override: data.message_html_override } : {}),
        ...(data.from_email ? { from_email: data.from_email } : {}),
        ...(data.to_email ? { to_email: data.to_email } : {}),
      };
      const sent = ws?.sendRaw?.(payload) ?? false;
      if (!sent) {
        await fetch("/api/leads/submit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            ui_surface: data.ui_surface ?? "lead_capture_form",
            buyer_name: data.buyer_name,
            buyer_email: data.buyer_email,
            buyer_phone: data.buyer_phone,
            property_ids: data.property_ids,
            ...(data.message_override ? { message_override: data.message_override } : {}),
            ...(data.message_html_override ? { message_html_override: data.message_html_override } : {}),
            ...(data.from_email ? { from_email: data.from_email } : {}),
            ...(data.to_email ? { to_email: data.to_email } : {}),
          }),
        });
      }
      useChatStore.getState().setLeadCaptureStatus("completed");
      clearLeadCaptureForms();
    },
    [sessionId],
  );

  /** Dismiss the lead offer */
  const sendLeadDismiss = useCallback(() => {
    wsRef.current?.sendRaw?.({ type: "lead_dismiss" });
    useChatStore.getState().setLeadCaptureStatus("dismissed");
    useChatStore.getState().clearAgentContacts();
    clearLeadCaptureForms();
  }, []);

  // Per-message lead actions ─────────────────────────────────────────────
  // Each handler is scoped to ONE assistant message's property cards and
  // persists its result server-side (Redis) keyed by that turn_id, so the
  // agent list / submitted state survives a page refresh.
  const leadBusyRef = useRef<Set<string>>(new Set());

  /** Mode B: fetch + persist agent contacts for one message's properties. */
  const showAgentsForMessage = useCallback(
    async (msg: Message) => {
      if (leadBusyRef.current.has(msg.id) || msg.agentContacts?.length) return;
      const propertyIds = cardPropertyIds(msg.cards);
      if (!propertyIds.length) {
        toast.error("No properties found to look up agents for.");
        return;
      }
      leadBusyRef.current.add(msg.id);
      try {
        const res = await fetch("/api/leads/agents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            turn_id: msg.turnId ?? null,
            property_ids: propertyIds,
            max_agents: 10,
          }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as {
          agents: AgentContact[];
          coverage?: AgentCoverage;
        };
        const agents = data.agents ?? [];
        updateMessage(msg.id, (m) => ({
          ...m,
          agentContacts: agents,
          agentCoverage: data.coverage,
          leadStatus: "agents_shown",
        }));
        if (!agents.length) toast.message("No listing agents found for these properties.");
      } catch (err: unknown) {
        const m = err instanceof Error ? err.message : "Unknown error";
        toast.error(`Could not load agent contacts: ${m}`);
      } finally {
        leadBusyRef.current.delete(msg.id);
      }
    },
    [sessionId],
  );

  /** Mode B: dismiss the agent contact list for one message (persisted per turn). */
  const dismissAgentsForMessage = useCallback(
    async (msg: Message) => {
      if (!msg.agentContacts?.length) return;
      updateMessage(msg.id, (m) => ({
        ...m,
        agentContacts: undefined,
        leadStatus: "dismissed",
      }));
      const turnId = msg.turnId;
      if (!sessionId || !turnId) return;
      try {
        await fetch("/api/leads/agents/dismiss", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, turn_id: turnId }),
        });
      } catch (err: unknown) {
        const m = err instanceof Error ? err.message : "Unknown error";
        toast.error(`Could not save dismiss state: ${m}`);
      }
    },
    [sessionId],
  );

  /** Mode A: submit buyer details for one message's properties — notifies every
   *  listing agent for those properties once (Email/WhatsApp via Laravel). */
  const submitLeadForMessage = useCallback(
    async (msg: Message, data: import("@/components/leads").LeadSubmitData) => {
      const propertyIds = data.property_ids?.length ? data.property_ids : cardPropertyIds(msg.cards);
      const res = await fetch("/api/leads/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          turn_id: msg.turnId ?? null,
          buyer_name: data.buyer_name,
          buyer_email: data.buyer_email,
          buyer_phone: data.buyer_phone,
          property_ids: propertyIds,
          ui_surface: data.ui_surface ?? "lead_capture_form",
          ...(data.message_override ? { message_override: data.message_override } : {}),
          ...(data.message_html_override ? { message_html_override: data.message_html_override } : {}),
          ...(data.from_email ? { from_email: data.from_email } : {}),
          ...(data.to_email ? { to_email: data.to_email } : {}),
        }),
      });
      if (!res.ok) {
        // Surface to the inline form so it shows its error state and stays open.
        throw new Error(`HTTP ${res.status}`);
      }
      updateMessage(msg.id, (m) => ({ ...m, leadStatus: "submitted" }));
    },
    [sessionId],
  );

  /** Mode A: submit buyer details for a single sidebar property card. */
  const submitLeadForProperty = useCallback(
    async (propertyId: number, data: import("@/components/leads").LeadSubmitData) => {
      const propertyIds = data.property_ids?.length ? data.property_ids : [propertyId];
      const res = await fetch("/api/leads/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          turn_id: null,
          buyer_name: data.buyer_name,
          buyer_email: data.buyer_email,
          buyer_phone: data.buyer_phone,
          property_ids: propertyIds,
          ui_surface: data.ui_surface ?? "property_card_sidebar",
          ...(data.message_override ? { message_override: data.message_override } : {}),
          ...(data.message_html_override ? { message_html_override: data.message_html_override } : {}),
          ...(data.from_email ? { from_email: data.from_email } : {}),
          ...(data.to_email ? { to_email: data.to_email } : {}),
        }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const body = (await res.json()) as { confirmation_text?: string };
      if (body.confirmation_text) {
        toast.success(body.confirmation_text);
      }
    },
    [sessionId],
  );

  return {
    messages,
    isStreaming,
    loadingStatus,
    sessionId,
    guestBanner,
    searchCount,
    sendMessage,
    cancelResponse,
    resumeHitl,
    startNewChat,
    loadSession,
    handleForgetSession,
    handleForgetAllConversations,
    dismissGuestBanner,
    triggerAgentClickBanner,
    sendLeadCaptureSubmit,
    sendLeadDismiss,
    showAgentsForMessage,
    dismissAgentsForMessage,
    submitLeadForMessage,
    submitLeadForProperty,
  };
}
