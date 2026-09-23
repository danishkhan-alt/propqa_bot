/**
 * Zustand chat store — port of the vanilla JS chatStore with full TypeScript types.
 *
 * Manages:
 *  - transportMode, lastTurnId, steps, pendingHitl, envelope, recallHits
 *  - stepsByTurn (per-bubble pipeline history for restored sessions)
 *  - contextUsage (Phase 2026 context window manager)
 *  - activeFlowId / activeFlowStages (F1–F23 routing)
 *  - carryOverLongTerm, lastCompactedAt, health
 */

import { create } from "zustand";
import type { AgentContact } from "@/api/frames";
import { randomUUID } from "@/lib/uuid";

// ── Flow registry ──────────────────────────────────────────────────────────

export const FLOWS_REGISTRY: Record<string, string[]> = {
  F1:  ["boot","think","enhance","propqa_core","commit","result"],
  F2:  ["boot","think","enhance","reason","propqa_core","commit","result"],
  F3:  ["boot","think","enhance","rebuild","propqa_core","commit","result"],
  F4:  ["boot","think","enhance","reason","rebuild","propqa_core","commit","result"],
  F5:  ["boot","think","enhance","reason","propqa_core","reason","rebuild","commit","result"],
  F6:  ["boot","think","rebuild","enhance","reason","propqa_core","commit","result"],
  F7:  ["boot","think","enhance","reason","propqa_core","rebuild","propqa_core","commit","result"],
  F8:  ["boot","think","enhance","propqa_core","reason","hitl","qa","rebuild","commit","result"],
  F9:  ["boot","think","enhance","reason","hitl","qa","propqa_core","rebuild","commit","result"],
  F10: ["boot","think","enhance","propqa_core","reason","rebuild","hitl","commit","result"],
  F11: ["boot","think","enhance","reason","propqa_core","hitl","rebuild","propqa_core","commit","result"],
  F12: ["boot","think","enhance","suggest","qa","propqa_core","commit","result"],
  F13: ["boot","think","enhance","reason","suggest","qa","propqa_core","commit","result"],
  F14: ["boot","think","suggest","qa","rebuild","propqa_core","commit","result"],
  F15: ["boot","think","enhance","propqa_core","commit","result","suggest"],
  F16: ["boot","think","research_start","research_plan","research_progress","propqa_core","research_summarise","extract_knowledge","research_done","commit","result"],
  F17: ["boot","think","research_start","research_plan","research_progress","propqa_core","research_summarise","hitl","research_done","commit","result"],
  F18: ["boot","think","research_start","research_plan","research_progress","propqa_core","rebuild","research_progress","research_summarise","research_done","commit","result"],
  F19: ["boot","think","enhance","research_start","research_progress","propqa_core","research_summarise","commit","result"],
  F20: ["boot","think","enhance","propqa_core","reason","extract_knowledge","commit","result"],
  F21: ["boot","think","extract_knowledge","enhance","reason","propqa_core","rebuild","commit","result"],
  F22: ["boot","think","enhance","propqa_core","extract_knowledge","hitl","commit","result"],
  F23: ["boot","think","extract_knowledge","suggest","rebuild","propqa_core","commit","result"],
};

export async function syncFlowsRegistry() {
  try {
    const res = await fetch("/api/flows");
    if (!res.ok) return;
    const data = await res.json();
    for (const cat of Object.values(data) as Array<{ flows?: Array<{ id: string; stages: string[] }> }>) {
      if (!Array.isArray(cat.flows)) continue;
      for (const f of cat.flows) {
        if (f.id && Array.isArray(f.stages)) {
          FLOWS_REGISTRY[f.id] = f.stages;
        }
      }
    }
  } catch {
    // non-fatal — hardcoded registry serves as fallback
  }
}

// ── Types ──────────────────────────────────────────────────────────────────

export interface StepFrame {
  type: "step";
  step: string;
  status?: string;
  ms?: number;
  /**
   * True when this step ran concurrently with its siblings. `ms` is still the
   * step's own duration, so summing parallel frames would over-count the turn;
   * the enclosing stage emits the wall-clock frame instead.
   */
  parallel?: boolean;
  payload?: Record<string, unknown>;
}

export interface HitlFrame {
  type: "hitl";
  interrupt_id: string;
  [key: string]: unknown;
}

