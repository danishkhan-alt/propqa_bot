import { marked } from "marked";

marked.setOptions({
  breaks: true,
  gfm: true,
});

// ── HTML helpers ─────────────────────────────────────────────────────────────

function escapeHtml(value: string): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeHtmlAttr(value: string): string {
  return escapeHtml(value);
}

function decodeHtmlEntities(value: string): string {
  if (typeof document === "undefined") return value;
  const el = document.createElement("textarea");
  el.innerHTML = value;
  return el.value;
}

// ── Content sanitisation (listing images stripped from display) ──────────────

export function stripMarkdownImages(text: string): string {
  return text.replace(/!\[[^\]]*\]\([^)]+\)/g, "");
}

export function stripListingImageLines(text: string): string {
  if (!text) return text;
  const lines = text.split(/\r?\n/);
  const filtered = lines.filter((line) => {
    const t = line.trim();
    if (!t) return true;
    if (/^[-*]\s*\*?\*?(image|photo|picture)s?\*?\*?\s*:/i.test(t)) return false;
    if (/^\*?\*?(image|photo|picture)s?\*?\*?\s*:/i.test(t)) return false;
    if (/^#{1,6}\s+.*\b(image|photo|picture)\s*:/i.test(t)) return false;
    if (/https?:\/\/\S+\.(jpg|jpeg|png|gif|webp)(\?\S*)?$/i.test(t)) return false;
    return true;
  });
  return filtered.join("\n");
}

export function assistantPlainTextStored(raw: string): string {
  return stripListingImageLines(raw);
}

const YIELD_WORKSHEET_HEAD =
  /^(?:#{1,6}\s*)?How this number was calculated\b/i;

/** True when the stored bubble is only the yield verification block. */
export function isYieldWorksheetOnly(text: string): boolean {
  const t = (text || "").trim();
  return t.length > 0 && YIELD_WORKSHEET_HEAD.test(t);
}

/** Short public-mode % list / empty-yield stub — must not replace a narrative. */
export function isYieldPublicStub(text: string): boolean {
  const t = (text || "").trim();
  if (!t) return false;
  if (/I don't have a reliable rental yield/i.test(t) && t.length < 400) {
    return true;
  }
  if (t.length >= 500 || !/Uncapped/i.test(t) || !/Median/i.test(t)) {
    return false;
  }
  const lines = t.split(/\n/).map((line) => line.trim()).filter(Boolean);
  return lines.length <= 8;
}

/**
 * Session restore must not prefer a worksheet-only stub over the
 * streamed yield narrative (or vice versa when the envelope is richer).
 */
export function pickRestoredAssistantText(
  assistantMessage: string,
  answerMd: string,
): string {
  const asst = (assistantMessage || "").trim();
  const env = (answerMd || "").trim();
  if (asst && !isYieldWorksheetOnly(asst) && !isYieldPublicStub(asst)) return asst;
  if (env && !isYieldWorksheetOnly(env) && !isYieldPublicStub(env)) return env;
  return env.length > asst.length ? env : asst;
}

// ── PropQA search link → CTA card ────────────────────────────────────────────

const PROPQA_SEARCH_HOST = /propqa\.ai\/search/i;

function iconExternalLink(): string {
  return `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>`;
}

function iconArrowRight(): string {
  return `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>`;
}

function cleanCtaLabel(raw: string): string {
  return decodeHtmlEntities(raw)
    .replace(/\*\*/g, "")
    .replace(/\s*(?:→|->|&rarr;)\s*$/u, "")
    .replace(/\s+/g, " ")
    .trim();
}

function formatPurpose(purpose: string): string | null {
  const map: Record<string, string> = {
    for_sale: "For sale",
    for_rent: "For rent",
    off_plan: "Off-plan",
  };
  return map[purpose] ?? purpose.replace(/_/g, " ");
}

function formatSubcategory(sub: string): string {
  return sub
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Build human-readable filter chips from a PropQA search URL. */
function describeSearchUrl(url: string): string {
  try {
    const u = new URL(url);
    const p = u.searchParams;
    const parts: string[] = [];

    const purpose = p.get("purpose");
    if (purpose) parts.push(formatPurpose(purpose) ?? purpose);

    const sub = p.get("subcategory");
    if (sub) parts.push(formatSubcategory(sub));

    const bed = p.get("bedroom") ?? p.get("bedrooms");
    if (bed) parts.push(`${bed} bed`);

    const address = p.get("address");
    if (address) parts.push(decodeURIComponent(address.replace(/\+/g, " ")));

    if (parts.length > 0) return parts.join(" · ");
    return "Opens propqa.ai in a new tab";
  } catch {
    return "Opens propqa.ai in a new tab";
  }
}

function buildPropqaCtaCard(label: string, url: string): string {
  const safeUrl = escapeHtmlAttr(url);
  const safeLabel = escapeHtml(label);
  const subtitle = escapeHtml(describeSearchUrl(url));

  return `<a class="propqa-cta-card" href="${safeUrl}" target="_blank" rel="noopener noreferrer" aria-label="${safeLabel} (opens in new tab)">
      <span class="propqa-cta-card__icon" aria-hidden="true">${iconExternalLink()}</span>
      <span class="propqa-cta-card__body">
        <span class="propqa-cta-card__title">${safeLabel}</span>
        <span class="propqa-cta-card__subtitle">${subtitle}</span>
      </span>
      <span class="propqa-cta-card__arrow" aria-hidden="true">${iconArrowRight()}</span>
    </a>`;
}

/**
 * Replace markdown-rendered PropQA search paragraphs with styled CTA cards.
 */
export function wrapPropqaCtas(html: string): string {
  if (!html || !/propqa/i.test(html)) return html;

  let out = html;

  // 1) <strong>Label →</strong> <a href="...">...</a>
  const strongLinkRe =
    /<p>\s*<strong>([^<]*?PropQA\s*(?:→|->|&rarr;)[^<]*?)<\/strong>\s*(?:<br\s*\/?>|\s)*\s*<a\s+href="(https?:\/\/[^"]+)"[^>]*>[^<]*<\/a>\s*<\/p>/gi;
  out = out.replace(strongLinkRe, (_m, rawLabel, rawUrl) =>
    buildPropqaCtaCard(cleanCtaLabel(rawLabel), rawUrl),
  );

  // 2) Plain label text (no strong) + anchor — e.g. "View … on PropQA → <a>"
  const plainLinkRe =
    /<p>([^<]*?PropQA\s*(?:→|->|&rarr;)[^<]*?)\s*<a\s+href="(https?:\/\/[^"]+)"[^>]*>[^<]*<\/a>\s*<\/p>/gi;
  out = out.replace(plainLinkRe, (_m, rawLabel, rawUrl) => {
    if (!PROPQA_SEARCH_HOST.test(rawUrl)) return _m;
    return buildPropqaCtaCard(cleanCtaLabel(rawLabel), rawUrl);
  });

  // 3) Label + bare URL in paragraph (autolink did not wrap)
  const plainUrlRe =
    /<p>([^<]*?PropQA\s*(?:→|->|&rarr;)[^<]*?)\s*(https?:\/\/propqa\.ai\/search[^\s<"]+)\s*<\/p>/gi;
  out = out.replace(plainUrlRe, (_m, rawLabel, rawUrl) =>
    buildPropqaCtaCard(cleanCtaLabel(rawLabel), rawUrl.trim()),
  );

  // 4) Paragraph that is only a propqa.ai/search anchor (URL shown as link text)
  const loneSearchLinkRe =
    /<p>\s*<a\s+href="(https?:\/\/propqa\.ai\/search[^"]*)"[^>]*>[^<]*<\/a>\s*<\/p>/gi;
  out = out.replace(loneSearchLinkRe, (_m, rawUrl) =>
    buildPropqaCtaCard("View results on PropQA", rawUrl),
  );

  // 5) Any remaining inline propqa search <a> whose visible text is the raw URL
  const inlineUrlLinkRe =
    /<a\s+href="(https?:\/\/propqa\.ai\/search[^"]*)"[^>]*>https?:\/\/propqa\.ai\/search[^<]*<\/a>/gi;
  out = out.replace(inlineUrlLinkRe, (_m, rawUrl) =>
    buildPropqaCtaCard("View results on PropQA", rawUrl),
  );

  return out;
}

