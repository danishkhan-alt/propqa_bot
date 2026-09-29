import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Human-readable duration for response-generation timing (e.g. "12.4s", "1m 5s"). */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

export function formatRelativeTime(date: Date | string | number | null): string {
  if (!date) return "";
  const ts = typeof date === "number" ? date : new Date(date).getTime();
  if (!Number.isFinite(ts)) return "";
  const diff = Date.now() - ts;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return new Date(ts).toLocaleDateString();
}

export function truncate(text: string, maxLength = 80): string {
  if (!text) return "";
  return text.length > maxLength ? text.slice(0, maxLength) + "…" : text;
}

/** Production site for PropQA property and search deep links. */
export const PROPQA_SITE_BASE = "https://propqa.ai";

/** Building guide page on propqa.ai, e.g. https://propqa.ai/buildings/dubai/trident-bayside. */
export function buildPropqaBuildingUrl(slug: string): string {
  return `${PROPQA_SITE_BASE}/buildings/dubai/${encodeURIComponent(slug.trim().replace(/^\/+|\/+$/g, ""))}`;
}

/** PropQA WhatsApp Business number (inquiries routed via PropQA, not direct to agents). */
export const PROPQA_WHATSAPP_NUMBER = "971557767201";

/** Pre-filled WhatsApp inquiry sent to PropQA for listing follow-up. */
export function buildPropqaWhatsAppMessage(propqaUrl: string | null | undefined): string {
  const url = propqaUrl?.trim() ?? "";
  return [
    "Hello, I am interested in this property listed on PropQA.",
    url,
    "Please share more details.",
    "Important: Kindly do not edit this message so your inquiry reaches the right person!",
  ]
    .filter(Boolean)
    .join("\n");
}

/** Opens WhatsApp chat with PropQA using the standard inquiry template. */
export function buildPropqaWhatsAppUrl(message: string): string {
  return `https://api.whatsapp.com/send?phone=${PROPQA_WHATSAPP_NUMBER}&text=${encodeURIComponent(message)}`;
}

/** Canonical listing path on propqa.ai (singular `/property/`, not `/properties/`). */
function normalizePropertyPath(pathname: string): string {
  if (/^\/properties\//i.test(pathname)) {
    return pathname.replace(/^\/properties\//i, "/property/");
  }
  return pathname;
}

/**
 * Resolve a property or search path to an absolute PropQA URL.
 * Listing paths use `https://propqa.ai/property/{slug}`.
 * Localhost URLs from dev are rewritten to propqa.ai.
 */
export function resolvePropqaUrl(pathOrUrl: string | null | undefined): string | null {
  if (!pathOrUrl || pathOrUrl === "#") return null;
  const s = pathOrUrl.trim();
  if (!s) return null;

  if (/^https?:\/\//i.test(s)) {
    try {
      const u = new URL(s);
      const path = normalizePropertyPath(u.pathname);
      if (u.hostname === "localhost" || u.hostname === "127.0.0.1") {
        return `${PROPQA_SITE_BASE}${path}${u.search}${u.hash}`;
      }
      if (path !== u.pathname) {
        return `${u.origin}${path}${u.search}${u.hash}`;
      }
      return s;
    } catch {
      return s;
    }
  }

  if (s.startsWith("/")) {
    return `${PROPQA_SITE_BASE}${normalizePropertyPath(s)}`;
  }

  return `${PROPQA_SITE_BASE}/property/${s.replace(/^\/+/, "")}`;
}
