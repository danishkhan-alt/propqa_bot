/**
 * PropertiesSidebar — right rail for property card results.
 * Collapse hides the full panel (handled by parent); this component
 * renders either the expanded rail or a compact reopen control.
 */

import { ChevronLeft, ChevronRight, LayoutList } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CardsPanel, type CardGroup } from "./CardsPanel";
import type { PropertyCard } from "@/store/chatStore";

interface PropertiesSidebarProps {
  groups: CardGroup[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
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

export function PropertiesSidebar({
  groups,
  open,
  onOpenChange,
  className,
  sessionId,
  onSubmitLead,
  inquiryPropertyIds,
  onToggleInquiryProperty,
  attachedPropertyIds,
  onToggleAttachedProperty,
}: PropertiesSidebarProps) {
  const totalCards = groups.reduce((sum, g) => sum + g.cards.length, 0);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        aria-expanded={false}
        aria-label="Expand properties panel"
        className={cn(
          "flex shrink-0 flex-col items-center gap-2 self-start",
          "rounded-[20px] border border-[#E8ECF3] bg-white px-3 py-4",
          "shadow-[0px_5.9009px_35.4054px_rgba(20,20,24,0.02)]",
          "text-[#141B34] transition-colors hover:bg-[#F5F7FA]",
          className,
        )}
      >
        <ChevronLeft className="size-4" />
        <LayoutList className="size-4" aria-hidden />
        <Badge
          variant="outline"
          className="h-5 min-w-5 justify-center border-[#E8ECF3] bg-[#F5F7FA] px-1 text-[10px] tabular-nums text-[#141B34]"
        >
          {totalCards}
        </Badge>
      </button>
    );
  }

  return (
    <aside
      className={cn(
        "flex h-full min-h-0 w-full flex-1 flex-col overflow-clip",
        className,
      )}
    >
      <div className="flex h-full min-h-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-2 border-b border-[#E8ECF3] bg-white px-2 py-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 shrink-0 text-[#141B34] hover:bg-[#F5F7FA] hover:text-[#141B34] [&_svg]:size-3"
            onClick={() => onOpenChange(false)}
            aria-expanded={true}
            aria-label="Collapse properties panel"
          >
            <ChevronRight className="size-3" />
          </Button>

          <LayoutList className="size-4 shrink-0 text-[#141B34]" />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-[#141B34]">
            Properties
          </span>
          <Badge
            variant="outline"
            className="shrink-0 border-[#E8ECF3] bg-[#F5F7FA] tabular-nums text-[#141B34]"
          >
            {totalCards}
          </Badge>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-clip">
          <CardsPanel
            groups={groups}
            className="h-full min-h-0"
            sessionId={sessionId}
            onSubmitLead={onSubmitLead}
            inquiryPropertyIds={inquiryPropertyIds}
            onToggleInquiryProperty={onToggleInquiryProperty}
            attachedPropertyIds={attachedPropertyIds}
            onToggleAttachedProperty={onToggleAttachedProperty}
          />
        </div>
      </div>
    </aside>
  );
}
