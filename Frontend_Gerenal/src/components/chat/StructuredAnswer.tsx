import { lazy, Suspense } from "react";
import { ArrowUpRight, Building2 } from "lucide-react";
import { buildPropqaBuildingUrl, cn } from "@/lib/utils";
import { renderMarkdown } from "@/lib/markdown";
import { QuickReplies, type FollowUpQuestion, type QuickReplyOption } from "./QuickReplies";
import { ExplainerBlock, FiguresBlock, type ReplyExplainer, type ReplyFigures } from "./ReplyBlocks";
import type { ReplyMap } from "./PlaceMap";

// Leaflet only loads for a reply that has a map.
const PlaceMap = lazy(() => import("./PlaceMap"));

export interface ReplyCard {
  title: string;
  tag?: string;
  tag_color?: "info" | "positive" | "warning";
  description?: string;
  price?: string | null;
}

/** A building with a guide page on propqa.ai, linked under the reply. */
export interface BuildingPageLink {
  name: string;
  community?: string;
  slug: string;
}

export interface StructuredReply {
  message_type?: string;
  intro_text?: string;
  data_source_note?: string;
  cards?: ReplyCard[];
  /** Places pinned from the data; the server sends at most one of cards, map, figures, explainer. */
  map?: ReplyMap | null;
  /** Figures copied from the lookup rows. */
  figures?: ReplyFigures | null;
  explainer?: ReplyExplainer | null;
  exclusions_note?: string;
  /** Guide pages for the buildings the reply is about, chosen from the data by the server. */
  building_pages?: BuildingPageLink[];
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

/** One assistant reply: the answer, one optional block (comparison, map, figures, or explainer), building guide links, one question, next steps, source. */
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
  const buildingPages = (reply.building_pages ?? []).filter((page) => page.slug);

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

      {reply.map?.pins?.length ? (
        <Suspense fallback={<div className="h-80 animate-pulse rounded-2xl border border-[#E8ECF3] bg-[#F5F7FA]" aria-hidden />}>
          <PlaceMap map={reply.map} />
        </Suspense>
      ) : null}

      {reply.figures && <FiguresBlock figures={reply.figures} />}

      {reply.explainer && <ExplainerBlock explainer={reply.explainer} />}

      {buildingPages.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {buildingPages.map((page) => (
            <a
              key={page.slug}
              href={buildPropqaBuildingUrl(page.slug)}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`${page.name} building guide on PropQA (opens in new tab)`}
              className="group flex items-center gap-3 rounded-2xl border border-[#E8ECF3] bg-white px-4 py-3 shadow-[0px_0px_20px_3px_rgba(20,20,24,0.04)] transition-colors hover:border-[#D8DDE6] hover:bg-[#F5F7FA]"
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-[#F5F7FA] text-[#141B34] group-hover:bg-[#E8ECF3]" aria-hidden>
                <Building2 className="size-4" />
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm font-semibold leading-5 text-[#101527]">{page.name}</span>
                <span className="truncate text-xs leading-4 text-[#747288]">
                  {page.community ? `Building guide · ${page.community}` : "Building guide"}
                </span>
              </span>
              <ArrowUpRight className="size-4 shrink-0 text-[#747288]" aria-hidden />
            </a>
          ))}
        </div>
      )}

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
