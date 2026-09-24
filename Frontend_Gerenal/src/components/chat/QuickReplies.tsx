import { cn } from "@/lib/utils";

export interface QuickReplyOption {
  id: string;
  label: string;
  /** What the user "says" when they tap this option. */
  reply: string;
}

/** One follow-up question from the assistant. `id` is the profile field it fills. */
export interface FollowUpQuestion {
  id: string;
  prompt: string;
  options: QuickReplyOption[];
}

interface QuickRepliesProps {
  question: FollowUpQuestion;
  /** Only the latest reply takes input, and only while the composer is free. */
  interactive: boolean;
  /** The option the user already answered with, read from the conversation. */
  answeredId?: string | null;
  onPick: (question: FollowUpQuestion, option: QuickReplyOption) => void;
}

/** The assistant's question, answered with one tap. Typing a reply works just as well. */
export function QuickReplies({ question, interactive, answeredId = null, onPick }: QuickRepliesProps) {
  return (
    <div className="flex flex-col gap-2" role="group" aria-label={question.prompt}>
      <p className="text-sm font-medium leading-6 text-[#141B34]">{question.prompt}</p>
      <div className="flex flex-wrap gap-1.5">
        {question.options.map((option) => {
          const selected = answeredId === option.id;
          return (
            <button
              key={option.id}
              type="button"
              disabled={!interactive}
              aria-pressed={selected}
              onClick={() => onPick(question, option)}
              className={cn(
                "rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1B60F4]/30",
                selected
                  ? "border-[#141B34] bg-[#141B34] text-white"
                  : "border-[#D8DDE6] bg-white text-[#141B34] enabled:hover:border-[#141B34] enabled:hover:bg-[#F5F7FA]",
                !interactive && !selected && "opacity-50",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
