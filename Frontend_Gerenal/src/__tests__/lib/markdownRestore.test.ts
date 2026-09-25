import { describe, expect, it } from "vitest";
import {
  collapseDuplicateMarkdownColumns,
  isYieldPublicStub,
  isYieldWorksheetOnly,
  pickRestoredAssistantText,
  sanitizeIncompleteMarkdownTable,
} from "@/lib/markdown";

describe("pickRestoredAssistantText", () => {
  it("keeps the streamed yield narrative over a worksheet-only stub", () => {
    const narrative =
      "Gross Rental Yield in Business Bay\n\nPer DLD/Ejari transactions (last 12 months): **20.83%**.";
    const worksheet =
      "## How this number was calculated\n\nGross yield = yearly Ejari rent ÷ DLD sale price.";
    expect(isYieldWorksheetOnly(worksheet)).toBe(true);
    expect(isYieldWorksheetOnly(narrative)).toBe(false);
    expect(pickRestoredAssistantText(worksheet, narrative)).toBe(narrative);
    expect(pickRestoredAssistantText(narrative, worksheet)).toBe(narrative);
  });

  it("falls back to envelope.answer_md when the transcript is empty", () => {
    expect(pickRestoredAssistantText("", "Around 6% in JVC.")).toBe(
      "Around 6% in JVC.",
    );
  });

  it("keeps a long narrative over a public yield stub", () => {
    const narrative =
      "For an AED 2 million apartment budget, focus on established communities with liquid resale, not just the raw yield ranking.";
    const stub =
      "**Dubai Investment Park First** — Uncapped **71.24%** · Median **10.26%**";
    expect(isYieldPublicStub(stub)).toBe(true);
    expect(isYieldPublicStub(narrative)).toBe(false);
    expect(pickRestoredAssistantText(stub, narrative)).toBe(narrative);
    expect(pickRestoredAssistantText(narrative, stub)).toBe(narrative);
  });
});

describe("sanitizeIncompleteMarkdownTable", () => {
  it("drops a cut-off last row and the id-redacted column", () => {
    const raw = [
      "| # | [id redacted] | Date | Project |",
      "|---|---|---|---|",
      "| 1 | 1-1-2026-1 | 31 Aug 2026 | Jumeirah Gate |",
      "| 40 | 1-11-2026-26773 | 31 Aug 2026 | Grand Bleu Tower interiors by",
    ].join("\n");
    const out = sanitizeIncompleteMarkdownTable(raw);
    expect(out).toContain("| 1 | 31 Aug 2026 | Jumeirah Gate |");
    expect(out).not.toContain("[id redacted]");
    expect(out).not.toContain("interiors by");
    expect(out.trim().endsWith("|")).toBe(true);
  });

  it("rewrites a promised row count to the rows actually shown", () => {
    const raw = [
      "Here are the most recent 50 registered DLD sale transactions:",
      "",
      "| # | [id redacted] | Date | Project |",
      "|---|---|---|---|",
      "| 1 | x | 31 Aug 2026 | Jumeirah Gate |",
      "| 2 | y | 31 Aug 2026 | Grand Bleu Tower interiors by",
    ].join("\n");
    const out = sanitizeIncompleteMarkdownTable(raw);
    expect(out).toMatch(/most recent 1/i);
    expect(out).not.toMatch(/most recent 50/i);
  });
});

describe("collapseDuplicateMarkdownColumns", () => {
  it("keeps the first of each repeated header from a wide SQL dump", () => {
    const raw = [
      "| # | Project | Date | Date | Project | Project | Property Type | Project | Price (AED) | Price (AED) |",
      "|---|---|---|---|---|---|---|---|---|---|",
      "| 1 | Burj Vista | 1 Sep 2026 | 1 Oct 2026 | Area A | Area B | Flat | Extra | 80,000 | 90,000 |",
    ].join("\n");
    const out = collapseDuplicateMarkdownColumns(raw);
    const header = out.split("\n")[0];
    expect(header).toBe("| # | Project | Date | Property Type | Price (AED) |");
    expect(out).toContain("| 1 | Burj Vista | 1 Sep 2026 | Flat | 80,000 |");
    expect((header.match(/Project/g) || []).length).toBe(1);
    expect((header.match(/Date/g) || []).length).toBe(1);
    expect((header.match(/Price/g) || []).length).toBe(1);
  });
});
