/**
 * MessageList — renders the scrollable chat message feed.
 * Handles user messages, assistant streaming messages, loading states,
 * property cards, pipeline pills and guest banners.
 */

import { useEffect, useRef, useState, forwardRef, useImperativeHandle, useMemo } from "react";
import { Copy, Check, RotateCcw, ThumbsUp, ThumbsDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { renderMarkdown, extractPlainText } from "@/lib/markdown";
import { formatDurationMs, formatRelativeTime } from "@/lib/utils";
import { GuestBanner, type BannerTrigger } from "./GuestBanner";
import { PropQABrand } from "@/components/brand/PropQABrand";
import { ThinkingPanel } from "./ThinkingPanel";
import { isVisibleStep } from "@/lib/pipelineLabels";
import { useAuthStore } from "@/store/authStore";
import type { AgentContact, AgentCoverage } from "@/components/leads";
import { LeadActions, type LeadStatus, type LeadSubmitData } from "@/components/leads";
import type { FollowUpSuggestion } from "@/lib/followUpSuggestions";
import type { StepFrame } from "@/store/chatStore";
import { StructuredAnswer } from "./StructuredAnswer";
import { followupQuery, type ContinuationContext } from "@/store/sessionProfileStore";
import { PropertyCards } from "./PropertyCards";
import type { PropertyCard } from "@/store/chatStore";

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  isStreaming?: boolean;
  timestamp?: Date;
  userPrompt?: string;
  statusText?: string;
  cards?: unknown[];
  searchUrl?: { url: string; total: number; shown: number; strictUrl?: string | null };
  appliedFilters?: string[];
  turnId?: string;
  /** Wall-clock ms from send to done for this assistant reply */
  durationMs?: number;
  /** Mode B agent contacts shown for THIS message's properties */
  agentContacts?: AgentContact[];
  /** Listing coverage stats from POST /api/leads/agents */
  agentCoverage?: AgentCoverage;
  /** Lead lifecycle state for THIS message */
  leadStatus?: LeadStatus;
  /** AI follow-up chips from the result envelope */
  suggestions?: FollowUpSuggestion[];
  /** Persisted thumbs feedback — undefined/null until the user votes */
  thumbsUp?: boolean | null;
  thumbsDown?: boolean | null;
  /** Structured cards, chips, and follow-ups for this reply */
  structured?: import("@/components/chat/StructuredAnswer").StructuredReply;
  /** Pipeline step timeline for THIS turn — drives the collapsible thinking panel */
  steps?: StepFrame[];
}

export interface MessageListHandle {
  scrollToBottom: (smooth?: boolean) => void;
}

interface MessageListProps {
  messages: Message[];
  isLoading?: boolean;
  loadingStatus?: string;
  /** Live pipeline steps for the in-flight turn — feeds the streaming thinking panel */
  liveSteps?: StepFrame[];
  guestBanner?: BannerTrigger | null;
  onRetry?: (prompt: string) => void;
  onSignUp?: () => void;
  onSignIn?: () => void;
  onDismissGuestBanner?: () => void;
  /** Submit buyer details for one message's properties */
  onSubmitLead?: (msg: Message, data: LeadSubmitData) => void | Promise<void>;
  /** Re-send a follow-up suggestion query */
  onSuggestionClick?: (query: string) => void;
  /** Chip answers for a structured reply, with the search they belong to */
  onClarify?: (answers: Record<string, string>, context?: ContinuationContext) => void;
  /** Property IDs selected in the sidebar for bulk agent contact */
  selectedInquiryPropertyIds?: number[];
  onSelectedInquiryPropertyIdsChange?: (ids: number[]) => void;
  sessionId?: string;
  className?: string;
}

