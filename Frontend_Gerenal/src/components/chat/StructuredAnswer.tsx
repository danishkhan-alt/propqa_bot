import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { renderMarkdown } from "@/lib/markdown";
import { QuickReplies, type FollowUpQuestion, type QuickReplyOption } from "./QuickReplies";
import { ExplainerBlock, FiguresBlock, type ReplyExplainer, type ReplyFigures } from "./ReplyBlocks";

export interface ReplyCard {
  title: string;
  tag?: string;
  tag_color?: "info" | "positive" | "warning";
  description?: string;
  price?: string | null;
}

export interface StructuredReply {
  message_type?: string;
  intro_text?: string;
  data_source_note?: string;
  cards?: ReplyCard[];
  /** Figures copied from the lookup rows; the server sends at most one of cards, figures, explainer. */
  figures?: ReplyFigures | null;
  explainer?: ReplyExplainer | null;
  exclusions_note?: string;
  question?: FollowUpQuestion | null;
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
  /** Only the latest reply offers next steps and takes a quick reply. */
  interactive: boolean;
  answeredId?: string | null;
  onFollowup?: (text: string) => void;
  onQuickReply?: (question: FollowUpQuestion, option: QuickReplyOption) => void;
}

/** One assistant reply: the answer, one optional block (comparison, figures, or explainer), one question, next steps, source. */
export function StructuredAnswer({
  reply,
  interactive,
  answeredId = null,
  onFollowup,
  onQuickReply,
}: StructuredAnswerProps) {
  const cards = reply.cards ?? [];
  const followups = reply.suggested_followups ?? [];
  const question = reply.question ?? null;

  return (
    <div className="flex flex-col gap-3">
      {reply.intro_text && (
        <div
          className="prose-chat min-w-0 max-w-full text-[#141B34]"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(reply.intro_text) }}
        />
      )}

      {cards.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {cards.map((card) => (
            <article
              key={card.title}
              className="flex flex-col gap-1.5 rounded-2xl border border-[#E8ECF3] bg-white px-4 py-3 shadow-[0px_0px_20px_3px_rgba(20,20,24,0.04)]"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold leading-5 text-[#101527]">{card.title}</h3>
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
              {card.price && <p className="text-sm font-semibold text-[#101527]">{card.price}</p>}
              {card.description && (
                <p className="text-xs leading-5 text-[#494A58]">{card.description}</p>
              )}
            </article>
          ))}
        </div>
      )}

      {reply.figures && <FiguresBlock figures={reply.figures} />}

      {reply.explainer && <ExplainerBlock explainer={reply.explainer} />}

      {reply.exclusions_note && (
        <p className="text-xs leading-5 text-[#747288]">{reply.exclusions_note}</p>
      )}

      {question && onQuickReply && (
        <QuickReplies
          question={question}
          interactive={interactive}
          answeredId={answeredId}
          onPick={onQuickReply}
        />
      )}

      {interactive && followups.length > 0 && onFollowup && (
        <div className="flex flex-wrap gap-1.5">
          {followups.map((label) => (
            <button
              key={label}
              type="button"
              onClick={() => onFollowup(label)}
              className="inline-flex items-center gap-1 rounded-full border border-[#E8ECF3] bg-[#F5F7FA] px-3 py-1.5 text-xs font-medium text-[#494A58] transition-colors hover:border-[#D8DDE6] hover:bg-white hover:text-[#141B34]"
            >
              {label}
              <ArrowUpRight className="size-3 opacity-60" aria-hidden />
            </button>
          ))}
        </div>
      )}

      {reply.data_source_note && (
        <p className="text-[11px] leading-4 text-[#979CAE]">Source: {reply.data_source_note}</p>
      )}
    </div>
  );
}
