/**
 * LeadOfferBanner — soft nudge shown when the readiness score crosses
 * the soft threshold (0.30) but hasn't yet hit the hard threshold (0.40).
 *
 * The banner renders as a non-intrusive chat message that offers two paths:
 *  - "Connect me with an agent" → requests Mode A form from the server
 *  - "Show agent contacts"      → requests Mode B contact cards
 *  - Dismiss (X)                → sends ``lead_dismiss`` frame
 */

import { useState } from "react";
import { UserRound, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface LeadOfferBannerProps {
  searchSummary?: string;
  /** Called when the user picks Mode A (agent contacts you) */
  onRequestModeA?: () => void;
  /** Called when the user picks Mode B (see agent contacts directly) */
  onRequestModeB?: () => void;
  onDismiss?: () => void;
  className?: string;
}

export function LeadOfferBanner({
  searchSummary,
  onRequestModeA,
  onRequestModeB,
  onDismiss,
  className,
}: LeadOfferBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  function handleDismiss() {
    setDismissed(true);
    onDismiss?.();
  }

  return (
    <div
      className={cn(
        "message-appear flex items-start gap-3 rounded-lg border border-border bg-card px-4 py-3 shadow-sm",
        "border-l-[3px] border-l-primary",
        className,
      )}
      role="complementary"
      aria-label="Agent connection offer"
    >
      <div
        className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary"
        aria-hidden
      >
        <UserRound className="size-4" />
      </div>

      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">
          Ready to take the next step?
        </p>
        {searchSummary && (
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            Based on your search:{" "}
            <span className="font-medium text-foreground">{searchSummary}</span>
          </p>
        )}

        <div className="mt-3 flex flex-wrap gap-2">
          {onRequestModeA && (
            <Button size="sm" className="h-7 gap-1.5 text-xs" onClick={onRequestModeA}>
              Connect me with an agent
            </Button>
          )}
          {onRequestModeB && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 gap-1.5 text-xs"
              onClick={onRequestModeB}
            >
              Show contact info
            </Button>
          )}
        </div>
      </div>

      <button
        type="button"
        onClick={handleDismiss}
        className="shrink-0 rounded-md p-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        aria-label="Dismiss offer"
      >
        <X className="size-4" />
      </button>
    </div>
  );
}
