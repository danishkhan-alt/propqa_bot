import { describe, expect, it } from "vitest";
import {
  emptySearchClearIndex,
  filterMessagesForCardGroups,
} from "@/lib/cardGroups";

describe("filterMessagesForCardGroups", () => {
  it("keeps prior card groups when latest assistant has cards", () => {
    const messages = [
      { id: "u1", role: "user", content: "marina apartments" },
      {
        id: "a1",
        role: "assistant",
        content: "Here are 3 matches",
        cards: [{ id: 1 }],
      },
      { id: "u2", role: "user", content: "show more" },
      {
        id: "a2",
        role: "assistant",
        content: "Here are more",
        cards: [{ id: 2 }],
      },
    ];
    const kept = filterMessagesForCardGroups(messages);
    expect(kept.map((m) => m.id)).toEqual(["a1", "a2"]);
  });

  it("keeps prior card groups on empty property-search answer", () => {
    const messages = [
      { id: "u1", role: "user", content: "marina apartments" },
      {
        id: "a1",
        role: "assistant",
        content: "Here are 3 matches",
        cards: [{ id: 1 }],
      },
      { id: "u2", role: "user", content: "sea view under 1m in jlt" },
      {
        id: "a2",
        role: "assistant",
        content: "I found **0 exact matches** for your filters.",
        cards: undefined,
      },
    ];
    expect(emptySearchClearIndex(messages)).toBe(-1);
    const kept = filterMessagesForCardGroups(messages);
    expect(kept.map((m) => m.id)).toEqual(["a1"]);
  });

  it("keeps prior cards while an empty answer is still streaming", () => {
    const messages = [
      {
        id: "a1",
        role: "assistant",
        content: "cards",
        cards: [{ id: 1 }],
      },
      {
        id: "a2",
        role: "assistant",
        content: "I found **0 exact matches**",
        isStreaming: true,
      },
    ];
    expect(emptySearchClearIndex(messages)).toBe(-1);
    expect(filterMessagesForCardGroups(messages).map((m) => m.id)).toEqual([
      "a1",
    ]);
  });
});
