import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("@/store/authStore", () => ({
  withAuthHeaders: () => ({}),
}));

import { deletePreferences } from "@/api/preferencesApi";

describe("preferencesApi.deletePreferences", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns false without calling fetch when userId is empty", async () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const result = await deletePreferences({ userId: "" });

    expect(result).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("issues a DELETE request with the user_id query param", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock as unknown as typeof fetch;

    const result = await deletePreferences({ userId: "user-123" });

    expect(result).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/preferences?user_id=user-123",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("includes session_id in the query string when provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock as unknown as typeof fetch;

    const result = await deletePreferences({ userId: "user-123", sessionId: "sess-abc" });

    expect(result).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/preferences?user_id=user-123&session_id=sess-abc",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("omits session_id from the query string when not provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock as unknown as typeof fetch;

    await deletePreferences({ userId: "user-123", sessionId: null });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/preferences?user_id=user-123",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("returns false when the server responds with a non-ok status", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    global.fetch = fetchMock as unknown as typeof fetch;

    const result = await deletePreferences({ userId: "user-123" });

    expect(result).toBe(false);
  });

  it("returns false and swallows network errors", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("network down"));
    global.fetch = fetchMock as unknown as typeof fetch;

    const result = await deletePreferences({ userId: "user-123" });

    expect(result).toBe(false);
  });
});
