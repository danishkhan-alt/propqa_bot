/**
 * PropertyCards — strip (chat) or Figma horizontal sidebar listing cards.
 */

import { useState, useEffect, useMemo, useRef, type ReactNode } from "react";
import { toast } from "sonner";
import {
  ExternalLink,
  Bed,
  Bath,
  Square,
  MapPin,
  Calendar,
  ChevronLeft,
  ChevronRight,
  UserPlus,
  Check,
  Home,
} from "lucide-react";
import { ContactCtaIconRow } from "@/components/leads/ContactCtaIconRow";
import {
  PropertyContactSheet,
  type CtaChannel,
  type PropertyContactContext,
} from "@/components/leads/PropertyContactSheet";
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { cn, resolvePropqaUrl } from "@/lib/utils";
import { usePropertyContact } from "@/hooks/usePropertyContact";
import { useWorkingImages } from "@/hooks/useWorkingImages";
import { cardPropertyIds, parsePropertyId } from "@/lib/propertyIds";
import {
  pickCardTitle,
  pickFigmaCardTitle,
  pickPriceLine,
  pickPriceAmount,
  pickCardImages,
  pickBeds,
  pickBaths,
  pickArea,
  humanizePurpose,
  humanizeCompletion,
  pickCardType,
  pickAddedOn,
  pickCompletionBadges,
  pickCardLocation,
  pickAgencyLogoUrl,
  pickAgentImageUrl,
  pickCardListingHref,
} from "@/lib/propertyCard";
import type { PropertyCard } from "@/store/chatStore";
import type { PropertyFocusRequest } from "@/store/propertyFocusStore";

/** Sidebar Figma list: ~3×239px cards per page. */
const SIDEBAR_PAGE_SIZE = 3;
// How long a listing opened from elsewhere (a map pin) stays outlined.
const FOCUS_HIGHLIGHT_MS = 2400;

/**
 * Build a compact page-number sequence with ellipses for large page counts,
 * e.g. [1, "ellipsis", 4, 5, 6, "ellipsis", 12].
 */
function getPageNumbers(current: number, total: number): (number | "ellipsis")[] {
  const siblingCount = 1;
  const totalVisible = siblingCount * 2 + 5;
  if (total <= totalVisible) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }

  const left = Math.max(current - siblingCount, 2);
  const right = Math.min(current + siblingCount, total - 1);
  const pages: (number | "ellipsis")[] = [1];

  if (left > 2) pages.push("ellipsis");
  for (let i = left; i <= right; i++) pages.push(i);
  if (right < total - 1) pages.push("ellipsis");

  pages.push(total);
  return pages;
}

interface PropertyCardsProps {
  cards: PropertyCard[];
  searchUrl?: { url: string; total: number; shown: number; strictUrl?: string | null } | null;
  appliedFilters?: string[] | null;
  /** Horizontal strip (default) or Figma single-column list for the right sidebar */
  layout?: "strip" | "sidebar";
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
  /** Bring this listing into view and outline it, when it is one of `cards`. */
  focusRequest?: PropertyFocusRequest | null;
}

