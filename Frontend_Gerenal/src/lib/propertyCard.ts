import type { PropertyCard } from "@/store/chatStore";
import { resolvePropqaUrl } from "@/lib/utils";

/** Collapse repeated comma-separated title segments. */
export function dedupeTitle(raw: unknown): string {
  if (raw == null) return "";
  const text = String(raw).trim();
  if (!text) return "";
  const seen = new Set<string>();
  const kept: string[] = [];
  for (const part of text.split(",")) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const key = trimmed.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    kept.push(trimmed);
  }
  return kept.join(", ");
}

const _PIPE_PURPOSE_RE = /^(for\s+)?(sale|rent)$/i;
const _PIPE_BEDS_RE = /^\d+\s*(b\/?r|bed(room)?s?)$/i;
const _PIPE_TYPE_RE =
  /^(apartment|apartments|villa|villas|townhouse|townhouses|penthouse|studio|office|shop|warehouse|land|plot|duplex|hotel\s*apartment)$/i;

/**
 * PropQA ``title_en`` is often pipe-delimited metadata
 * (``2 B/R | Apartment | Place, Community, Dubai | for Sale``).
 * Return the place / headline segment(s), not the beds/type/purpose wrappers.
 */
export function cleanPropQaPipeTitle(raw: unknown): string | null {
  if (raw == null) return null;
  const text = String(raw).trim();
  if (!text) return null;
  if (!text.includes("|")) {
    const plain = dedupeTitle(text);
    return plain || null;
  }
  const parts = text
    .split("|")
    .map((p) => p.trim())
    .filter(Boolean)
    .filter((p) => {
      const low = p.toLowerCase();
      if (_PIPE_PURPOSE_RE.test(low)) return false;
      if (_PIPE_BEDS_RE.test(low)) return false;
      return true;
    });
  const rich = parts.filter((p) => !_PIPE_TYPE_RE.test(p));
  const chosen = (rich.length > 0 ? rich : parts).join(", ");
  const cleaned = dedupeTitle(chosen);
  return cleaned || null;
}

export function pickCardTitle(card: PropertyCard): string {
  const tryValue = (v: unknown) => {
    if (v == null) return null;
    const s = String(v).trim();
    return s || null;
  };
  const cleaned = cleanPropQaPipeTitle(
    card.title_en ?? card.title ?? card.headline ?? card.name,
  );
  if (cleaned) return cleaned;
  const titleEn = dedupeTitle(
    card.title_en ?? card.title ?? card.headline ?? card.name,
  );
  return titleEn || tryValue(card.address) || "Untitled property";
}

/**
 * Figma sidebar title: prefer cleaned place headline; when that duplicates
 * the location row, fall back to ``{n} Bedroom {Type}``.
 */
export function pickFigmaCardTitle(card: PropertyCard): string {
  const location = pickCardLocation(card);
  const cleaned = cleanPropQaPipeTitle(
    card.title_en ?? card.title ?? card.headline ?? card.name,
  );
  if (cleaned) {
    if (!location || cleaned.toLowerCase() !== location.toLowerCase()) {
      return cleaned;
    }
  }
  const beds = pickBeds(card);
  const type = pickCardType(card);
  if (beds && type) {
    const n = Number(beds);
    if (Number.isFinite(n) && n === 0) return `Studio ${type}`;
    return `${beds} Bedroom ${type}`;
  }
  if (type) return type;
  return pickCardTitle(card);
}

