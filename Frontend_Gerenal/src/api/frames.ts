/**
 * Frame type definitions and guards for the SSE/WS protocol.
 * Mirrors the vanilla JS frames.js logic with full TypeScript types.
 */

import { randomUUID } from "@/lib/uuid";

export interface TokenFrame { type: "token"; token: string; }
export interface ReplyFrame { type: "reply"; reply: Record<string, unknown>; }
export interface StepFrame {
  type: "step";
  step: string;
  status?: string;
  ms?: number;
  /** Ran concurrently with sibling steps — excluded from the pipeline total. */
  parallel?: boolean;
  payload?: Record<string, unknown>;
}
export interface CardsFrame {
  type: "cards";
  cards: unknown[];
  search_url?: string;
  total_matches?: number;
  shown?: number;
  applied_filters?: string[];
  strict_search_url?: string;
}
export interface HitlFrame { type: "hitl"; interrupt_id: string; [key: string]: unknown; }
export interface ResultFrame { type: "result"; envelope: Record<string, unknown>; }
export interface DoneFrame { type: "done"; cancelled?: boolean; }
export interface CancelledFrame {
  type: "cancelled";
  run_id?: string;
  message?: string;
}
export interface ErrorFrame { type: "error"; code?: string; message: string; done?: boolean; retry_after?: number; }

// ── Lead generation frames ───────────────────────────────────────────────────

/** Agent contact info (Mode B) — emitted by lead_offer_node */
export interface AgentContact {
  agent_id: number;
  agent_name: string;
  company_name?: string | null;
  phone?: string | null;
  mobile?: string | null;
  whatsapp?: string | null;
  email?: string | null;
  verification_status: string;
  experience_years?: number | null;
  specialization_areas?: string[];
  property_ids?: number[];
}

export interface AgentContactsFrame {
  type: "agent_contacts";
  mode: "B";
  session_id?: string;
  agents: AgentContact[];
  note?: string;
}

/** Lead capture HITL form (Mode A) — emitted as a hitl frame with sub_type="lead_capture" */
export interface LeadCaptureField {
  name: string;
  label: string;
  type: "text" | "email" | "tel";
  required?: boolean;
}

export interface LeadCaptureHitlFrame extends HitlFrame {
  sub_type: "lead_capture";
  mode: "A";
  task_id?: string;
  prompt?: string;
  fields: LeadCaptureField[];
  context_summary?: {
    search_summary?: string;
    matched_property_ids?: number[];
  };
}

export type ServerFrame = TokenFrame | StepFrame | CardsFrame | HitlFrame | ResultFrame | DoneFrame | CancelledFrame | ErrorFrame | AgentContactsFrame | ReplyFrame;

export function isAgentContactsFrame(f: unknown): f is AgentContactsFrame {
  return !!f && typeof f === "object" && (f as AgentContactsFrame).type === "agent_contacts";
}

export function isLeadCaptureHitlFrame(f: unknown): f is LeadCaptureHitlFrame {
  return (
    !!f &&
    typeof f === "object" &&
    (f as LeadCaptureHitlFrame).type === "hitl" &&
    (f as LeadCaptureHitlFrame).sub_type === "lead_capture"
  );
}

export function isCancelledFrame(f: unknown): f is CancelledFrame {
  return !!f && typeof f === "object" && (f as CancelledFrame).type === "cancelled";
}

export function isReplyFrame(f: unknown): f is ReplyFrame {
  return !!f && typeof f === "object" && (f as ReplyFrame).type === "reply" && typeof (f as ReplyFrame).reply === "object";
}

export function isTokenFrame(f: unknown): f is TokenFrame {
  return !!f && typeof f === "object" && "token" in f && typeof (f as TokenFrame).token === "string";
}

export function isStepFrame(f: unknown): f is StepFrame {
  return !!f && typeof f === "object" && "step" in f && typeof (f as StepFrame).step === "string";
}

export function isCardsFrame(f: unknown): f is CardsFrame {
  return !!f && typeof f === "object" && "cards" in f && Array.isArray((f as CardsFrame).cards);
}

export function isHitlFrame(f: unknown): f is HitlFrame {
  return !!f && typeof f === "object" && "interrupt_id" in f;
}

export function isResultFrame(f: unknown): f is ResultFrame {
  return !!f && typeof f === "object" && "envelope" in f && !("token" in f) && !("cards" in f);
}