export function PropertyCards({
  cards,
  searchUrl,
  appliedFilters,
  layout = "strip",
  className,
  sessionId = "",
  onSubmitLead,
  inquiryPropertyIds = [],
  onToggleInquiryProperty,
  attachedPropertyIds = [],
  onToggleAttachedProperty,
  focusRequest = null,
}: PropertyCardsProps) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sheetChannel, setSheetChannel] = useState<CtaChannel | null>(null);
  const [sheetContext, setSheetContext] = useState<PropertyContactContext | null>(null);
  const { fetchContact } = usePropertyContact();

  const showCtas = Boolean(sessionId && onSubmitLead);
  const propertyIds = useMemo(() => cardPropertyIds(cards), [cards]);
  useEffect(() => {
    if (!showCtas || !propertyIds.length) return;
    for (const id of propertyIds) {
      void fetchContact(id);
    }
  }, [propertyIds, showCtas, fetchContact]);

  const isSidebar = layout === "sidebar";

  const [page, setPage] = useState(1);
  const totalPages = isSidebar
    ? Math.max(Math.ceil(cards.length / SIDEBAR_PAGE_SIZE), 1)
    : 1;

  useEffect(() => {
    setPage(1);
  }, [cards]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const listRef = useRef<HTMLDivElement>(null);
  const [highlightId, setHighlightId] = useState<number | null>(null);

  useEffect(() => {
    if (!focusRequest) return;
    const index = cards.findIndex((card) => parsePropertyId(card) === focusRequest.propertyId);
    if (index < 0) return;
    if (isSidebar) setPage(Math.floor(index / SIDEBAR_PAGE_SIZE) + 1);
    setHighlightId(focusRequest.propertyId);
    const timer = window.setTimeout(() => setHighlightId(null), FOCUS_HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [focusRequest, cards, isSidebar]);

  // Runs after the page holding the listing has rendered.
  useEffect(() => {
    if (highlightId == null) return;
    listRef.current
      ?.querySelector(`[data-property-id="${highlightId}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [highlightId, page]);

  const pagedCards = useMemo(() => {
    if (!isSidebar) return cards;
    const start = (page - 1) * SIDEBAR_PAGE_SIZE;
    return cards.slice(start, start + SIDEBAR_PAGE_SIZE);
  }, [cards, isSidebar, page]);

  if (!cards || cards.length === 0) return null;

  const viewAllHref = searchUrl?.url ? resolvePropqaUrl(searchUrl.url) : null;

  function openCta(channel: CtaChannel, card: PropertyCard) {
    const propertyId = parsePropertyId(card);
    if (!propertyId) return;
    const rawPath =
      (card.url as string | undefined) ||
      (card.link as string | undefined) ||
      (card.slug ? `/property/${String(card.slug)}` : null);
    setSheetContext({
      propertyId,
      propertyTitle: pickCardTitle(card),
      price: pickPriceLine(card),
      propqaUrl: resolvePropqaUrl(rawPath),
    });
    setSheetChannel(channel);
    setSheetOpen(true);
  }

  return (
    <div className={cn("w-full", isSidebar && "flex flex-col", className)}>
      {searchUrl && (
        <div className="mb-2 flex shrink-0 items-center justify-between px-1 text-xs text-muted-foreground">
          <span>
            Showing {searchUrl.shown} of {searchUrl.total.toLocaleString()} properties
          </span>
          {viewAllHref && (
            <a
              href={viewAllHref}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-primary hover:underline"
            >
              View all <ExternalLink className="size-3" />
            </a>
          )}
        </div>
      )}

      {appliedFilters && appliedFilters.length > 0 && (
        <div className="mb-2 flex shrink-0 flex-wrap gap-1 px-1">
          {appliedFilters.map((f) => (
            <span
              key={f}
              className="rounded-full border bg-muted px-2 py-0.5 text-[10px] text-muted-foreground"
            >
              {f}
            </span>
          ))}
        </div>
      )}

      <div
        ref={listRef}
        className={cn(
          isSidebar ? "flex flex-col gap-3 pr-1" : "cards-strip",
        )}
      >
        {pagedCards.map((card, i) => (
          <PropertyCardItem
            key={(card.id as string | number | undefined) ?? i}
            card={card}
            layout={layout}
            showCtas={showCtas}
            onCtaClick={showCtas ? (ch) => openCta(ch, card) : undefined}
            inquirySelected={
              parsePropertyId(card) != null &&
              inquiryPropertyIds.includes(parsePropertyId(card)!)
            }
            onToggleInquiry={
              isSidebar && onToggleInquiryProperty && parsePropertyId(card) != null
                ? () => onToggleInquiryProperty(parsePropertyId(card)!)
                : undefined
            }
            attachedSelected={
              parsePropertyId(card) != null &&
              attachedPropertyIds.includes(parsePropertyId(card)!)
            }
            onToggleAttached={
              isSidebar && onToggleAttachedProperty && parsePropertyId(card) != null
                ? () => onToggleAttachedProperty(parsePropertyId(card)!, card)
                : undefined
            }
            highlighted={highlightId != null && parsePropertyId(card) === highlightId}
          />
        ))}
      </div>

      {isSidebar && totalPages > 1 && (
        <PropertyCardsPagination page={page} totalPages={totalPages} onPageChange={setPage} />
      )}

      {showCtas && onSubmitLead && (
        <PropertyContactSheet
          open={sheetOpen}
          onOpenChange={setSheetOpen}
          channel={sheetChannel}
          context={sheetContext}
          sessionId={sessionId}
          onSubmitLead={onSubmitLead}
        />
      )}
    </div>
  );
}

function PropertyCardsPagination({
  page,
  totalPages,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  const pageNumbers = useMemo(() => getPageNumbers(page, totalPages), [page, totalPages]);
  const chromeBtn =
    "border border-[#D8DDE6] bg-white text-[#141B34] shadow-none hover:bg-[#F5F7FA] hover:text-[#141B34]";
  const chromeActive =
    "border-[#101527] bg-[#101527] text-white hover:bg-[#101527] hover:text-white";

  return (
    <Pagination className="mt-3 shrink-0 bg-white">
      <PaginationContent>
        <PaginationItem>
          <PaginationPrevious
            aria-disabled={page <= 1}
            className={cn(chromeBtn, page <= 1 && "pointer-events-none opacity-40")}
            onClick={() => onPageChange(Math.max(page - 1, 1))}
          />
        </PaginationItem>

        {pageNumbers.map((n, i) =>
          n === "ellipsis" ? (
            <PaginationItem key={`ellipsis-${i}`}>
              <PaginationEllipsis className="text-[#747288]" />
            </PaginationItem>
          ) : (
            <PaginationItem key={n}>
              <PaginationLink
                isActive={n === page}
                className={cn(n === page ? chromeActive : chromeBtn)}
                onClick={() => onPageChange(n)}
              >
                {n}
              </PaginationLink>
            </PaginationItem>
          ),
        )}

        <PaginationItem>
          <PaginationNext
            aria-disabled={page >= totalPages}
            className={cn(chromeBtn, page >= totalPages && "pointer-events-none opacity-40")}
            onClick={() => onPageChange(Math.min(page + 1, totalPages))}
          />
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  );
}

function PropertyCardItem({
  card,
  layout = "strip",
  showCtas = false,
  onCtaClick,
  inquirySelected = false,
  onToggleInquiry,
  attachedSelected = false,
  onToggleAttached,
  highlighted = false,
}: {
  card: PropertyCard;
  layout?: "strip" | "sidebar";
  showCtas?: boolean;
  onCtaClick?: (channel: CtaChannel) => void;
  inquirySelected?: boolean;
  onToggleInquiry?: () => void;
  attachedSelected?: boolean;
  onToggleAttached?: () => void;
  highlighted?: boolean;
}) {
  if (layout === "sidebar") {
    return (
      <SidebarFigmaCard
        card={card}
        showCtas={showCtas}
        onCtaClick={onCtaClick}
        inquirySelected={inquirySelected}
        onToggleInquiry={onToggleInquiry}
        attachedSelected={attachedSelected}
        onToggleAttached={onToggleAttached}
        highlighted={highlighted}
      />
    );
  }
  return (
    <StripCard
      card={card}
      showCtas={showCtas}
      onCtaClick={onCtaClick}
    />
  );
}

/** Figma horizontal card: image 280×239 | details column. */
function SidebarFigmaCard({
  card,
  showCtas = false,
  onCtaClick,
  inquirySelected = false,
  onToggleInquiry,
  attachedSelected = false,
  onToggleAttached,
  highlighted = false,
}: {
  card: PropertyCard;
  showCtas?: boolean;
  onCtaClick?: (channel: CtaChannel) => void;
  inquirySelected?: boolean;
  onToggleInquiry?: () => void;
  attachedSelected?: boolean;
  onToggleAttached?: () => void;
  highlighted?: boolean;
}) {
  const title = pickFigmaCardTitle(card);
  const location = pickCardLocation(card);
  const priceAmount = pickPriceAmount(card);
  const beds = pickBeds(card);
  const baths = pickBaths(card);
  const area = pickArea(card);
  const type = pickCardType(card);
  const badges = pickCompletionBadges(card.completion_status ?? card.completion);
  const agencyLogo = pickAgencyLogoUrl(card);
  // When the agent account is the brokerage (only a logo on file), reuse it as avatar.
  const agentImage = pickAgentImageUrl(card) ?? agencyLogo;
  const cardImages = useMemo(() => pickCardImages(card), [card]);
  const { images, markFailed } = useWorkingImages(cardImages);
  const [imageIndex, setImageIndex] = useState(0);

  useEffect(() => {
    setImageIndex(0);
  }, [card.id]);

  // A photo that failed can shrink the list under the current index.
  const currentImage = images[imageIndex] ?? images[0];
  const hasMultiple = images.length > 1;
  const propertyId = parsePropertyId(card);
  const ctaEnabled = showCtas && propertyId != null && onCtaClick;
  const listingHref = pickCardListingHref(card);

  const listingLink = listingHref
    ? {
        href: listingHref,
        target: "_blank" as const,
        rel: "noopener noreferrer",
      }
    : null;

  return (
    <article
      data-property-id={propertyId ?? undefined}
      className={cn(
        "relative flex h-[239px] w-full min-w-0 shrink-0 flex-row overflow-hidden rounded-2xl",
        "shadow-[0px_0px_20px_3px_rgba(20,20,24,0.04)] transition-shadow duration-300",
        highlighted && "ring-2 ring-[#101527] ring-offset-2",
      )}
    >
      {/* Image column */}
      <div className="relative h-full w-[280px] shrink-0 overflow-hidden bg-[#F5F7FA]">
        {currentImage ? (
          listingLink ? (
            <a {...listingLink} aria-label={`Open ${title} on PropQA`} className="block h-full w-full">
              <img
                key={currentImage}
                onError={() => markFailed(currentImage)}
                src={currentImage}
                alt={`${title} — photo ${imageIndex + 1} of ${images.length}`}
                className="h-full w-full object-cover"
                loading="lazy"
              />
            </a>
          ) : (
            <img
              key={currentImage}
              onError={() => markFailed(currentImage)}
              src={currentImage}
              alt={`${title} — photo ${imageIndex + 1} of ${images.length}`}
              className="h-full w-full object-cover"
              loading="lazy"
            />
          )
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-[#747288]">
            <Home className="size-8 opacity-40" />
            <span className="text-[10px]">No image</span>
          </div>
        )}

        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-[52px] bg-gradient-to-b from-[rgba(32,34,38,0.28)] to-transparent"
          aria-hidden
        />

        <div className="absolute inset-x-4 top-4 z-10 flex items-start justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {badges.map((b) => (
              <span
                key={b}
                className="inline-flex h-[30px] items-center rounded-full border border-white/20 bg-[rgba(26,20,51,0.2)] px-3 text-xs font-semibold tracking-[-0.01em] text-white backdrop-blur-[11px]"
              >
                {b}
              </span>
            ))}
            {Boolean(card.is_distress) && (
              <span className="inline-flex h-[30px] items-center rounded-full bg-destructive px-3 text-xs font-semibold text-destructive-foreground">
                Distress
              </span>
            )}
          </div>
          {onToggleAttached ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggleAttached();
              }}
              aria-label="Ask AI about this listing"
              aria-pressed={attachedSelected}
              title={attachedSelected ? "Remove from AI chat" : "Ask AI about this listing"}
              className={cn(
                "pointer-events-auto flex size-[30px] shrink-0 items-center justify-center rounded-full",
                "focus:outline-none focus:ring-2 focus:ring-white/60",
                attachedSelected
                  ? "ring-2 ring-[#1B60F4] ring-offset-1 ring-offset-transparent bg-white/90"
                  : "hover:bg-white/20",
              )}
            >
              <img
                src="/AI_Icon.svg"
                alt=""
                width={30}
                height={30}
                className="size-[30px] shrink-0"
                aria-hidden
              />
            </button>
          ) : (
            <img
              src="/AI_Icon.svg"
              alt=""
              title="AI matched"
              width={30}
              height={30}
              className="size-[30px] shrink-0"
              aria-hidden
            />
          )}
        </div>

        {hasMultiple && (
          <>
            <button
              type="button"
              aria-label="Previous photo"
              onClick={(e) => {
                e.stopPropagation();
                setImageIndex((i) => (i - 1 + images.length) % images.length);
              }}
              className="pointer-events-auto absolute left-1.5 top-1/2 z-10 flex size-7 -translate-y-1/2 items-center justify-center rounded-full border border-white/30 bg-black/45 text-white backdrop-blur-sm hover:bg-black/65"
            >
              <ChevronLeft className="size-4" />
            </button>
            <button
              type="button"
              aria-label="Next photo"
              onClick={(e) => {
                e.stopPropagation();
                setImageIndex((i) => (i + 1) % images.length);
              }}
              className="pointer-events-auto absolute right-1.5 top-1/2 z-10 flex size-7 -translate-y-1/2 items-center justify-center rounded-full border border-white/30 bg-black/45 text-white backdrop-blur-sm hover:bg-black/65"
            >
              <ChevronRight className="size-4" />
            </button>
            <div className="absolute bottom-2 left-1/2 z-10 flex -translate-x-1/2 items-center gap-[3px] rounded-full bg-[rgba(8,8,9,0.12)] px-[3px] py-[3px] backdrop-blur-sm">
              {images.slice(0, 4).map((_, i) => (
                <button
                  key={i}
                  type="button"
                  aria-label={`Photo ${i + 1}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setImageIndex(i);
                  }}
                  className={cn(
                    "pointer-events-auto size-1.5 rounded-full",
                    i === imageIndex ? "bg-[#D8DDE6]" : "bg-white/30",
                  )}
                />
              ))}
            </div>
          </>
        )}
      </div>

      {/* Details column — body opens PropQA; WhatsApp / Call stay on the card */}
      <div
        className={cn(
          "relative z-[2] flex min-w-0 flex-1 flex-col items-stretch gap-3",
          "rounded-r-[20px] border border-l-0 border-[#E8ECF3] bg-white px-[18px] py-5",
        )}
      >
        <div className="flex min-h-0 flex-1 flex-col gap-2">
          {listingLink ? (
            <a
              {...listingLink}
              aria-label={`Open ${title} on PropQA`}
              className="flex min-h-0 flex-1 flex-col gap-2 no-underline outline-none hover:opacity-[0.92] focus-visible:ring-2 focus-visible:ring-[#E8ECF3]"
            >
              <SidebarFigmaCardBody
                card={card}
                title={title}
                location={location}
                priceAmount={priceAmount}
                agencyLogo={agencyLogo}
                agentImage={agentImage}
              />
            </a>
          ) : (
            <SidebarFigmaCardBody
              card={card}
              title={title}
              location={location}
              priceAmount={priceAmount}
              agencyLogo={agencyLogo}
              agentImage={agentImage}
            />
          )}
          {(beds || baths || area || type || (onToggleInquiry && propertyId)) ? (
            <div className="flex h-5 min-w-0 items-center gap-1">
              {listingLink ? (
                <a
                  {...listingLink}
                  aria-hidden
                  tabIndex={-1}
                  className="flex min-w-0 flex-1 flex-nowrap items-center gap-1 overflow-hidden no-underline"
                >
                  <FigmaSpecRow beds={beds} baths={baths} area={area} type={type} />
                </a>
              ) : (
                <div className="flex min-w-0 flex-1 flex-nowrap items-center gap-1 overflow-hidden">
                  <FigmaSpecRow beds={beds} baths={baths} area={area} type={type} />
                </div>
              )}
              {onToggleInquiry && propertyId ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleInquiry();
                  }}
                  title={inquirySelected ? "Remove from inquiry" : "Add to inquiry"}
                  aria-label={inquirySelected ? "Remove from inquiry" : "Add to inquiry"}
                  className={cn(
                    "inline-flex size-5 shrink-0 items-center justify-center rounded-full border transition-colors",
                    inquirySelected
                      ? "border-[#141B34] bg-[#141B34] text-white"
                      : "border-[#D8DDE6] text-[#494A58] hover:bg-[#F4F6FA]",
                  )}
                >
                  {inquirySelected ? (
                    <Check className="size-2.5" />
                  ) : (
                    <UserPlus className="size-2.5" />
                  )}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        {ctaEnabled ? (
          <ContactCtaIconRow
            variant="figma"
            subjectLabel={title}
            onCtaClick={onCtaClick}
            className="mt-auto min-w-0 w-full"
          />
        ) : null}
      </div>
    </article>
  );
}