function wrapCodeBlocks(html: string): string {
  return html.replace(
    /<pre><code(?:\s+class="language-(\w+)")?>([\s\S]*?)<\/code><\/pre>/g,
    (_match, lang, code) => {
      const langDisplay = lang || "code";
      return `<div class="code-block-wrapper">
        <div class="code-block-header">
          <span class="code-block-lang">${langDisplay}</span>
          <button type="button" class="code-copy-btn" aria-label="Copy code">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            <span>Copy</span>
          </button>
        </div>
        <pre><code${lang ? ` class="language-${lang}"` : ""}>${code}</code></pre>
      </div>`;
    },
  );
}

function wrapTables(html: string): string {
  return html.replace(
    /<table>([\s\S]*?)<\/table>/g,
    (_match, inner) => `<div class="table-wrapper"><table>${inner}</table></div>`,
  );
}

const REDACTED_HEADER_RE = /id redacted|transaction\s*id|contract\s*id|procedure\s*id/i;

function splitMdRow(line: string): string[] {
  let raw = line.trim();
  if (raw.startsWith("|")) raw = raw.slice(1);
  if (raw.endsWith("|")) raw = raw.slice(0, -1);
  return raw.split("|").map((c) => c.trim());
}

/** Drop cut-off last rows and id-redaction columns so GFM can render a closed table. */
export function sanitizeIncompleteMarkdownTable(text: string): string {
  if (!text || !text.includes("|")) return text;
  const lines = text.split(/\r?\n/);
  const out: string[] = [];
  let dropIdx: Set<number> | null = null;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("|")) {
      dropIdx = null;
      out.push(line);
      continue;
    }
    if (!trimmed.endsWith("|")) {
      continue;
    }
    const cells = splitMdRow(line);
    const isSep = cells.every((c) => /^:?-{1,}:?$/.test(c) || c === "");
    if (dropIdx === null && cells.some((c) => REDACTED_HEADER_RE.test(c))) {
      dropIdx = new Set(
        cells
          .map((c, i) => (REDACTED_HEADER_RE.test(c) ? i : -1))
          .filter((i) => i >= 0),
      );
    }
    const kept =
      dropIdx && dropIdx.size > 0
        ? cells.filter((_, i) => !dropIdx!.has(i))
        : cells;
    if (isSep) {
      out.push("|" + kept.map(() => "---").join("|") + "|");
    } else {
      out.push("| " + kept.join(" | ") + " |");
    }
  }
  const joined = collapseDuplicateMarkdownColumns(out.join("\n"));
  const shown = joined.split(/\r?\n/).filter((ln) => {
    const t = ln.trim();
    if (!t.startsWith("|") || !t.endsWith("|")) return false;
    const cells = splitMdRow(ln);
    if (cells.every((c) => /^:?-{1,}:?$/.test(c) || c === "")) return false;
    return /^\d+$/.test(cells[0] ?? "");
  }).length;
  if (shown < 1) return joined;
  return joined.replace(
    /\bmost recent\s+\d+\b|\b(?:latest|last|recent)\s+\d+\b|\b\d+\s+registered\b/i,
    (m) => m.replace(/\d+/, String(shown)),
  );
}

