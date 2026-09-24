import { useMemo } from "react";
import { ChevronRight, Home } from "lucide-react";
import { useWorkingImages } from "@/hooks/useWorkingImages";
import { pickCardImages } from "@/lib/propertyCard";
import type { PropertyCard } from "@/store/chatStore";

interface ListingSummaryProps {
  cards: PropertyCard[];
  /** Opens the properties panel, where the full cards live. */
  onOpen?: () => void;
}

const THUMBNAILS = 3;

/** In-chat pointer to a result set. The full cards stay in the properties panel. */
export function ListingSummary({ cards, onOpen }: ListingSummaryProps) {
  const firstImages = useMemo(
    () => cards.map((card) => pickCardImages(card)[0]).filter((url): url is string => Boolean(url)),
    [cards],
  );
  const { images, markFailed } = useWorkingImages(firstImages);
  if (cards.length === 0) return null;
  const thumbnails = images.slice(0, THUMBNAILS);
  const range = priceRange(cards);
  const noun = cards.length === 1 ? "property" : "properties";

  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!onOpen}
      className="group/summary flex w-full max-w-[520px] items-center gap-3 rounded-2xl border border-[#E8ECF3] bg-white px-3 py-2.5 text-left shadow-[0px_0px_20px_3px_rgba(20,20,24,0.04)] transition-colors enabled:hover:border-[#D8DDE6] enabled:hover:bg-[#FAFBFC]"
      aria-label={`View ${cards.length} ${noun} in the properties panel`}
    >
      <div className="flex shrink-0 -space-x-3">
        {thumbnails.length > 0 ? (
          thumbnails.map((image) => (
            <img
              key={image}
              src={image}
              alt=""
              onError={() => markFailed(image)}
              className="size-11 rounded-xl border-2 border-white object-cover"
              loading="lazy"
            />
          ))
        ) : (
          <span className="flex size-11 items-center justify-center rounded-xl bg-[#F5F7FA] text-[#979CAE]">
            <Home className="size-5" aria-hidden />
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-[#101527]">
          {cards.length} {noun} matched
        </p>
        {range && <p className="truncate text-xs text-[#747288]">{range}</p>}
      </div>
      {onOpen && (
        <span className="flex shrink-0 items-center gap-0.5 text-xs font-medium text-[#1B60F4]">
          View
          <ChevronRight className="size-3.5 transition-transform group-hover/summary:translate-x-0.5" aria-hidden />
        </span>
      )}
    </button>
  );
}

/** "AED 1.2M – 1.44M" from sale prices on the cards; null when none are shown. */
function priceRange(cards: PropertyCard[]): string | null {
  const prices = cards
    .map((card) => Number(card.price_min ?? card.price_max))
    .filter((value) => Number.isFinite(value) && value > 0);
  if (prices.length === 0) return null;
  const low = Math.min(...prices);
  const high = Math.max(...prices);
  return low === high ? `AED ${compact(low)}` : `AED ${compact(low)} – ${compact(high)}`;
}

function compact(value: number): string {
  if (value >= 1_000_000) return `${trim(value / 1_000_000)}M`;
  if (value >= 1_000) return `${trim(value / 1_000)}K`;
  return value.toLocaleString();
}

function trim(value: number): string {
  return value.toFixed(2).replace(/\.?0+$/, "");
}
