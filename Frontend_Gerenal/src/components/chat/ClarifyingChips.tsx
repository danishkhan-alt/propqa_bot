import { Check } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

export interface ChipOption {
  id: string;
  label: string;
}

export interface ClarifyingQuestion {
  id: string;
  label: string;
  type: "single_select" | "multi_select";
  options: ChipOption[];
}

interface ClarifyingChipsProps {
  questions: ClarifyingQuestion[];
  ctaLabel: string;
  onSubmit: (answers: Record<string, string>) => void;
}

export function ClarifyingChips({ questions, ctaLabel, onSubmit }: ClarifyingChipsProps) {
  const [selected, setSelected] = useState<Record<string, string>>({});
  const answered = questions.filter((question) => selected[question.id]).length;
  const complete = questions.length > 0 && answered === questions.length;

  return (
    <div className="mt-3 rounded-xl border border-[#E8ECF3] bg-[#FAFBFC] p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-[#141B34]">
          {questions.length === 1 ? "One thing narrows this down" : "Two things narrow this down"}
        </p>
        <p className="text-xs text-[#747288]">
          {answered} of {questions.length} answered
        </p>
      </div>
      <div className="flex flex-col gap-3">
        {questions.map((question) => (
          <fieldset key={question.id} className="min-w-0 border-0 p-0">
            <legend className="mb-1.5 text-xs text-[#747288]">{question.label}</legend>
            <div className="flex flex-wrap gap-1.5">
              {question.options.map((option) => {
                const on = selected[question.id] === option.id;
                return (
                  <button
                    key={option.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() =>
                      setSelected((current) => ({ ...current, [question.id]: option.id }))
                    }
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-medium",
                      on
                        ? "border-[#141B34] bg-[#141B34] text-white"
                        : "border-[#E8ECF3] bg-white text-[#141B34] hover:border-[#C9CED8]",
                    )}
                  >
                    {on && <Check className="size-3" aria-hidden />}
                    {option.label}
                  </button>
                );
              })}
            </div>
          </fieldset>
        ))}
      </div>
      <button
        type="button"
        disabled={!complete}
        aria-disabled={!complete}
        onClick={() => complete && onSubmit(selected)}
        className={cn(
          "mt-3 w-full rounded-lg px-3 py-2 text-sm font-medium",
          complete
            ? "bg-[#141B34] text-white"
            : "cursor-not-allowed bg-[#F0F2F7] text-[#747288]",
        )}
      >
        {complete ? ctaLabel : questions.length > 1 ? "Answer both to compare areas" : "Answer to compare areas"}
      </button>
    </div>
  );
}