export function isDoneFrame(f: unknown): f is DoneFrame {
  if (!f || typeof f !== "object") return false;
  const o = f as Record<string, unknown>;
  // Normalized frame: { type: "done" }
  // Raw frame (edge case): { done: true }
  return o["type"] === "done" || (o["done"] === true && !("error" in o));
}

export function isErrorFrame(f: unknown): f is ErrorFrame {
  if (!f || typeof f !== "object") return false;
  const o = f as Record<string, unknown>;
  // Normalized frame: { type: "error", message: "..." }
  // Raw frame (edge case): { error: "..." }
  return o["type"] === "error" || (typeof o["error"] === "string");
}

/**
 * Normalise a backend HITL interrupt payload into a flat HitlFrame the
 * `HitlPrompt` component can render directly.
 *
 * The backend (both WS `_hitl_frame` and SSE `_sse_hitl_frame`) sends
 * `action_requests: [{ kind, title, options: [{ id, label, query }], default }]`.
 * `HitlPrompt` reads flat `prompt` + `options: [{ label, value, query }]`, so we
 * hoist the first action request onto the frame while preserving every raw
 * field (interrupt_id, review_configs, sub_type=lead_capture, etc.).
 */
function normaliseHitlFrame(
  event: Record<string, unknown>,
  interruptId: string,
): HitlFrame {
  const frame: HitlFrame = { type: "hitl", interrupt_id: interruptId, ...event };

  // Already flattened (or a lead-capture form) — nothing to hoist.
  if (Array.isArray((frame as Record<string, unknown>).options)) return frame;

  const requests = event.action_requests;
  if (!Array.isArray(requests) || requests.length === 0) return frame;
  const first = requests[0];
  if (!first || typeof first !== "object") return frame;
  const req = first as Record<string, unknown>;

  const rawOptions = Array.isArray(req.options) ? req.options : [];
  const options = rawOptions
    .map((o) => {
      if (!o || typeof o !== "object") return null;
      const opt = o as Record<string, unknown>;
      const value = typeof opt.id === "string" ? opt.id : typeof opt.value === "string" ? opt.value : "";
      const label = typeof opt.label === "string" ? opt.label : value;
      const query = typeof opt.query === "string" ? opt.query : undefined;
      if (!value && !label) return null;
      return { label, value: value || label, query };
    })
    .filter((o): o is { label: string; value: string; query: string | undefined } => o !== null);

  if (typeof req.title === "string" && !("prompt" in frame)) {
    (frame as Record<string, unknown>).prompt = req.title;
  }
  if (options.length > 0) {
    (frame as Record<string, unknown>).options = options;
  }
  (frame as Record<string, unknown>).multi_select = req.kind === "choose_many";
  return frame;
}

export function parseFrame(raw: string): ServerFrame | null {
  try {
    const obj = JSON.parse(raw);
    if (!obj || typeof obj !== "object") return null;
    return legacyEventToFrames(obj)[0] ?? null;
  } catch {
    return null;
  }
}

/**
 * Normalise a raw SSE/WS event dict into one or more canonical frames.
 * Preserves the exact logic from the original frames.js legacyEventToFrames.
 */