/** Tiered price line (mirrors legacy pickPriceLine / backend _format_price_band). */
export function pickPriceLine(card: PropertyCard): string {
  const fmt = (n: number) => `AED ${n.toLocaleString()}`;
  const min =
    card.price_min != null && card.price_min !== ""
      ? Number(card.price_min)
      : null;
  const max =
    card.price_max != null && card.price_max !== ""
      ? Number(card.price_max)
      : null;

  if (Number.isFinite(min) && Number.isFinite(max) && max! > min!) {
    return `${fmt(min!)} – ${fmt(max!)}`;
  }
  if (Number.isFinite(min)) return fmt(min!);
  if (Number.isFinite(max)) return fmt(max!);
  if (card.yearly_price != null && card.yearly_price !== "")
    return `${fmt(Number(card.yearly_price))} / year`;
  if (card.monthly_price != null && card.monthly_price !== "")
    return `${fmt(Number(card.monthly_price))} / month`;
  if (card.weekly_price != null && card.weekly_price !== "")
    return `${fmt(Number(card.weekly_price))} / week`;
  if (card.daily_price != null && card.daily_price !== "")
    return `${fmt(Number(card.daily_price))} / night`;
  if (card.price_band) return String(card.price_band);
  if (card.price != null) {
    const p = Number(card.price);
    if (Number.isFinite(p)) return fmt(p);
    return String(card.price);
  }
  return "Price on request";
}

export function humanizePurpose(purpose: unknown): string | null {
  if (!purpose) return null;
  const key = String(purpose).toLowerCase().replace(/\s+/g, "_");
  const map: Record<string, string> = {
    for_sale: "For Sale",
    for_rent: "For Rent",
    sale: "For Sale",
    rent: "For Rent",
  };
  return map[key] ?? String(purpose).replace(/_/g, " ");
}

