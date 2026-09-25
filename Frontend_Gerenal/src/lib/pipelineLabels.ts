/**
 * Shared cognitive-pipeline step labels + human-readable descriptions.
 *
 * Used by both the compact `PipelineSteps` pill bar and the Claude-style
 * `ThinkingPanel` timeline so a step name maps to the same wording everywhere.
 */

import type { StepFrame } from "@/store/chatStore";

/**
 * Short pill labels. An empty string means "hide this step from the UI"
 * (observability-only frames like context_usage / status / session_rotated).
 */
export const STEP_LABELS: Record<string, string> = {
  boot: "Init",
  think: "Thinking",
  plan: "Planning",
  classify: "Understanding",
  enhance: "Enhancing",
  rebuild: "Rebuilding",
  reason: "Reasoning",
  propqa_core: "Searching",
  search_domain: "Searching",
  wave_complete: "Cross-checking",
  grounding_check: "Verifying",
  answer_gate: "Verifying",
  coverage_check: "Verifying",
  verify_gate: "Verifying",
  recover: "Recovering",
  widen: "Widening",
  synthesize: "Composing",
  suggest: "Suggesting",
  hitl: "Review",
  qa: "Q&A",
  commit: "Saving",
  result: "Done",
  lead_readiness: "Matching",
  lead_offer_emitted: "Contacts",
  post_result_suggest: "Suggesting",
  extract_knowledge: "Learning",
  // Wrapper frame for the concurrent post-answer stage — its children
  // (suggest / extract_knowledge / lead_readiness) report their own frames.
  finalize_tail: "",
  research_start: "Research",
  research_plan: "Planning",
  research_progress: "Researching",
  research_summarise: "Summarising",
  research_done: "Research Done",
  scoring_investor: "Scoring",
  scoring_buyer_fit: "Scoring",
  scoring_rental: "Scoring",
  context_usage: "",
  compacted: "Compacted",
  session_rotated: "",
  status: "",
};

/** Title-cased fallback for any step name not in the map. */
export function labelForStep(step: string): string {
  const mapped = STEP_LABELS[step];
  if (mapped !== undefined) return mapped;
  return step.charAt(0).toUpperCase() + step.slice(1);
}

/**
 * Product-safe labels for domain ids in ``search_domain`` payloads.
 * Never expose snake_case ids or “Agent” wording in the thinking UI.
 */
export const DOMAIN_PRODUCT_LABELS: Record<string, string> = {
  property_search: "Searching listings",
  location_intel: "Checking areas",
  communities_intel: "Checking community guides",
  offplan_projects: "Checking off-plan projects",
  market_intel: "Checking market stats",
  rta_intel: "Checking transport",
};

/** Resolve a domain id to a product-safe thinking-panel label. */
export function productLabelForDomain(domain: unknown): string {
  const key = String(domain ?? "").trim().toLowerCase();
  const label =
    key && DOMAIN_PRODUCT_LABELS[key]
      ? DOMAIN_PRODUCT_LABELS[key]
      : "Searching listings and guides";
  return label;
}

/** Steps that are observability-only and never shown in the UI. */
export function isVisibleStep(step: string): boolean {
  return STEP_LABELS[step] !== "" && labelForStep(step) !== "";
}

/**
 * A full human sentence for one step, folding its `payload` in — this is what
 * the `ThinkingPanel` timeline shows for each row and what drives the live
 * header line ("Thinking… — Checking market stats").
 */
export function describeStep(frame: StepFrame): string {
  const p = (frame.payload ?? {}) as Record<string, unknown>;
  switch (frame.step) {
    case "boot":
      return "Initialising";
    case "think":
      return "Thinking through your question";
    case "classify":
      return "Understanding your question";
    case "plan": {
      const steps = Array.isArray(p.steps) ? p.steps : [];
      return p.multi_domain && steps.length > 1
        ? `Planning across ${steps.length} areas`
        : "Planning the approach";
    }
    case "enhance":
      return "Enhancing the query";
    case "reason":
      return "Reasoning about the best plan";
    case "rebuild":
      return "Refining your question";
    case "propqa_core":
      return "Searching listings and guides";
    case "search_domain": {
      const label = productLabelForDomain(p.domain);
      return label;
    }
    case "grounding_check":
      return "Checking the answer against the listings";
    case "answer_gate":
      return p.verdict === "repair"
        ? "Rewriting a claim the data does not support"
        : "Checking the answer against the data";
    case "coverage_check": {
      const missing = Array.isArray(p.missing) ? p.missing.length : 0;
      return missing > 0
        ? "Something was missing — fetching the rest"
        : "Checking that every part of the question was covered";
    }
    case "verify_gate":
      return "Checking the answer against the data";
    case "wave_complete": {
      const domains = Array.isArray(p.domains) ? p.domains.length : 0;
      return domains > 0
        ? `Got ${domains === 1 ? "a first result" : `${domains} results`} — checking what depends on them`
        : "Checking dependent searches";
    }
    case "recover": {
      const attempt = typeof p.attempt === "number" ? p.attempt : undefined;
      const base = "No exact match — refining the search";
      return attempt && attempt > 1 ? `${base} (attempt ${attempt})` : base;
    }
    case "widen": {
      const to = typeof p.to_days === "number" ? p.to_days : undefined;
      return to ? `Widening the time window to ${to} days` : "Widening the search";
    }
    case "synthesize":
      return "Composing your answer";
    case "suggest":
    case "post_result_suggest":
      return "Preparing follow-up suggestions";
    case "hitl":
      return "Waiting for your input";
    case "qa":
      return "Reviewing details";
    case "commit":
      return "Saving the result";
    case "result":
      return "Finalising the response";
    case "lead_readiness":
      return "Checking agent availability";
    case "lead_offer_emitted":
      return "Preparing agent contacts";
    case "extract_knowledge":
      return "Learning from this turn";
    case "research_start":
      return "Starting research";
    case "research_plan":
      return "Planning research";
    case "research_progress":
      return "Researching";
    case "research_summarise":
      return "Summarising findings";
    case "research_done":
      return "Research complete";
    case "scoring_investor":
      return "Scoring investment opportunity";
    case "scoring_buyer_fit":
      return "Scoring community fit";
    case "scoring_rental":
      return "Scoring rental suitability";
    default: {
      // Gracefully describe unknown "<base>_skipped" frames as "Base (skipped)"
      // and any other unknown step by de-snake-casing it.
      const base = frame.step.replace(/_skipped$/, "");
      const pretty = labelForStep(base).replace(/_/g, " ");
      return frame.step.endsWith("_skipped") ? `${pretty} (skipped)` : pretty.replace(/_/g, " ");
    }
  }
}