function SidebarFigmaCardBody({
  card,
  title,
  location,
  priceAmount,
  agencyLogo,
  agentImage,
}: {
  card: PropertyCard;
  title: string;
  location: string | null;
  priceAmount: string | null;
  agencyLogo: string | null;
  agentImage: string | null;
}) {
  return (
    <>
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-1">
          <img
            src="/UAE_Dirham.svg"
            alt=""
            width={16}
            height={14}
            className="h-4 w-auto shrink-0"
            aria-hidden
          />
          <span className="truncate text-lg font-semibold leading-[1.4] text-[#101527]">
            {priceAmount ?? "On request"}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {agencyLogo && (
            <img
              src={agencyLogo}
              alt={String(card.agency_name ?? "Agency")}
              className="h-7 max-w-[68px] object-contain"
              loading="lazy"
            />
          )}
          {agentImage && (
            <img
              src={agentImage}
              alt={String(card.agent_name ?? "Agent")}
              className="size-7 rounded-full object-cover"
              loading="lazy"
            />
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-col gap-1.5">
        {location && (
          <p
            className="flex min-w-0 items-center gap-1 text-xs font-medium leading-[1.4] text-[#494A58]"
            title={location}
          >
            <MapPin className="size-3 shrink-0" strokeWidth={1.5} />
            <span className="truncate">{location}</span>
          </p>
        )}
        <p
          className="truncate text-sm font-medium leading-[1.4] text-[#101527]"
          title={title}
        >
          {title}
        </p>
      </div>
    </>
  );
}

function FigmaSpecRow({
  beds,
  baths,
  area,
  type,
}: {
  beds: string | null;
  baths: string | null;
  area: string | null;
  type: string | null;
}) {
  return (
    <>
      {beds && <FigmaSpecPill icon={<Bed className="size-2.5" />} label={beds} />}
      {baths && <FigmaSpecPill icon={<Bath className="size-2.5" />} label={baths} />}
      {area && <FigmaSpecPill icon={<Square className="size-2.5" />} label={area} />}
      {type && (
        <FigmaSpecPill
          icon={<Home className="size-2.5" />}
          label={type}
          className="min-w-0 shrink"
        />
      )}
    </>
  );
}

/** Compact vertical card for chat message strips. */
function StripCard({
  card,
  showCtas = false,
  onCtaClick,
}: {
  card: PropertyCard;
  showCtas?: boolean;
  onCtaClick?: (channel: CtaChannel) => void;
}) {
  const title = pickCardTitle(card);
  const address = String(card.address || card.location || "").trim() || null;
  const price = pickPriceLine(card);
  const showPrice = price !== "Price on request";
  const beds = pickBeds(card);
  const baths = pickBaths(card);
  const area = pickArea(card);
  const purpose = humanizePurpose(card.purpose);
  const completion = humanizeCompletion(card.completion_status ?? card.completion);
  const type = pickCardType(card);
  const addedOn = pickAddedOn(card);
  const cardImages = useMemo(() => pickCardImages(card), [card]);
  const { images, markFailed } = useWorkingImages(cardImages);
  const [imageIndex, setImageIndex] = useState(0);

  useEffect(() => {
    setImageIndex(0);
  }, [card.id]);

  // A photo that failed can shrink the list under the current index.
  const currentImage = images[imageIndex] ?? images[0];
  const hasMultiple = images.length > 1;

  const rawPath =
    (card.url as string | undefined) ||
    (card.link as string | undefined) ||
    (card.slug ? `/property/${String(card.slug)}` : null);
  const href = resolvePropqaUrl(rawPath);
  const propertyId = parsePropertyId(card);
  const ctaEnabled = showCtas && propertyId != null && onCtaClick;

  return (
    <article
      className={cn(
        "flex w-[280px] shrink-0 snap-start flex-col overflow-hidden rounded-xl border border-[#E8ECF3] bg-white text-[#141B34] shadow-sm transition-shadow hover:shadow-md",
      )}
    >
      <div className="group/gallery relative aspect-[4/3] w-full overflow-hidden bg-[#F5F7FA]">
        {currentImage ? (
          <img
            key={currentImage}
            onError={() => markFailed(currentImage)}
            src={currentImage}
            alt={`${title} — photo ${imageIndex + 1} of ${images.length}`}
            className="h-full w-full object-cover transition-opacity duration-200"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-muted-foreground">
            <span className="text-3xl" aria-hidden>
              🏢
            </span>
            <span className="text-[10px]">No image</span>
          </div>
        )}

        {Boolean(card.is_distress) && (
          <span className="absolute left-2 top-2 z-10 rounded-full bg-destructive px-2 py-0.5 text-[10px] font-semibold text-destructive-foreground shadow-sm">
            Distress
          </span>
        )}

        {hasMultiple && (
          <>
            <button
              type="button"
              aria-label="Previous photo"
              onClick={(e) => {
                e.stopPropagation();
                setImageIndex((i) => (i - 1 + images.length) % images.length);
              }}
              className="absolute left-1.5 top-1/2 z-10 flex size-7 -translate-y-1/2 items-center justify-center rounded-full border border-white/30 bg-black/50 text-white shadow-sm backdrop-blur-sm transition-colors hover:bg-black/70"
            >
              <ChevronLeft className="size-4" />
            </button>
            <button
              type="button"
              aria-label="Next photo"
              onClick={(e) => {
                e.stopPropagation();
                setImageIndex((i) => (i + 1) % images.length);
              }}
              className="absolute right-1.5 top-1/2 z-10 flex size-7 -translate-y-1/2 items-center justify-center rounded-full border border-white/30 bg-black/50 text-white shadow-sm backdrop-blur-sm transition-colors hover:bg-black/70"
            >
              <ChevronRight className="size-4" />
            </button>
            <span className="absolute bottom-2 right-2 z-10 rounded-md bg-black/55 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
              {imageIndex + 1} / {images.length}
            </span>
          </>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2.5 p-3">
        <p className="truncate text-sm font-semibold text-[#141B34]" title={title}>
          {title}
        </p>

        {address && (
          <p
            className="flex min-w-0 items-center gap-1 truncate text-[11px] text-[#747288]"
            title={address}
          >
            <MapPin className="size-3 shrink-0" />
            <span className="truncate">{address}</span>
          </p>
        )}

        {(showPrice || beds || baths || area || purpose || type || completion || addedOn || propertyId) && (
          <div className="relative min-h-[26px]">
            <div
              className={cn(
                "flex flex-wrap items-center gap-1.5",
                propertyId && "pr-12",
              )}
            >
              {showPrice && (
                <span className="inline-flex shrink-0 items-center rounded-md border border-[#E8ECF3] bg-white px-2 py-1 text-[10px] font-bold tracking-tight text-[#141B34]">
                  {price}
                </span>
              )}
              {beds && (
                <SpecPill icon={<Bed className="size-3" />} label={beds} title={`${beds} beds`} />
              )}
              {baths && (
                <SpecPill icon={<Bath className="size-3" />} label={baths} title={`${baths} baths`} />
              )}
              {area && (
                <SpecPill icon={<Square className="size-3" />} label={area} title={`${area} sqft`} />
              )}
              {purpose && <MetaPill label={purpose} />}
              {type && <MetaPill label={type} />}
              {completion && <MetaPill label={completion} />}
              {addedOn && (
                <MetaPill icon={<Calendar className="size-3" />} label={addedOn} />
              )}
            </div>
            {propertyId && (
              <PropertyIdPill id={propertyId} className="absolute bottom-0 right-0" />
            )}
          </div>
        )}

        {(ctaEnabled || href) && (
          <ContactCtaIconRow
            subjectLabel={title}
            onCtaClick={ctaEnabled ? onCtaClick : undefined}
            propqaHref={href}
          />
        )}
      </div>
    </article>
  );
}

function FigmaSpecPill({
  icon,
  label,
  className,
}: {
  icon: ReactNode;
  label: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-5 max-w-full shrink-0 items-center gap-0.5 rounded-full border border-[#E8ECF3] px-1.5 text-[10px] font-medium leading-none text-[#141B34]",
        className,
      )}
    >
      <span className="shrink-0 text-[#494A58]">{icon}</span>
      <span className="truncate">{label}</span>
    </span>
  );
}

function PropertyIdPill({ id, className }: { id: number; className?: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(String(id));
      setCopied(true);
      toast.success(`Copied property ID ${id}`);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy property ID");
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      title="Click to copy property ID"
      className={cn(
        "inline-flex cursor-copy items-center rounded-md border border-dashed border-[#D8DDE6] bg-white px-2 py-1 text-[10px] font-medium text-[#747288] transition-colors hover:border-[#979CAE] hover:bg-[#F5F7FA] hover:text-[#141B34]",
        className,
      )}
    >
      {copied ? "Copied" : id}
    </button>
  );
}

function SpecPill({ icon, label, title }: { icon: ReactNode; label: string; title?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-[#E8ECF3] bg-white px-2 py-1 text-[10px] font-medium text-[#141B34]"
      title={title}
    >
      {icon}
      {label}
    </span>
  );
}

function MetaPill({
  label,
  icon,
}: {
  label: string;
  icon?: ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-[#E8ECF3] bg-white px-2 py-1 text-[10px] font-medium text-[#141B34]">
      {icon}
      {label}
    </span>
  );
}