export interface SuggestionOut {
  label: string;
  rebuilt_query: string;
  rationale?: string;
  confidence?: number;
}

export interface ResultEnvelope {
  answer_md?: string;
  cards?: PropertyCard[];
  metadata?: {
    search_url?: string;
    total_matches?: number;
    shown?: number;
    strict_search_url?: string;
    applied_filters?: string[];
    persona_signal?: {
      persona?: string | null;
      segment?: string | null;
      homepage_variant?: string | null;
      guided_explainer?: boolean;
    };
  };
  suggestions?: SuggestionOut[];
  follow_ups?: string[];
  [key: string]: unknown;
}

export interface PropertyCard {
  id?: string | number;
  title?: string;
  price?: string | number;
  location?: string;
  beds?: number | string;
  baths?: number | string;
  area?: number | string;
  image_url?: string;
  url?: string;
  slug?: string;
  [key: string]: unknown;
}

export interface TurnRecord {
  steps: StepFrame[];
  envelope: ResultEnvelope | null;
  recallHits: unknown[];
  cardsRendered: boolean;
}

export interface ContextUsage {
  prompt_tokens?: number;
  budget?: number;
  fraction?: number;
  compacted_turns?: number;
  last_compaction_ts?: number;
  [key: string]: unknown;
}

export interface HealthFlags {
  cognitive_pipeline?: boolean;
  hitl_transport?: string;
  result_envelope?: boolean;
  skills_registry?: boolean;
  ltm_enabled?: boolean;
  ws_mounted?: boolean;
  memory_backend?: string;
  [key: string]: unknown;
}

// ── Lead state ─────────────────────────────────────────────────────────────

export interface LeadState {
  /** Accumulated readiness score (0.0 – 1.0) for the current session */
  leadReadinessScore: number;
  /** True when the hard threshold (0.40) has been crossed and offer not yet shown */
  leadOfferReady: boolean;
  /** True when the soft threshold (0.30) has been crossed */
  leadSoftReady: boolean;
  /** "pending" | "completed" | "dismissed" */
  leadCaptureStatus: "pending" | "completed" | "dismissed";
  /** LLM-decided offer mode for this session: "none" | "A" | "B" | "both" */
  leadRecommendedMode: "none" | "A" | "B" | "both";
  /** Mode B agent contact cards waiting to be rendered */
  pendingAgentContacts: AgentContact[];
  /** The note accompanying Mode B cards */
  agentContactsNote: string | null;
}

export interface ChatState {
  transportMode: "ws" | "sse" | null;
  lastTurnId: string | null;
  steps: StepFrame[];
  stepsByTurn: Map<string, TurnRecord>;
  pendingHitl: HitlFrame[];
  envelope: ResultEnvelope | null;
  /** Latest persona_signal from envelope.metadata (investor/buyer/renter). */
  personaSignal: NonNullable<ResultEnvelope["metadata"]>["persona_signal"] | null;
  recallHits: unknown[];
  cardsRenderedThisTurn: boolean;
  health: { flags: HealthFlags; status: string; version: string } | null;
  contextUsage: ContextUsage | null;
  lastCompactedAt: number | null;
  carryOverLongTerm: boolean;
  activeFlowId: string | null;
  activeFlowStages: string[];
  // Lead generation state
  lead: LeadState;
  // Actions
  setTransportMode: (mode: "ws" | "sse") => void;
  setHealth: (health: ChatState["health"]) => void;
  startTurn: (opts?: { transportMode?: "ws" | "sse" }) => string;
  pushStep: (frame: StepFrame) => void;
  setEnvelope: (env: ResultEnvelope | null) => void;
  getTurnRecord: (turnId: string) => TurnRecord | null;
  seedTurnRecord: (turnId: string, data: Partial<TurnRecord>) => void;
  addHitl: (frame: HitlFrame) => void;
  clearHitl: (interruptId: string) => void;
  noteCardsRendered: () => void;
  setContextUsage: (usage: ContextUsage | null) => void;
  setLastCompactedAt: (ts: number | null) => void;
  setCarryOverLongTerm: (value: boolean) => void;
  setActiveFlow: (flowId: string, stages?: string[]) => void;
  // Lead actions
  setLeadReadiness: (
    score: number,
    offerReady: boolean,
    softReady: boolean,
    recommendedMode?: LeadState["leadRecommendedMode"],
  ) => void;
  setAgentContacts: (agents: AgentContact[], note?: string | null) => void;
  clearAgentContacts: () => void;
  setLeadCaptureStatus: (status: LeadState["leadCaptureStatus"]) => void;
  /** Inject a synthetic Mode A lead-capture HITL frame so the form renders
   *  immediately without a backend round-trip. */
  addLocalLeadCapture: (propertyIds?: number[], searchSummary?: string) => void;
  resetLead: () => void;
  reset: () => void;
}