export const MessageList = forwardRef<MessageListHandle, MessageListProps>(
  ({
    messages,
    isLoading,
    loadingStatus,
    liveSteps = [],
    guestBanner,
    onRetry,
    onSignUp,
    onSignIn,
    onDismissGuestBanner,
    onSubmitLead,
    onSuggestionClick,
    onClarify,
    selectedInquiryPropertyIds = [],
    onSelectedInquiryPropertyIdsChange,
    sessionId = "",
    className,
  }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const { isGuest } = useAuthStore();

    // Scroll only this list's own container, never scrollIntoView(): in modern
    // Chromium, overflow-hidden ancestors (e.g. the <main> shell) are treated as
    // programmatically scrollable "scroll containers", so scrollIntoView() can
    // walk up and scroll <main> itself — shoving the whole layout upward and
    // leaving a dead-space gap below the composer. Scrolling containerRef
    // directly guarantees only the message pane ever moves.
    function scrollContainerToBottom(smooth: boolean) {
      const el = containerRef.current;
      if (!el) return;
      el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "instant" });
    }

    const latestAssistantWithCardsId = useMemo(() => {
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (m.role === "assistant" && (m.cards?.length ?? 0) > 0) return m.id;
      }
      return null;
    }, [messages]);

    useImperativeHandle(ref, () => ({
      scrollToBottom: (smooth = true) => scrollContainerToBottom(smooth),
    }));

    useEffect(() => {
      scrollContainerToBottom(true);
    }, [messages.length, isLoading]);

    return (
      <div
        ref={containerRef}
        className={cn("flex h-full min-h-0 flex-col overflow-y-auto scrollbar-thin", className)}
      >
        {/* Empty state — Figma Frame 2147228905: SPHERE 4 + headline */}
        {messages.length === 0 && !isLoading && (
          <div className="relative isolate flex flex-1 flex-col items-center justify-center gap-2 px-4 py-8 text-center">
            <img
              src="/propqa-empty-sphere.svg"
              alt=""
              width={138}
              height={140}
              className="pointer-events-none h-[140px] w-[138px] shrink-0 select-none"
              draggable={false}
            />
            <p className="text-xl font-medium leading-[1.4] text-[#494A58]">
              How can i help you?
            </p>
          </div>
        )}

        {/* Messages */}
        <div className="flex flex-col gap-1 px-2 py-4">
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              sessionId={sessionId}
              isLatestWithCards={msg.id === latestAssistantWithCardsId}
              onRetry={onRetry}
              onSubmitLead={onSubmitLead}
              onSuggestionClick={onSuggestionClick}
              onClarify={onClarify}
              selectedInquiryPropertyIds={selectedInquiryPropertyIds}
              onSelectedInquiryPropertyIdsChange={onSelectedInquiryPropertyIdsChange}
            />
          ))}

          {/* Loading indicator — live thinking panel once pipeline steps start
              arriving, otherwise the classic bouncing dots + status text. */}
          {isLoading && (
            <div className="flex gap-3 px-3 py-2 message-appear">
              <AssistantAvatar />
              {liveSteps.some((s) => s.step && isVisibleStep(s.step)) ? (
                <div className="min-w-0 max-w-[80%] flex-1">
                  <ThinkingPanel steps={liveSteps} isStreaming />
                </div>
              ) : (
                <div className="flex items-center gap-2 rounded-2xl border border-[#E8ECF3] bg-white px-4 py-2.5 text-sm text-[#747288]">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  {loadingStatus && (
                    <span className="ml-2 text-xs text-[#747288]">{loadingStatus}</span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Guest conversion banner */}
          {isGuest && guestBanner && onSignUp && (
            <GuestBanner
              trigger={guestBanner}
              onSignUp={onSignUp}
              onSignIn={onSignIn}
              onDismiss={onDismissGuestBanner}
            />
          )}
        </div>
      </div>
    );
  },
);

MessageList.displayName = "MessageList";

function replyContext(message: Message): ContinuationContext {
  const listings = (message.cards ?? []) as PropertyCard[];
  const areas = message.structured?.cards ?? [];
  const subjects = (listings.length ? listings : areas)
    .map((card) => String(("title" in card && card.title) || ("location" in card && card.location) || "").trim())
    .filter(Boolean)
    .slice(0, 4);
  return {
    priorQuestion: message.userPrompt,
    subjects,
    about: listings.length ? "properties" : "areas",
  };
}

// ── MessageBubble ────────────────────────────────────────────────────────────

interface MessageBubbleProps {
  message: Message;
  sessionId: string;
  isLatestWithCards?: boolean;
  onRetry?: (prompt: string) => void;
  onSubmitLead?: (msg: Message, data: LeadSubmitData) => void | Promise<void>;
  onSuggestionClick?: (query: string) => void;
  onClarify?: (answers: Record<string, string>, context?: ContinuationContext) => void;
  selectedInquiryPropertyIds?: number[];
  onSelectedInquiryPropertyIdsChange?: (ids: number[]) => void;
}

function MessageBubble({
  message,
  sessionId,
  isLatestWithCards = false,
  onRetry,
  onSubmitLead,
  onSuggestionClick,
  onClarify,
  selectedInquiryPropertyIds = [],
  onSelectedInquiryPropertyIdsChange,
}: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(
    message.thumbsUp ? "up" : message.thumbsDown ? "down" : null,
  );

  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <div className="mx-auto my-2 rounded-full border bg-muted/50 px-4 py-1 text-xs text-muted-foreground">
        {message.content}
      </div>
    );
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(extractPlainText(message.content));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* ignore */ }
  }

  return (
    <div className={cn("group flex items-start gap-3 px-2.5 py-1 message-appear", isUser && "flex-row-reverse")}>
      {!isUser && <AssistantAvatar />}

      <div className={cn("flex min-w-0 max-w-[80%] flex-col gap-1", isUser && "items-end", !isUser && (message.cards?.length ?? 0) > 0 && "max-w-full")}>
        {!isUser && !message.isStreaming && (message.steps?.length ?? 0) > 0 && (
          <ThinkingPanel
            steps={message.steps ?? []}
            isStreaming={false}
            durationMs={message.durationMs}
          />
        )}

        {/* Bubble — Figma: user = Gray/100; assistant = white + Secondary/800 body */}
        <div
          className={cn(
            "text-sm font-medium leading-[1.5] text-[#141B34]",
            isUser
              ? "rounded-2xl rounded-br-none bg-[#F0F2F7] px-4 py-3"
              : "bg-white px-2.5 py-0",
            message.isStreaming && "animate-pulse",
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap break-words text-[#141B34]">{message.content}</p>
          ) : message.structured ? (
            <StructuredAnswer
              reply={message.structured}
              onFollowup={(label) => {
                const context = replyContext(message);
                onSuggestionClick?.(followupQuery(label, context));
              }}
              onClarify={(answers) => onClarify?.(answers, replyContext(message))}
            />
          ) : (
            <div
              className="prose-chat min-w-0 max-w-full text-[#141B34]"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content || "…") }}
            />
          )}
        </div>

        {/* Status text during streaming */}
        {!isUser && (message.cards?.length ?? 0) > 0 && (
          <PropertyCards
            cards={message.cards as PropertyCard[]}
            searchUrl={message.searchUrl}
            appliedFilters={message.appliedFilters}
            layout="strip"
            sessionId={sessionId}
            className="mt-1"
          />
        )}

        {message.statusText && (message.isStreaming || message.statusText === "Stopped") && (
          <span className="px-1 text-[10px] text-muted-foreground">{message.statusText}</span>
        )}

        {/* Timestamp + action buttons */}
        <div
          className={cn(
            "flex items-center gap-2 px-1 text-[10px] text-muted-foreground",
            !isUser && "opacity-70 transition-opacity group-hover:opacity-100",
            isUser && "opacity-0 transition-opacity group-hover:opacity-100 flex-row-reverse",
          )}
        >
          {message.timestamp && (
            <span>{formatRelativeTime(message.timestamp)}</span>
          )}
          {!isUser && message.durationMs != null && message.durationMs > 0 && (
            <>
              <span className="opacity-50" aria-hidden>·</span>
              <span title="Total response generation time">
                Generated in {formatDurationMs(message.durationMs)}
              </span>
            </>
          )}
          {!isUser && (
            <button
              onClick={handleCopy}
              className="rounded p-0.5 text-muted-foreground hover:text-foreground"
              title="Copy"
            >
              {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
            </button>
          )}
          {!isUser && message.userPrompt && onRetry && (
            <button
              onClick={() => onRetry(message.userPrompt!)}
              className="rounded p-0.5 text-muted-foreground hover:text-foreground"
              title="Retry"
            >
              <RotateCcw className="size-3" />
            </button>
          )}
          {/* Thumbs feedback — only on completed assistant messages */}
          {!isUser && !message.isStreaming && (
            <ThumbsFeedback
              messageId={message.id}
              sessionId={sessionId}
              turnId={message.turnId}
              userMessage={message.userPrompt}
              assistantMessage={message.content}
              value={feedback}
              onChange={setFeedback}
            />
          )}
        </div>

        {/* Per-message lead actions — rendered for every card-bearing response.
            Each response carries its own suggestion chips (stored per-turn in Redis/DB)
            and the "Contact with Agents" CTA. */}
        {!isUser && !message.isStreaming &&
          (message.cards?.length ?? 0) > 0
          && onSubmitLead && (
          <LeadActions
            cards={message.cards}
            sessionId={sessionId}
            searchSummary={message.userPrompt}
            leadStatus={message.leadStatus}
            suggestions={message.suggestions}
            isLatestWithCards={isLatestWithCards}
            selectedInquiryPropertyIds={selectedInquiryPropertyIds}
            onSelectedInquiryPropertyIdsChange={onSelectedInquiryPropertyIdsChange}
            onSuggestionClick={onSuggestionClick}
            onSubmitLead={async (data) => {
              await onSubmitLead(message, data);
            }}
            className="w-full"
          />
        )}
      </div>
    </div>
  );
}

