import { cn } from "@/lib/utils";
import { ClarifyingChips, type ClarifyingQuestion } from "./ClarifyingChips";

export interface ReplyCard {
  title: string;
  tag?: string;
  tag_color?: "info" | "positive" | "warning";
  description?: string;
  image_url?: string | null;
  price?: string | null;
}

export interface StructuredReply {
  message_type?: string;
  intro_text?: string;
  data_source_note?: string;
  cards?: ReplyCard[];
  exclusions_note?: string;
  clarifying_questions?: ClarifyingQuestion[];
  suggested_followups?: string[];
  session_profile?: Record<string, unknown>;
}

const TAG_CLASS: Record<string, string> = {
  info: "bg-[#E8F1FF] text-[#1D4ED8]",
  positive: "bg-[#E7F6EE] text-[#157A45]",
  warning: "bg-[#F8F1E6] text-[#8A5A12]",
};

interface StructuredAnswerProps {
  reply: StructuredReply;
  onFollowup?: (query: string) => void;
  onClarify?: (answers: Record<string, string>) => void;
}

export function StructuredAnswer({ reply, onFollowup, onClarify }: StructuredAnswerProps) {
  const questions = reply.clarifying_questions ?? [];
  const followups = reply.suggested_followups ?? [];
  const cta = followups[0] || "Compare these areas";

  return (
    <div className="flex flex-col gap-2">
      {reply.data_source_note && (
        <p className="text-[11px] uppercase tracking-wide text-[#8A5A12]">
          <span className="mr-1 inline-block size-1.5 rounded-full bg-[#E07A2F]" aria-hidden />
          {reply.data_source_note}
        </p>
      )}
      {reply.intro_text && (
        <p className="text-sm font-medium leading-6 text-[#141B34]">{reply.intro_text}</p>
      )}
      {(reply.cards ?? []).length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {(reply.cards ?? []).map((card) => (
            <article
              key={card.title}
              className="flex w-[260px] shrink-0 flex-col overflow-hidden rounded-xl border border-[#E8ECF3] bg-white shadow-sm"
            >
              {card.image_url && (
                <img
                  src={card.image_url}
                  alt=""
                  className="h-24 w-full object-cover"
                  loading="lazy"
                />
              )}
              <div className="flex flex-1 flex-col gap-1 px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-sm font-semibold leading-5 text-[#141B34]">{card.title}</h3>
                  {card.tag && (
                    <span
                      className={cn(
                        "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
                        TAG_CLASS[card.tag_color || "info"] || TAG_CLASS.info,
                      )}
                    >
                      {card.tag}
                    </span>
                  )}
                </div>
                {card.price && <p className="text-xs font-medium text-[#141B34]">{card.price}</p>}
                {card.description && (
                  <p className="text-xs leading-5 text-[#494A58]">{card.description}</p>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
      {reply.exclusions_note && (
        <p className="rounded-xl bg-[#F7F8FA] px-3 py-2 text-xs leading-5 text-[#747288]">
          {reply.exclusions_note}
        </p>
      )}
      {questions.length > 0 && onClarify && (
        <ClarifyingChips questions={questions} ctaLabel={cta} onSubmit={onClarify} />
      )}
      {followups.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-1">
          {followups.map((label) => (
            <button
              key={label}
              type="button"
              onClick={() => onFollowup?.(label)}
              className="rounded-full border border-[#E8ECF3] bg-[#F5F7FA] px-3 py-1.5 text-xs font-medium text-[#747288] hover:bg-[#EDF0F5] hover:text-[#494A58]"
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
