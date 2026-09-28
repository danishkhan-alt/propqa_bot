/**
 * CardsPanel — scrollable list of per-query property groups (nested Collapsible).
 */

import { useState, useEffect, useMemo } from "react";
import { ChevronDown, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { PropertyCard } from "@/store/chatStore";
import { usePropertyFocusStore } from "@/store/propertyFocusStore";
import { cardPropertyIds } from "@/lib/propertyIds";
import { PropertyCards } from "./PropertyCards";

export interface CardGroup {
  messageId: string;
  userQuery: string;
  cards: PropertyCard[];
  searchUrl?: { url: string; total: number; shown: number; strictUrl?: string | null } | null;
  appliedFilters?: string[] | null;
  timestamp?: Date;
}

interface CardsPanelProps {
  groups: CardGroup[];
  className?: string;
  sessionId?: string;
  onSubmitLead?: (data: {
    buyer_name: string;
    buyer_email: string;
    buyer_phone: string;
    property_ids: number[];
  }) => Promise<void>;
  inquiryPropertyIds?: number[];
  onToggleInquiryProperty?: (propertyId: number) => void;
  attachedPropertyIds?: number[];
  onToggleAttachedProperty?: (propertyId: number, card: PropertyCard) => void;
}

export function CardsPanel({
  groups,
  className,
  sessionId,
  onSubmitLead,
  inquiryPropertyIds,
  onToggleInquiryProperty,
  attachedPropertyIds,
  onToggleAttachedProperty,
}: CardsPanelProps) {
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const s = new Set<string>();
    if (groups.length > 0) s.add(groups[groups.length - 1].messageId);
    return s;
  });

  useEffect(() => {
    if (groups.length === 0) return;
    const latest = groups[groups.length - 1].messageId;
    setExpanded((prev) => {
      if (prev.has(latest)) return prev;
      const next = new Set(prev);
      next.add(latest);
      return next;
    });
  }, [groups.length, groups[groups.length - 1]?.messageId]); // eslint-disable-line react-hooks/exhaustive-deps

  // A listing picked elsewhere (a map pin) opens in the newest group that shows it.
  const focusRequest = usePropertyFocusStore((state) => state.request);
  const focusGroupId = useMemo(() => {
    if (!focusRequest) return null;
    const group = [...groups].reverse().find((g) => cardPropertyIds(g.cards).includes(focusRequest.propertyId));
    return group?.messageId ?? null;
  }, [focusRequest, groups]);

  useEffect(() => {
    if (focusGroupId) setGroupOpen(focusGroupId, true);
  }, [focusGroupId, focusRequest]); // eslint-disable-line react-hooks/exhaustive-deps

  function setGroupOpen(id: string, open: boolean) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (open) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  const reversed = [...groups].reverse();

  return (
    <div className={cn("flex h-full min-h-0 flex-col overflow-hidden", className)}>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain scrollbar-thin">
        {groups.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
            <Search className="size-8 opacity-40" />
            <p className="text-sm">No results yet</p>
          </div>
        ) : (
          reversed.map((group, idx) => {
            const isLatest = idx === 0;
            const isOpen = expanded.has(group.messageId);
            return (
              <Collapsible
                key={group.messageId}
                open={isOpen}
                onOpenChange={(open) => setGroupOpen(group.messageId, open)}
                className={cn("border-b border-[#E8ECF3] last:border-b-0", isLatest && "bg-white")}
              >
                <CollapsibleTrigger asChild>
                  <button
                    type="button"
                    className="flex w-full items-start gap-2 px-3 py-2.5 text-left transition-colors hover:bg-[#F5F7FA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#E8ECF3] focus-visible:ring-inset"
                  >
                    <ChevronDown
                      className={cn(
                        "mt-0.5 size-4 shrink-0 text-[#747288] transition-transform duration-200",
                        !isOpen && "-rotate-90",
                      )}
                      aria-hidden
                    />
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-2 text-xs font-medium leading-snug text-[#141B34]">
                        {group.userQuery || "Search results"}
                      </p>
                      <div className="mt-0.5 flex flex-wrap items-center gap-2">
                        <span className="text-[10px] text-[#747288]">
                          {group.cards.length} listing{group.cards.length !== 1 ? "s" : ""}
                          {group.searchUrl?.total
                            ? ` of ${group.searchUrl.total.toLocaleString()}`
                            : ""}
                        </span>
                        {isLatest && (
                          <Badge className="h-4 px-1.5 text-[9px] font-bold uppercase">
                            Latest
                          </Badge>
                        )}
                      </div>
                    </div>
                  </button>
                </CollapsibleTrigger>

                <CollapsibleContent className="overflow-hidden">
                  <div className="px-2 pb-3">
                    <PropertyCards
                      layout="sidebar"
                      cards={group.cards}
                      searchUrl={group.searchUrl}
                      appliedFilters={group.appliedFilters}
                      sessionId={sessionId}
                      onSubmitLead={onSubmitLead}
                      inquiryPropertyIds={inquiryPropertyIds}
                      onToggleInquiryProperty={onToggleInquiryProperty}
                      attachedPropertyIds={attachedPropertyIds}
                      onToggleAttachedProperty={onToggleAttachedProperty}
                      focusRequest={group.messageId === focusGroupId ? focusRequest : null}
                    />
                  </div>
                </CollapsibleContent>
              </Collapsible>
            );
          })
        )}
      </div>
    </div>
  );
}