// ── Store ──────────────────────────────────────────────────────────────────

const _initialLeadState: LeadState = {
  leadReadinessScore: 0,
  leadOfferReady: false,
  leadSoftReady: false,
  leadCaptureStatus: "pending",
  leadRecommendedMode: "none",
  pendingAgentContacts: [],
  agentContactsNote: null,
};

export const useChatStore = create<ChatState>((set, get) => ({
  transportMode: null,
  lastTurnId: null,
  steps: [],
  stepsByTurn: new Map(),
  pendingHitl: [],
  envelope: null,
  personaSignal: null,
  recallHits: [],
  cardsRenderedThisTurn: false,
  health: null,
  contextUsage: null,
  lastCompactedAt: null,
  carryOverLongTerm: true,
  activeFlowId: null,
  lead: { ..._initialLeadState },
  activeFlowStages: [],

  setTransportMode: (mode) => set({ transportMode: mode }),

  setHealth: (health) => set({ health }),

  startTurn: (opts = {}) => {
    const turnId = randomUUID();
    const stepsByTurn = new Map(get().stepsByTurn);
    stepsByTurn.set(turnId, { steps: [], envelope: null, recallHits: [], cardsRendered: false });
    set({
      transportMode: opts.transportMode ?? get().transportMode,
      lastTurnId: turnId,
      steps: [],
      envelope: null,
      recallHits: [],
      cardsRenderedThisTurn: false,
      stepsByTurn,
      activeFlowId: null,
      activeFlowStages: [],
    });
    return turnId;
  },

  pushStep: (frame) => {
    const lastTurnId = get().lastTurnId;
    const stepsByTurn = new Map(get().stepsByTurn);
    const record = stepsByTurn.get(lastTurnId ?? "") ?? { steps: [], envelope: null, recallHits: [], cardsRendered: false };
    const newRecord = { ...record, steps: [...record.steps, frame] };

    let recallHits = get().recallHits;
    if (frame.step === "think" && frame.payload?.recall_hits != null) {
      const hits = frame.payload.recall_hits;
      recallHits = Array.isArray(hits) ? hits : [];
      newRecord.recallHits = recallHits;
    }

    if (lastTurnId) stepsByTurn.set(lastTurnId, newRecord);
    set({ steps: [...get().steps, frame], stepsByTurn, recallHits });
  },

  setEnvelope: (env) => {
    const lastTurnId = get().lastTurnId;
    const stepsByTurn = new Map(get().stepsByTurn);
    if (lastTurnId) {
      const record = stepsByTurn.get(lastTurnId) ?? { steps: [], envelope: null, recallHits: [], cardsRendered: false };
      stepsByTurn.set(lastTurnId, { ...record, envelope: env ?? null });
    }
    const signal = env?.metadata?.persona_signal ?? null;
    set({ envelope: env ?? null, stepsByTurn, personaSignal: signal });
  },

  getTurnRecord: (turnId) => get().stepsByTurn.get(turnId) ?? null,

  seedTurnRecord: (turnId, data) => {
    if (!turnId) return;
    const stepsByTurn = new Map(get().stepsByTurn);
    if (stepsByTurn.has(turnId)) return; // never overwrite live data
    stepsByTurn.set(turnId, {
      steps: data.steps ?? [],
      envelope: data.envelope ?? null,
      recallHits: data.recallHits ?? [],
      cardsRendered: false,
    });
    set({ stepsByTurn });
  },

  addHitl: (frame) => {
    if (!frame?.interrupt_id) return;
    const existing = get().pendingHitl;
    const idx = existing.findIndex(f => f.interrupt_id === frame.interrupt_id);
    const next = idx >= 0
      ? existing.map((f, i) => i === idx ? { ...frame } : f)
      : [...existing, frame];
    set({ pendingHitl: next });
  },

  clearHitl: (interruptId) => {
    set({ pendingHitl: get().pendingHitl.filter(f => f.interrupt_id !== interruptId) });
  },

  noteCardsRendered: () => {
    if (get().cardsRenderedThisTurn) return;
    const lastTurnId = get().lastTurnId;
    const stepsByTurn = new Map(get().stepsByTurn);
    if (lastTurnId) {
      const record = stepsByTurn.get(lastTurnId);
      if (record) stepsByTurn.set(lastTurnId, { ...record, cardsRendered: true });
    }
    set({ cardsRenderedThisTurn: true, stepsByTurn });
  },

  setContextUsage: (usage) => {
    if (!usage) { set({ contextUsage: null }); return; }
    const extra: Partial<ChatState> = { contextUsage: { ...usage } };
    if (typeof usage.last_compaction_ts === "number") extra.lastCompactedAt = usage.last_compaction_ts;
    set(extra);
  },

  setLastCompactedAt: (ts) => set({ lastCompactedAt: ts }),

  setCarryOverLongTerm: (value) => set({ carryOverLongTerm: value }),

  setActiveFlow: (flowId, stages) => {
    if (!flowId) return;
    const stageList = stages?.length ? stages : (FLOWS_REGISTRY[flowId] ?? []);
    set({ activeFlowId: flowId, activeFlowStages: stageList });
  },

  setLeadReadiness: (score, offerReady, softReady, recommendedMode) =>
    set((s) => ({
      lead: {
        ...s.lead,
        leadReadinessScore: score,
        leadOfferReady: offerReady,
        leadSoftReady: softReady,
        ...(recommendedMode ? { leadRecommendedMode: recommendedMode } : {}),
      },
    })),

  setAgentContacts: (agents, note = null) =>
    set((s) => ({ lead: { ...s.lead, pendingAgentContacts: agents, agentContactsNote: note ?? null } })),

  clearAgentContacts: () =>
    set((s) => ({ lead: { ...s.lead, pendingAgentContacts: [], agentContactsNote: null } })),

  setLeadCaptureStatus: (status) =>
    set((s) => ({ lead: { ...s.lead, leadCaptureStatus: status } })),

  addLocalLeadCapture: (propertyIds = [], searchSummary) => {
    const frame: HitlFrame = {
      type: "hitl",
      interrupt_id: "local-lead-capture",
      sub_type: "lead_capture",
      mode: "A",
      fields: [
        { name: "buyer_name",  label: "Your Name",       type: "text",  required: true },
        { name: "buyer_email", label: "Email Address",    type: "email", required: true },
        { name: "buyer_phone", label: "Phone / WhatsApp", type: "tel",   required: true },
      ],
      context_summary: {
        ...(searchSummary ? { search_summary: searchSummary } : {}),
        ...(propertyIds.length ? { matched_property_ids: propertyIds } : {}),
      },
    };
    get().addHitl(frame);
    get().setLeadCaptureStatus("pending");
  },

  resetLead: () => set({ lead: { ..._initialLeadState } }),

  reset: () => set((s) => ({
    steps: [],
    // Preserve the Mode A lead-capture form across the done frame.  The
    // lead-capture HITL is emitted alongside the turn's ``done`` (it is NOT a
    // blocking graph interrupt), so clearing pendingHitl unconditionally here
    // wiped the form the instant it arrived — the user never saw it.  Regular
    // (blocking) HITL prompts still clear, since a turn cannot complete while
    // one is genuinely pending.
    pendingHitl: s.pendingHitl.filter(
      (f) => (f as { sub_type?: string }).sub_type === "lead_capture",
    ),
    envelope: null,
    personaSignal: null,
    recallHits: [],
    lastTurnId: null,
    cardsRenderedThisTurn: false,
    stepsByTurn: new Map(),
    contextUsage: null,
    activeFlowId: null,
    activeFlowStages: [],
    // lead is intentionally NOT cleared here — agent contacts and lead capture
    // form must persist across the done frame so React can render them.
    // Lead state is reset explicitly at session boundaries via resetLead().
    // Intentionally preserve: carryOverLongTerm, lastCompactedAt, transportMode, health
  })),
}));

// Singleton ref for non-React code (transport layer)
export const chatStore = useChatStore;
