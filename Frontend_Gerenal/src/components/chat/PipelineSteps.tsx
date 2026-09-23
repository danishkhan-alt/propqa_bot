/**
 * PipelineSteps — shows cognitive pipeline stage progress as compact pills.
 */

import { cn } from "@/lib/utils";
import type { StepFrame } from "@/store/chatStore";
import { labelForStep, isVisibleStep } from "@/lib/pipelineLabels";

interface PipelineStepsProps {
  steps: StepFrame[];
  activeFlowId?: string | null;
  activeFlowStages?: string[];
  className?: string;
}

const STEP_COLORS: Record<string, string> = {
  completed: "bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 border-emerald-500/30",
  running: "bg-blue-500/20 text-blue-700 dark:text-blue-400 border-blue-500/30 step-pill-running",
  skipped: "bg-muted text-muted-foreground/50 border-border",
  error: "bg-red-500/20 text-red-700 dark:text-red-400 border-red-500/30",
  pending: "bg-muted/50 text-muted-foreground/40 border-border/50",
};

export function PipelineSteps({ steps, activeFlowId, activeFlowStages, className }: PipelineStepsProps) {
  if (!steps || steps.length === 0) return null;

  const visibleSteps = steps.filter((s) => s.step && isVisibleStep(s.step));

  if (visibleSteps.length === 0) return null;

  return (
    <div className={cn("flex flex-wrap gap-1 px-1 py-0.5", className)}>
      {visibleSteps.map((step, i) => {
        const label = labelForStep(step.step);
        const status = step.status ?? "completed";
        const colorClass = STEP_COLORS[status] ?? STEP_COLORS.completed;
        return (
          <span
            key={`${step.step}-${i}`}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
              colorClass,
            )}
            title={`${step.step}: ${status}${step.ms ? ` (${step.ms}ms)` : ""}`}
          >
            {status === "running" && <span className="inline-block size-1.5 rounded-full bg-current" />}
            {label}
            {step.ms && step.ms > 100 && (
              <span className="opacity-60">{step.ms < 1000 ? `${step.ms}ms` : `${(step.ms / 1000).toFixed(1)}s`}</span>
            )}
          </span>
        );
      })}

      {activeFlowId && (
        <span className="ml-1 inline-flex items-center rounded-full border border-border px-2 py-0.5 text-[10px] text-muted-foreground/60">
          {activeFlowId}
        </span>
      )}
    </div>
  );
}
