/** Follow-up chip from the backend result envelope. */
export interface FollowUpSuggestion {
  label: string;
  rebuilt_query: string;
}

/** Parse envelope.suggestions (objects or legacy strings) into chip payloads. */
export function parseEnvelopeSuggestions(
  env: Record<string, unknown> | null | undefined,
): FollowUpSuggestion[] {
  if (!env || !Array.isArray(env.suggestions)) return [];
  const out: FollowUpSuggestion[] = [];
  for (const raw of env.suggestions) {
    if (typeof raw === "string") {
      const text = raw.trim();
      if (text) out.push({ label: text, rebuilt_query: text });
      continue;
    }
    if (!raw || typeof raw !== "object") continue;
    const o = raw as Record<string, unknown>;
    const rebuilt = String(o.rebuilt_query ?? o.label ?? "").trim();
    const label = String(o.label ?? rebuilt).trim();
    if (label && rebuilt) out.push({ label, rebuilt_query: rebuilt });
  }
  return out.slice(0, 4);
}

export const MAX_INQUIRY_PROPERTY_IDS = 5;

/** Max listings attachable to the composer for listing-scoped FAQ mode. */
export const MAX_ATTACHED_PROPERTY_IDS = 8;

/** Visible chip count before the "+N more" overflow control. */
export const VISIBLE_ATTACHED_CHIP_COUNT = 3;

/** Composer chip payload for a listing attached via the sidebar AI icon. */
export interface AttachedListing {
  id: number;
  title: string;
  imageUrl?: string;
}

/** Name the attached listings inside a short chip prompt so the search is not just "this listing". */
export function withListingContext(message: string, listings: AttachedListing[]): string {
  const names = listings.map((item) => item.title.trim()).filter(Boolean).slice(0, 3);
  if (!names.length) return message;
  const named = names.length === 1 ? names[0] : names.join("; ");
  if (/this listing/i.test(message)) {
    const replacement = names.length === 1 ? named : `these listings (${named})`;
    return message.replace(/this listing/gi, replacement);
  }
  return `${message} The ${names.length === 1 ? "listing is" : "listings are"} ${named}.`;
}

export const LISTING_FAQ_SUGGESTION_CHIPS: { label: string; message: string }[] = [
  { label: "Price", message: "What is the price of this listing?" },
  { label: "Size and layout", message: "Tell me about the size and layout of this listing." },
  { label: "Amenities", message: "What amenities does this listing include?" },
  { label: "Location", message: "Where is this listing located and what's nearby?" },
];

/**
 * True when the user is starting a new catalog search (beds + type / find verbs).
 * Used to auto-dismiss attach chips so listing-FAQ mode does not answer
 * inventory queries about the previously attached listing.
 */
export function looksLikeFreshInventorySearch(text: string): boolean {
  const q = text.trim().toLowerCase();
  if (q.length < 8) return false;
  // Keep short FAQ prompts on the attached listing.
  if (
    /^(what|where|which|who|how|tell me about|price|size|amenities|location)\b/.test(q) &&
    !/\b(villa|villas|apartment|apartments|townhouse|studio|penthouse)\b/.test(q)
  ) {
    return false;
  }
  const hasType =
    /\b(villa|villas|apartment|apartments|townhouse|townhouses|studio|studios|penthouse|penthouses)\b/.test(
      q,
    );
  const hasBeds = /\b\d+\s*-?\s*(bed|beds|br|b\/r|bedroom|bedrooms)\b/.test(q);
  const hasSearchVerb =
    /\b(provide|show|find|search|list|looking for|want|need|get me)\b/.test(q);
  return (hasType && (hasBeds || hasSearchVerb)) || (hasBeds && hasSearchVerb);
}