export function legacyEventToFrames(event: Record<string, unknown>): ServerFrame[] {
  if (!event || typeof event !== "object") return [];
  const frames: ServerFrame[] = [];

  if (event.type === "reply" && event.reply && typeof event.reply === "object") {
    frames.push({ type: "reply", reply: event.reply as Record<string, unknown> });
    return frames;
  }

  // ── Cancelled frame (Stop) — before generic done ─────────────────────────
  if (
    event.type === "cancelled" ||
    (event.cancelled === true && event.done === true)
  ) {
    frames.push({
      type: "cancelled",
      run_id: typeof event.run_id === "string" ? event.run_id : undefined,
      message: typeof event.message === "string" ? event.message : undefined,
    });
    return frames;
  }

  // ── WS-typed done frame: {"type":"done"} ──────────────────────────────────
  // The WebSocket transport sends {"type":"done"} while the SSE path sends
  // {"done":true}.  Handle the typed variant first so it is never misrouted.
  // Legacy cancel reused done + metadata.cancelled — treat as cancelled.
  if (event.type === "done") {
    const meta = event.metadata;
    const cancelled =
      event.cancelled === true ||
      (meta && typeof meta === "object" && (meta as Record<string, unknown>).cancelled === true);
    if (cancelled) {
      frames.push({
        type: "cancelled",
        run_id: typeof event.run_id === "string" ? event.run_id : undefined,
      });
      return frames;
    }
    frames.push({ type: "done" });
    return frames;
  }

  // ── Error frame ───────────────────────────────────────────────────────────
  // WS sends {"type":"error","message":"..."}, SSE sends {"error":"..."}.
  // Both must be normalised into an ErrorFrame so finishTurn() is triggered.
  const errorMsg =
    typeof event.error === "string"
      ? event.error
      : event.type === "error" && typeof event.message === "string"
      ? event.message
      : null;
  if (errorMsg !== null) {
    frames.push({
      type: "error",
      code: typeof event.code === "string" ? event.code : undefined,
      message: errorMsg,
      done: !!event.done,
      retry_after: typeof event.retry_after === "number" ? event.retry_after : undefined,
    });
    return frames;
  }

  // Step frame (cognitive pipeline stages)
  if (typeof event.step === "string") {
    const stepFrame: StepFrame = {
      type: "step",
      step: event.step,
      status: typeof event.status === "string" ? event.status : undefined,
      ms: typeof event.ms === "number" ? event.ms : undefined,
      parallel: event.parallel === true ? true : undefined,
      payload: event.payload && typeof event.payload === "object"
        ? event.payload as Record<string, unknown>
        : undefined,
    };
    if (typeof event.run_id === "string") {
      stepFrame.payload = { ...(stepFrame.payload || {}), run_id: event.run_id };
    }
    frames.push(stepFrame);
    return frames;
  }

  // Token / status may carry run_id on the first frame
  if (typeof event.status === "string" && typeof event.token !== "string" && !event.step) {
    frames.push({
      type: "step",
      step: "status",
      status: event.status,
      payload: typeof event.run_id === "string" ? { run_id: event.run_id } : undefined,
    });
    // Fall through only if we also need token — status-only returns.
    if (typeof event.token !== "string") return frames;
  }

  // Token frame
  if (typeof event.token === "string") {
    frames.push({ type: "token", token: event.token });
    return frames;
  }

  // Cards frame
  if (Array.isArray(event.cards)) {
    frames.push({
      type: "cards",
      cards: event.cards,
      search_url: typeof event.search_url === "string" ? event.search_url : undefined,
      total_matches: typeof event.total_matches === "number" ? event.total_matches : undefined,
      shown: typeof event.shown === "number" ? event.shown : undefined,
      applied_filters: Array.isArray(event.applied_filters) ? event.applied_filters as string[] : undefined,
      strict_search_url: typeof event.strict_search_url === "string" ? event.strict_search_url : undefined,
    });
    return frames;
  }

  // Agent contacts frame (Mode B lead generation)
  if (event.type === "agent_contacts" && Array.isArray(event.agents)) {
    frames.push({
      type: "agent_contacts",
      mode: "B",
      session_id: typeof event.session_id === "string" ? event.session_id : undefined,
      agents: event.agents as AgentContact[],
      note: typeof event.note === "string" ? event.note : undefined,
    });
    return frames;
  }

  // Lead-capture HITL frame from SSE path — may arrive without interrupt_id
  // when emitted by the SSE lead-gen hook (sub_type="lead_capture").
  if (
    event.type === "hitl" &&
    event.sub_type === "lead_capture" &&
    Array.isArray(event.fields)
  ) {
    const interruptId =
      typeof event.interrupt_id === "string" ? event.interrupt_id : randomUUID();
    frames.push({ type: "hitl", interrupt_id: interruptId, ...event });
    return frames;
  }

  // HITL frame
  if (typeof event.interrupt_id === "string") {
    frames.push(normaliseHitlFrame(event, event.interrupt_id));
    return frames;
  }

  // Result / envelope frame
  if (event.envelope && typeof event.envelope === "object") {
    frames.push({ type: "result", envelope: event.envelope as Record<string, unknown> });
    return frames;
  }

  // SSE legacy done frame: {"done":true}
  if (event.done === true) {
    frames.push({ type: "done" });
    return frames;
  }

  return frames;
}
