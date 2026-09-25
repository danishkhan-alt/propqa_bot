/**
 * Shared property ID extraction — mirrors backend _resolve_property_ids.
 */

import { pickCardTitle } from "@/lib/propertyCard";
import type { PropertyCard } from "@/store/chatStore";

/** Parse a single card's marketplace property row ID. */
export function parsePropertyId(card: PropertyCard): number | null {
  const raw = card.id ?? (card as { property_id?: unknown }).property_id;
  if (raw == null || raw === "") return null;
  const n = typeof raw === "number" ? raw : parseInt(String(raw), 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Collect unique numeric property IDs from a card list. */
export function cardPropertyIds(cards: PropertyCard[] | unknown[] | undefined): number[] {
  if (!cards?.length) return [];
  const seen = new Set<number>();
  for (const card of cards as PropertyCard[]) {
    const id = parsePropertyId(card);
    if (id !== null) seen.add(id);
  }
  return [...seen];
}

/** Map property ID → display title for listing coverage UI. */
export function propertyTitleMap(
  cards: PropertyCard[] | unknown[] | undefined,
): Record<number, string> {
  const out: Record<number, string> = {};
  if (!cards?.length) return out;
  for (const card of cards as PropertyCard[]) {
    const id = parsePropertyId(card);
    if (id !== null) out[id] = pickCardTitle(card);
  }
  return out;
}
