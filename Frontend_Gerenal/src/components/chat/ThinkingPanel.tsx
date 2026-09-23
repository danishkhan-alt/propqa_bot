/**
 * ThinkingPanel — Claude-style collapsible "thinking" trace.
 *
 * While a turn is streaming it auto-expands and shows the live pipeline
 * timeline (classifying -> searching each domain -> recovering/widening ->
 * composing) so the user can see what is happening during the long
 * propqa_core search phase. When the turn completes it auto-collapses to a
 * "Thought for Xs" summary that stays expandable in history.
 */

import { useEffect, useState } from "react";
import { ChevronRight, ChevronDown, Loader2, Check, X, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDurationMs } from "@/lib/utils";
import { describeStep, isVisibleStep } from "@/lib/pipelineLabels";
import type { StepFrame } from "@/store/chatStore";

interface ThinkingPanelProps {
  steps: StepFrame[];
  isStreaming: boolean;
  durationMs?: number;
  className?: string;
}

const PIPELINE_SKIP_STEPS = new Set([
  "connected",
  "context_usage",
  "session_rotated",
  "status",
  "hitl_skipped",
]);

/**
 * Approximate the turn duration by adding up step durations.
 *
 * Steps flagged `parallel` overlapped with their siblings, so their durations
 * are not additive — the stage that fanned them out reports the wall-clock time
 * for all of them, and counting both would inflate the total well past the real
 * turn length.  Likewise ``propqa_core`` wraps nested ``search_domain`` frames;
 * counting both was measured to push "Thought for" toward ~2 minutes on slow
 * turns even when wall-clock was far lower.
 */
function sumStepMs(steps: StepFrame[]): number {
  const hasSearchDomain = steps.some(
    (s) => s.step === "search_domain" && (s.ms ?? 0) > 0,
  );
  return steps
    .filter((s) => {
      if (!s.ms || s.ms <= 0) return false;
      if (s.parallel || PIPELINE_SKIP_STEPS.has(s.step)) return false;
      if (s.step === "propqa_core" && hasSearchDomain) return false;
      return true;
    })
    .reduce((sum, s) => sum + (s.ms ?? 0), 0);
}

function StepGlyph({ status }: { status?: string }) {
  if (status === "running") {
    return <span className="inline-block size-1.5 shrink-0 animate-pulse rounded-full bg-blue-500" />;
  }
  if (status === "error") {
    return <X className="size-3 shrink-0 text-red-500" />;
  }
  if (status === "skipped") {
    return <span className="inline-block size-1.5 shrink-0 rounded-full bg-muted-foreground/40" />;
  }
  return <Check className="size-3 shrink-0 text-emerald-500" />;
}

export function ThinkingPanel({ steps, isStreaming, durationMs, className }: ThinkingPanelProps) {
  const [open, setOpen] = useState(isStreaming);

  // Auto-expand while streaming, auto-collapse once the turn finishes.
  useEffect(() => {
    setOpen(isStreaming);
  }, [isStreaming]);

  const visibleSteps = steps.filter((s) => {
    if (!s.step || !isVisibleStep(s.step)) return false;
    // propqa_core wraps nested search_domain frames — hide the wrapper so
    // the panel shows one product-safe row per domain, not N generic lines.
    if (s.step === "propqa_core" && steps.some((x) => x.step === "search_domain")) {
      return false;
    }
    return true;
  });
  if (visibleSteps.length === 0 && !isStreaming) return null;

  const lastStep = visibleSteps[visibleSteps.length - 1];
  const totalMs = durationMs && durationMs > 0 ? durationMs : sumStepMs(steps);

  const headerText = isStreaming
    ? lastStep
      ? `Thinking… — ${describeStep(lastStep)}`
      : "Thinking…"
    : totalMs > 0
      ? `Thought for ${formatDurationMs(totalMs)}`
      : "Thought process";

  return (
    <div className={cn("w-full rounded-lg border border-[#E8ECF3] bg-white text-xs text-[#141B34]", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left text-[#747288] transition-colors hover:text-[#141B34]"
        aria-expanded={open}
      >
        {open ? <ChevronDown className="size-3.5 shrink-0" /> : <ChevronRight className="size-3.5 shrink-0" />}
        {isStreaming ? (
          <Loader2 className="size-3.5 shrink-0 animate-spin text-[#1B60F4]" />
        ) : (
          <Sparkles className="size-3.5 shrink-0 text-[#747288]" />
        )}
        <span className="truncate font-medium text-[#141B34]">{headerText}</span>
      </button>

      {open && visibleSteps.length > 0 && (
        <ol className="flex flex-col gap-1 border-t border-[#E8ECF3] px-3 py-2">
          {visibleSteps.map((step, i) => (
            <li key={`${step.step}-${i}`} className="flex items-center gap-2">
              <StepGlyph status={step.status} />
              <span
                className={cn(
                  "flex-1 truncate",
                  step.status === "skipped" ? "text-[#979CAE]" : "text-[#494A58]",
                )}
              >
                {describeStep(step)}
              </span>
              {step.ms && step.ms > 100 && (
                <span className="shrink-0 tabular-nums text-[#979CAE]">
                  {step.ms < 1000 ? `${step.ms}ms` : `${(step.ms / 1000).toFixed(1)}s`}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
