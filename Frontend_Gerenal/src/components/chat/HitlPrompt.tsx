/**
 * HitlPrompt — Human-in-the-Loop decision widget.
 * Renders pending HITL frames (interrupt requests) from the cognitive pipeline.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { HitlFrame } from "@/store/chatStore";
import { isLeadCaptureHitlFrame } from "@/api/frames";
import { LeadCaptureForm } from "@/components/leads";
import type { LeadCaptureHitlPayload, LeadSubmitData } from "@/components/leads";

interface HitlPromptProps {
  frames: HitlFrame[];
  sessionId?: string;
  onResume: (interruptId: string, decisions: unknown[]) => void;
  onSuggestionResubmit?: (query: string) => void;
  onLeadCaptureSubmit?: (data: LeadSubmitData) => Promise<void> | void;
  onDismiss?: () => void;
}

export function HitlPrompt({
  frames,
  sessionId,
  onResume,
  onSuggestionResubmit,
  onLeadCaptureSubmit,
  onDismiss,
}: HitlPromptProps) {
  if (!frames || frames.length === 0) return null;

  return (
    <div className="flex flex-col gap-2 px-3 py-2">
      {frames.map((frame) => (
        <HitlCard
          key={frame.interrupt_id}
          frame={frame}
          onResume={onResume}
          onSuggestionResubmit={onSuggestionResubmit}
          sessionId={sessionId}
          onLeadCaptureSubmit={onLeadCaptureSubmit}
          onDismiss={onDismiss}
        />
      ))}
    </div>
  );
}

function HitlCard({
  frame,
  onResume,
  onSuggestionResubmit,
  sessionId,
  onLeadCaptureSubmit,
  onDismiss,
}: {
  frame: HitlFrame;
  sessionId?: string;
  onResume: (id: string, decisions: unknown[]) => void;
  onSuggestionResubmit?: (q: string) => void;
  onLeadCaptureSubmit?: (data: LeadSubmitData) => Promise<void> | void;
  onDismiss?: () => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [freeText, setFreeText] = useState("");

  // Lead capture form — render dedicated component instead of generic HITL card
  if (isLeadCaptureHitlFrame(frame)) {
    return (
      <LeadCaptureForm
        payload={frame as unknown as LeadCaptureHitlPayload}
        sessionId={sessionId}
        onSubmit={onLeadCaptureSubmit ?? (() => Promise.resolve())}
        onDismiss={onDismiss}
      />
    );
  }

  const prompt = String(frame.prompt || frame.question || "Please make a selection:");
  const options = Array.isArray(frame.options) ? frame.options as Array<{ label: string; value: string; query?: string }> : [];
  const multiSelect = frame.multi_select === true;
  // A real, resumable interrupt from the cognitive graph carries an
  // interrupt_id.  When present, every action RESUMES the paused turn rather
  // than starting a brand-new message.
  const canResume = typeof frame.interrupt_id === "string" && frame.interrupt_id.length > 0;

  function resumeSelection(value: string, query?: string) {
    setSubmitting(true);
    onResume(frame.interrupt_id, [{ type: "selection", selected: value, query }]);
  }

  function handleOptionClick(opt: { label: string; value: string; query?: string }) {
    if (multiSelect) {
      setSelected((prev) => prev.includes(opt.value) ? prev.filter((v) => v !== opt.value) : [...prev, opt.value]);
      return;
    }
    // Single-select: pick and resume immediately (Claude/ChatGPT quick-action).
    if (canResume) {
      resumeSelection(opt.value, opt.query);
    } else if (opt.query && onSuggestionResubmit) {
      onSuggestionResubmit(opt.query);
    }
  }

  function handleConfirm() {
    if (selected.length === 0) return;
    setSubmitting(true);
    const decisions = selected.map((v) => {
      const opt = options.find((o) => o.value === v);
      return { type: "selection", selected: v, query: opt?.query };
    });
    onResume(frame.interrupt_id, decisions);
  }

  function handleFreeTextSubmit() {
    const text = freeText.trim();
    if (!text) return;
    setSubmitting(true);
    if (canResume) {
      onResume(frame.interrupt_id, [{ type: "respond", answer: text }]);
    } else if (onSuggestionResubmit) {
      onSuggestionResubmit(text);
    }
  }

  return (
    <div className="message-appear rounded-xl border border-primary/20 bg-primary/5 p-4">
      <div className="flex items-start gap-2">
        <Badge variant="secondary" className="shrink-0 text-[10px]">AI Review</Badge>
      </div>
      <p className="mt-2 text-sm font-medium">{prompt}</p>

      {options.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {options.map((opt) => (
            <button
              key={opt.value}
              onClick={() => handleOptionClick(opt)}
              className={cn(
                "rounded-full border px-3 py-1 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-ring",
                selected.includes(opt.value)
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-card-foreground hover:bg-accent",
              )}
              disabled={submitting}
            >
              {opt.label}
            </button>
          ))}
        </div>
      ) : null}

      {multiSelect && options.length > 0 && (
        <div className="mt-3">
          <Button
            size="sm"
            disabled={selected.length === 0 || submitting}
            onClick={handleConfirm}
          >
            {submitting ? "Processing…" : "Confirm"}
          </Button>
        </div>
      )}

      {/* Free-text clarification — always available so the user can answer in
          their own words instead of picking a preset option. */}
      <div className="mt-3 flex items-center gap-2">
        <input
          type="text"
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleFreeTextSubmit();
            }
          }}
          placeholder="Or type your answer…"
          disabled={submitting}
          className="flex-1 rounded-md border border-border bg-card px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={freeText.trim().length === 0 || submitting}
          onClick={handleFreeTextSubmit}
        >
          Send
        </Button>
      </div>
    </div>
  );
}