export function humanizeCompletion(completion: unknown): string | null {
  if (!completion) return null;
  const s = String(completion).trim();
  if (!s) return null;
  return s
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Figma image-overlay pills: Off-Plan / Ready to Move (empty when unknown).
 */
export function pickCompletionBadges(completion: unknown): string[] {
  if (!completion) return [];
  const key = String(completion).trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (!key) return [];
  if (
    key.includes("off_plan") ||
    key.includes("offplan") ||
    key === "off_plan" ||
    key === "offplan"
  ) {
    return ["Off-Plan"];
  }
  if (
    key.includes("ready") ||
    key.includes("completed") ||
    key.includes("complete") ||
    key === "ready_to_move"
  ) {
    return ["Ready to Move"];
  }
  const label = humanizeCompletion(completion);
  return label ? [label] : [];
}

/** Numeric/display price without the leading "AED " (Figma uses a dirham mark). */
export function pickPriceAmount(card: PropertyCard): string | null {
  const line = pickPriceLine(card);
  if (!line || line === "Price on request") return null;
  return line.replace(/^AED\s+/i, "").trim() || null;
}

/** Prefer building/project location string for the Figma location row. */
export function pickCardLocation(card: PropertyCard): string | null {
  const parts = [
    card.building_name,
    card.project_name,
    card.master_project_name,
    card.address,
    card.location,
  ]
    .map((v) => (v == null ? "" : String(v).trim()))
    .filter(Boolean);
  if (parts.length === 0) return null;
  // Dedupe while preserving order
  const seen = new Set<string>();
  const kept: string[] = [];
  for (const p of parts) {
    const k = p.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    kept.push(p);
  }
  // Prefer a short "Building, Project" style when we have structure
  if (card.building_name || card.project_name) {
    return [card.building_name, card.project_name, card.master_project_name]
      .map((v) => (v == null ? "" : String(v).trim()))
      .filter(Boolean)
      .filter((v, i, arr) => arr.findIndex((x) => x.toLowerCase() === v.toLowerCase()) === i)
      .join(", ");
  }
  return kept[0] ?? null;
}

export function pickAgencyLogoUrl(card: PropertyCard): string | null {
  const v = card.agency_logo_url ?? card.agency_logo;
  const s = v == null ? "" : String(v).trim();
  return s || null;
}

export function pickAgentImageUrl(card: PropertyCard): string | null {
  const v = card.agent_image_url ?? card.agent_image ?? card.agent_avatar;
  const s = v == null ? "" : String(v).trim();
  return s || null;
}

export function humanizeType(type: unknown): string | null {
  if (!type) return null;
  const s = String(type).trim();
  return s || null;
}

/** Infer property type from PropQA pipe-separated title_en (e.g. "Villas | Marina | for Sale"). */
export function inferTypeFromTitle(title: unknown): string | null {
  if (!title) return null;
  const text = String(title).trim();
  if (!text.includes("|")) return null;
  const first = text.split("|", 1)[0]?.trim();
  if (!first) return null;
  const low = first.toLowerCase();
  if (low === "for sale" || low === "for rent" || low === "sale" || low === "rent") {
    return null;
  }
  return first;
}

/** Resolve Type from card fields (Property Information section). */
export function pickCardType(card: PropertyCard): string | null {
  return (
    humanizeType(card.type) ||
    humanizeType(card.subcategory_name) ||
    inferTypeFromTitle(card.title_en ?? card.title ?? card.headline ?? card.name) ||
    null
  );
}

/** All listing photos (deduped), primary image first. */
export function pickCardImages(card: PropertyCard): string[] {
  const urls: string[] = [];
  const seen = new Set<string>();
  const add = (raw: unknown) => {
    const s = String(raw ?? "").trim();
    if (!s || seen.has(s)) return;
    seen.add(s);
    urls.push(s);
  };
  add(card.image_url);
  if (Array.isArray(card.images)) {
    for (const img of card.images) add(img);
  }
  return urls;
}

export function pickCardImage(card: PropertyCard): string | undefined {
  return pickCardImages(card)[0];
}

export function pickAddedOn(card: PropertyCard): string | null {
  const raw =
    card.added_on ??
    card.created_at ??
    card.listed_at ??
    card.updated_at ??
    null;
  if (!raw) return null;
  const d = new Date(String(raw));
  if (!Number.isFinite(d.getTime())) return String(raw);
  const day = String(d.getDate()).padStart(2, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const year = String(d.getFullYear()).slice(-2);
  return `${day}/${month}/${year}`;
}

export function pickBeds(card: PropertyCard): string | null {
  const v = card.rooms ?? card.bedrooms ?? card.beds;
  if (v == null || v === "") return null;
  const n = Number(v);
  if (Number.isFinite(n)) return String(n);
  return String(v);
}

export function pickBaths(card: PropertyCard): string | null {
  const v = card.baths ?? card.bathrooms;
  if (v == null || v === "") return null;
  const n = Number(v);
  if (Number.isFinite(n)) return String(n);
  return String(v);
}

export function pickArea(card: PropertyCard): string | null {
  const v = card.area_sqft ?? card.area;
  if (v == null || v === "") return null;
  const n = Number(v);
  if (Number.isFinite(n)) return n.toLocaleString();
  return String(v);
}

/** Absolute PropQA listing URL, or null when the card has no path/slug. */
export function pickCardListingHref(card: PropertyCard): string | null {
  const url = typeof card.url === "string" ? card.url.trim() : "";
  const link = typeof card.link === "string" ? card.link.trim() : "";
  if (url || link) {
    return resolvePropqaUrl(url || link);
  }

  const slug = typeof card.slug === "string" ? card.slug.trim().replace(/^\/+/, "") : "";
  const rawId = card.id ?? card.property_id;
  const idNum =
    typeof rawId === "number"
      ? rawId
      : rawId != null && rawId !== ""
        ? parseInt(String(rawId), 10)
        : NaN;
  const id = Number.isFinite(idNum) && idNum > 0 ? idNum : null;

  // Live listings are /property/{slug}-{id} (e.g. …-semi-furnished-17258).
  if (slug) {
    const withId =
      id != null && !new RegExp(`-${id}$`).test(slug) ? `${slug}-${id}` : slug;
    return resolvePropqaUrl(`/property/${withId}`);
  }
  if (id != null) {
    return resolvePropqaUrl(`/property/${id}`);
  }
  return null;
}