// ── ThumbsFeedback ────────────────────────────────────────────────────────────

interface ThumbsFeedbackProps {
  messageId: string;
  sessionId: string;
  turnId?: string;
  userMessage?: string;
  assistantMessage?: string;
  value: "up" | "down" | null;
  onChange: (v: "up" | "down") => void;
}

function ThumbsFeedback({
  messageId,
  sessionId,
  turnId,
  userMessage,
  assistantMessage,
  value,
  onChange,
}: ThumbsFeedbackProps) {
  async function handleClick(thumbs: "up" | "down") {
    if (value === thumbs) return; // already voted
    onChange(thumbs);
    try {
      const { analyticsApi } = await import("@/api/analyticsApi");
      await analyticsApi.submitFeedback(thumbs, turnId ?? messageId, sessionId, undefined, {
        turnId,
        userMessage,
        assistantMessage,
      });
    } catch { /* graceful no-op */ }
  }

  return (
    <>
      <button
        onClick={() => handleClick("up")}
        className={cn(
          "rounded p-0.5 transition-colors",
          value === "up"
            ? "text-emerald-500"
            : "text-muted-foreground hover:text-emerald-500",
        )}
        title="Helpful"
        aria-label="Mark as helpful"
        aria-pressed={value === "up"}
      >
        <ThumbsUp className="size-3" />
      </button>
      <button
        onClick={() => handleClick("down")}
        className={cn(
          "rounded p-0.5 transition-colors",
          value === "down"
            ? "text-rose-500"
            : "text-muted-foreground hover:text-rose-500",
        )}
        title="Not helpful"
        aria-label="Mark as not helpful"
        aria-pressed={value === "down"}
      >
        <ThumbsDown className="size-3" />
      </button>
    </>
  );
}

/** Assistant bubble avatar — uses media/Icon.svg via /propqa-icon.svg */
function AssistantAvatar({ className }: { className?: string }) {
  return (
    <PropQABrand
      variant="icon"
      className={cn("size-7 shrink-0 mt-1", className)}
    />
  );
}

// ── Suggestion Chips ─────────────────────────────────────────────────────────

/** Welcome prompt chips — shown inside the Composer input footer. */
export const WELCOME_SUGGESTION_CHIPS = [
  { label: "Off-plan apartments", message: "Show me off-plan apartments in Dubai Marina under AED 2M" },
  { label: "Market trends", message: "What are the current property market trends in Dubai?" },
  { label: "Best ROI areas", message: "Which Dubai areas have the best rental ROI right now?" },
  { label: "Golden Visa", message: "What properties qualify for the UAE Golden Visa?" },
];
