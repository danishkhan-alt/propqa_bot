/**
 * HitlPrompt — Human-in-the-Loop decision widget.
 * Renders pending HITL frames (interrupt requests) from the cognitive pipeline.
 */

import { useMemo, useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import type { HitlFrame } from "@/store/chatStore";
import { isLeadCaptureHitlFrame } from "@/api/frames";
import { LeadCaptureForm } from "@/components/leads";
import type { LeadCaptureHitlPayload, LeadSubmitData } from "@/components/leads";
import {
  Questionnaire,
  QuestionnaireActions,
  QuestionnaireChoice,
  QuestionnaireChoices,
  QuestionnaireError,
  QuestionnaireInput,
  QuestionnaireItem,
  QuestionnaireNext,
  QuestionnairePrevious,
  QuestionnaireProgress,
  QuestionnaireSubmit,
  QuestionnaireTitle,
} from "@/components/ui/questionnaire";

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
  const [submitting, setSubmitting] = useState(false);
  const options = useMemo(
    () =>
      Array.isArray(frame.options)
        ? (frame.options as Array<{ label: string; value: string; query?: string }>)
        : [],
    [frame.options],
  );
  const prompt = String(frame.prompt || frame.question || "Please make a selection:");
  const multiSelect = frame.multi_select === true;
  const canResume = typeof frame.interrupt_id === "string" && frame.interrupt_id.length > 0;
  const items = useMemo(
    () => [
      {
        name: "answer",
        required: true as const,
        multiple: multiSelect,
        prompt,
        choices: options.map((option) => ({
          value: option.value,
          label: option.label,
        })),
      },
    ],
    [multiSelect, options, prompt],
  );

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

  function submitAnswer(value: string) {
    const opt = options.find((option) => option.value === value);
    setSubmitting(true);
    if (opt) {
      const query = opt.query || opt.label;
      if (canResume) {
        onResume(frame.interrupt_id, [{ type: "selection", selected: value, query }]);
      } else {
        onSuggestionResubmit?.(query);
      }
      return;
    }
    if (canResume) {
      onResume(frame.interrupt_id, [{ type: "respond", answer: value }]);
    } else {
      onSuggestionResubmit?.(value);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    const values = new FormData(event.currentTarget).getAll("answer").map(String).filter(Boolean);
    if (values.length === 0) return;
    if (multiSelect && values.every((value) => options.some((option) => option.value === value))) {
      setSubmitting(true);
      onResume(
        frame.interrupt_id,
        values.map((value) => {
          const opt = options.find((option) => option.value === value);
          return { type: "selection", selected: value, query: opt?.query || opt?.label };
        }),
      );
      return;
    }
    submitAnswer(values[0]);
  }

  return (
    <div className="message-appear rounded-2xl border border-[#E8ECF3] bg-[#F7F8FA] p-3">
      <Badge variant="secondary" className="border-[#E8ECF3] bg-white text-[10px] font-medium text-[#747288]">A quick check</Badge>
      <Questionnaire
        className="mt-3"
        items={items}
        shortcuts="letters"
        onSubmit={handleSubmit}
      >
        <QuestionnaireProgress />
        {items.map((question) => (
          <QuestionnaireItem
            key={question.name}
            name={question.name}
            required
            multiple={question.multiple}
          >
            <QuestionnaireTitle>{question.prompt}</QuestionnaireTitle>
            <QuestionnaireChoices>
              {question.choices.map((choice) => (
                <QuestionnaireChoice key={choice.value} value={choice.value}>
                  {choice.label}
                </QuestionnaireChoice>
              ))}
              <QuestionnaireInput aria-label="Another answer" placeholder="Or type your answer…" />
            </QuestionnaireChoices>
            <QuestionnaireError />
          </QuestionnaireItem>
        ))}
        <QuestionnaireActions>
          <QuestionnairePrevious />
          <QuestionnaireNext />
          <QuestionnaireSubmit disabled={submitting}>
            {submitting ? "Processing…" : "Submit"}
          </QuestionnaireSubmit>
        </QuestionnaireActions>
      </Questionnaire>
    </div>
  );
}
