/**
 * SSE / WS focused_property_ids body wiring.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/store/authStore", () => ({
  withAuthHeaders: () => ({}),
}));

describe("sendSSE focused_property_ids", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("includes focused_property_ids in the request body", async () => {
    const bodies: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        bodies.push(JSON.parse(String(init?.body ?? "{}")));
        return {
          body: {
            getReader: () => ({
              read: async () => ({ done: true, value: undefined }),
            }),
          },
        } as unknown as Response;
      }),
    );

    const { sendSSE } = await import("@/api/sseClient");
    await sendSSE({
      prompt: "what is the price?",
      sessionId: "s1",
      userId: null,
      focusedPropertyIds: [42, 7],
      onFrame: () => {},
    });

    expect(bodies[0]?.focused_property_ids).toEqual([42, 7]);
    expect(bodies[0]?.message).toBe("what is the price?");
  });

  it("sends empty focused_property_ids when none attached", async () => {
    const bodies: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        bodies.push(JSON.parse(String(init?.body ?? "{}")));
        return {
          body: {
            getReader: () => ({
              read: async () => ({ done: true, value: undefined }),
            }),
          },
        } as unknown as Response;
      }),
    );

    const { sendSSE } = await import("@/api/sseClient");
    await sendSSE({
      prompt: "villas in marina",
      sessionId: "s1",
      userId: null,
      focusedPropertyIds: [],
      onFrame: () => {},
    });

    expect(bodies[0]?.focused_property_ids).toEqual([]);
  });
});