/** Keep the first Date / Project / Price column so leftover SQL cols don't explode the grid. */
export function collapseDuplicateMarkdownColumns(text: string): string {
  if (!text || !text.includes("|")) return text;
  const lines = text.split(/\r?\n/);
  const out: string[] = [];
  let keepIdx: number[] | null = null;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("|") || !trimmed.endsWith("|")) {
      keepIdx = null;
      out.push(line);
      continue;
    }
    const cells = splitMdRow(line);
    const isSep = cells.every((c) => /^:?-{1,}:?$/.test(c) || c === "");
    if (keepIdx === null && !isSep) {
      const seen = new Set<string>();
      keepIdx = [];
      cells.forEach((cell, idx) => {
        const key = cell.replace(/\s+/g, " ").trim().toLowerCase() || `col-${idx}`;
        if (seen.has(key)) return;
        seen.add(key);
        keepIdx!.push(idx);
      });
    }
    const aligned = keepIdx
      ? keepIdx.map((idx) => (idx < cells.length ? cells[idx] : ""))
      : cells;
    if (isSep) {
      out.push("|" + aligned.map(() => "---").join("|") + "|");
    } else {
      out.push("| " + aligned.join(" | ") + " |");
    }
  }
  return out.join("\n");
}

export function renderMarkdown(text: string): string {
  if (!text) return "";
  try {
    const sanitized = sanitizeIncompleteMarkdownTable(text);
    const cleaned = stripListingImageLines(stripMarkdownImages(sanitized));
    let html = marked.parse(cleaned) as string;
    html = wrapCodeBlocks(html);
    html = wrapTables(html);
    html = wrapPropqaCtas(html);
    return html;
  } catch {
    return text;
  }
}

export function extractPlainText(markdown: string): string {
  if (!markdown) return "";
  return assistantPlainTextStored(markdown)
    .replace(/#{1,6}\s/g, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/`(.+?)`/g, "$1")
    .replace(/\[(.+?)\]\(.+?\)/g, "$1")
    .replace(/^[-*+]\s/gm, "")
    .replace(/\n{2,}/g, " ")
    .trim();
}
