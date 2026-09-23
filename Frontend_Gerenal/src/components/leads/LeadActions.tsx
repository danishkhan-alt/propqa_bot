/**
 * LeadActions — per-message follow-up chips and bulk agent contact beneath assistant replies.
 */

import { useState } from "react";
import { SendHorizonal, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import type { FollowUpSuggestion } from "@/lib/followUpSuggestions";
import { BulkAgentContactSheet } from "./BulkAgentContactSheet";
import type { PropertyCard } from "@/store/chatStore";

export type LeadStatus = "none" | "agents_shown" | "submitted" | "dismissed";

export interface LeadSubmitData {
  buyer_name: string;
  buyer_email: string;
  buyer_phone: string;
  property_ids: number[];
  message_override?: string;
  message_html_override?: string;
  from_email?: string;
  to_email?: string;
  ui_surface?: string;
}

interface LeadActionsProps {
  sessionId: string;
  searchSummary?: string;
  cards?: unknown[];
  leadStatus?: LeadStatus;
  suggestions?: FollowUpSuggestion[];
  isLatestWithCards?: boolean;
  selectedInquiryPropertyIds?: number[];
  onSelectedInquiryPropertyIdsChange?: (ids: number[]) => void;
  onSuggestionClick?: (query: string) => void;
  onSubmitLead: (data: LeadSubmitData) => void | Promise<void>;
  className?: string;
}

function FollowUpChip({
  label,
  onClick,
  primary = false,
}: {
  label: string;
  onClick: () => void;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]",
        primary
          ? "border-[#141B34] bg-[#141B34] text-white hover:bg-[#2a3148]"
          : "border-[#E8ECF3] bg-white text-[#141B34] hover:bg-[#F5F7FA]",
      )}
    >
      {label}
    </button>
  );
}

export function LeadActions({
  sessionId,
  searchSummary,
  cards,
  leadStatus = "none",
  suggestions = [],
  isLatestWithCards = false,
  selectedInquiryPropertyIds = [],
  onSelectedInquiryPropertyIdsChange,
  onSuggestionClick,
  onSubmitLead,
  className,
}: LeadActionsProps) {
  const [contactOpen, setContactOpen] = useState(false);
  const submitted = leadStatus === "submitted";

  if (submitted) {
    return (
      <div className={cn("mt-2 flex flex-col gap-2", className)}>
        <div className="flex items-start gap-3 rounded-lg border border-border bg-card p-3 shadow-sm border-l-[3px] border-l-primary">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <SendHorizonal className="size-4" />
          </div>
          <div>
            <p className="text-sm font-medium text-foreground">Details sent!</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              The listing agent(s) for these properties will reach out within 24 hours.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Suggestion chips are shown on every card-bearing response that has them.
  // Each response carries its own contextually-relevant chips (stored per-turn
  // in Redis/DB via commit_node) so chips are persistent across page reloads.
  // The "Contact with Agents" CTA is always visible on every card-bearing message.
  const showSuggestionChips = suggestions.length > 0;

  return (
    <>
      <div className={cn("mt-2 flex flex-col gap-2", className)}>
        <div className="flex flex-wrap gap-2">
          {/* Follow-up chips — shown per response, each with its own relevant context */}
          {showSuggestionChips && suggestions.map((s) => (
            <FollowUpChip
              key={s.rebuilt_query}
              label={s.label}
              onClick={() => onSuggestionClick?.(s.rebuilt_query)}
            />
          ))}
          {/* "Contact with Agents" — always present on any card-bearing message */}
          <FollowUpChip
            label="Contact with Agents"
            primary
            onClick={() => setContactOpen(true)}
          />
        </div>
        {selectedInquiryPropertyIds.length > 0 && isLatestWithCards && (
          <p className="text-[10px] text-muted-foreground">
            {selectedInquiryPropertyIds.length} listing
            {selectedInquiryPropertyIds.length === 1 ? "" : "s"} selected for inquiry
          </p>
        )}
      </div>

      <BulkAgentContactSheet
        open={contactOpen}
        onOpenChange={setContactOpen}
        selectedPropertyIds={selectedInquiryPropertyIds}
        onSelectedPropertyIdsChange={onSelectedInquiryPropertyIdsChange ?? (() => {})}
        cards={(cards as PropertyCard[]) ?? []}
        sessionId={sessionId}
        searchSummary={searchSummary}
        onSubmitLead={async (data) => {
          await onSubmitLead(data);
        }}
      />
    </>
  );
}
