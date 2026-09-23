/**
 * ContactCtaIconRow — shared Call / WhatsApp / Email buttons.
 *
 * Variants:
 * - `card` — compact icon row on strip cards
 * - `agent` — full-width row on Mode B agent cards
 * - `figma` — labeled WhatsApp + Call + icon Email (Figma property card)
 */

import { Phone, MessageCircle, Mail, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CtaChannel } from "./PropertyContactSheet";

interface ContactCtaIconRowProps {
  onCtaClick?: (channel: CtaChannel) => void;
  /** Used in aria-labels */
  subjectLabel: string;
  className?: string;
  /** `card` = compact strip; `agent` = Mode B; `figma` = labeled Figma CTAs */
  variant?: "card" | "agent" | "figma";
  /** Optional PropQA listing URL */
  propqaHref?: string | null;
}

export function ContactCtaIconRow({
  onCtaClick,
  subjectLabel,
  className,
  variant = "card",
  propqaHref,
}: ContactCtaIconRowProps) {
  const isAgent = variant === "agent";
  const isFigma = variant === "figma";
  const showCtas = Boolean(onCtaClick);
  const showPropqa = Boolean(propqaHref);

  if (!showCtas && !showPropqa) return null;

  if (isFigma) {
    return (
      <div className={cn("flex w-full items-center gap-1.5", className)}>
        {showCtas && (
          <>
            <button
              type="button"
              onClick={() => onCtaClick!("whatsapp")}
              className="inline-flex h-10 shrink-0 items-center justify-center gap-2.5 rounded-full bg-[#1B60F4] px-5 text-sm font-semibold text-white hover:bg-[#1554d9] focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]"
              aria-label={`WhatsApp about ${subjectLabel}`}
            >
              WhatsApp
              <MessageCircle className="size-4" strokeWidth={2} />
            </button>
            <button
              type="button"
              onClick={() => onCtaClick!("phone")}
              className="inline-flex h-10 min-w-0 flex-1 items-center justify-center gap-2.5 rounded-full border border-[#D8DDE6] px-5 text-sm font-medium text-[#494A58] hover:bg-[#F4F6FA] focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]"
              aria-label={`Call about ${subjectLabel}`}
            >
              <Phone className="size-4" strokeWidth={1.75} />
              Call
            </button>
            <button
              type="button"
              onClick={() => onCtaClick!("email")}
              className="inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-[#D8DDE6] text-[#494A58] hover:bg-[#F4F6FA] focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]"
              aria-label={`Email about ${subjectLabel}`}
            >
              <Mail className="size-4" strokeWidth={1.75} />
            </button>
          </>
        )}
        {showPropqa && !showCtas && (
          <a
            href={propqaHref!}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-full border border-[#D8DDE6] text-sm font-medium text-[#494A58] hover:bg-[#F4F6FA]"
            aria-label={`View ${subjectLabel} on PropQA`}
          >
            <ExternalLink className="size-4" />
            View listing
          </a>
        )}
      </div>
    );
  }

  const cardBtnClass =
    "h-6 min-w-0 flex-1 px-0 border-[#E8ECF3] bg-white text-[#141B34] shadow-none hover:bg-[#F5F7FA] hover:text-[#141B34]";
  const cardIconClass = "size-3";

  return (
    <div
      className={cn(
        isAgent
          ? "grid grid-cols-3 divide-x divide-[#E8ECF3] border-t border-[#E8ECF3]"
          : "flex items-center gap-1 border-t border-[#E8ECF3] pt-2",
        className,
      )}
    >
      {showCtas && (
        <>
          <Button
            type="button"
            variant={isAgent ? "ghost" : "outline"}
            size="icon"
            className={cn(
              "shrink-0",
              isAgent
                ? "size-7 w-full rounded-none py-1 text-[#141B34] hover:bg-[#F5F7FA] hover:text-[#141B34]"
                : cardBtnClass,
            )}
            aria-label={`Call about ${subjectLabel}`}
            onClick={() => onCtaClick!("phone")}
          >
            <Phone className={isAgent ? "size-3.5" : cardIconClass} />
          </Button>
          <Button
            type="button"
            variant={isAgent ? "ghost" : "outline"}
            size="icon"
            className={cn(
              "shrink-0",
              isAgent
                ? "size-7 w-full rounded-none py-1 text-[#141B34] hover:bg-[#F5F7FA] hover:text-[#141B34]"
                : cardBtnClass,
            )}
            aria-label={`WhatsApp about ${subjectLabel}`}
            onClick={() => onCtaClick!("whatsapp")}
          >
            <MessageCircle className={isAgent ? "size-3.5" : cardIconClass} />
          </Button>
          <Button
            type="button"
            variant={isAgent ? "ghost" : "outline"}
            size="icon"
            className={cn(
              "shrink-0",
              isAgent
                ? "size-7 w-full rounded-none py-1 text-[#141B34] hover:bg-[#F5F7FA] hover:text-[#141B34]"
                : cardBtnClass,
            )}
            aria-label={`Email about ${subjectLabel}`}
            onClick={() => onCtaClick!("email")}
          >
            <Mail className={isAgent ? "size-3.5" : cardIconClass} />
          </Button>
        </>
      )}
      {showPropqa && (
        <Button
          asChild
          variant="outline"
          size="icon"
          className={cn(
            "shrink-0 border-[#E8ECF3] bg-white text-[#141B34] hover:bg-[#F5F7FA] hover:text-[#141B34]",
            isAgent ? "size-7 w-full rounded-none py-1" : cardBtnClass,
          )}
        >
          <a
            href={propqaHref!}
            target="_blank"
            rel="noopener noreferrer"
            title="View on PropQA"
            aria-label={`View ${subjectLabel} on PropQA`}
          >
            <ExternalLink className={isAgent ? "size-3.5" : cardIconClass} />
          </a>
        </Button>
      )}
    </div>
  );
}
