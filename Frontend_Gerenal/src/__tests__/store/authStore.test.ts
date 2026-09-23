import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useAuthStore } from "@/store/authStore";

// Mock fetch globally
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

describe("authStore", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch.mockReset();
    // Reset store state
    useAuthStore.setState({
      user: null,
      accessToken: null,
      isAuthenticated: false,
      isGuest: true,
      isLoading: false,
      error: null,
      userId: "anon-test-uuid",
    });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("starts in guest mode with an anon userId", () => {
    const state = useAuthStore.getState();
    expect(state.isGuest).toBe(true);
    expect(state.isAuthenticated).toBe(false);
    expect(state.user).toBeNull();
  });

  it("login() updates state on success", async () => {
    const mockUser = { id: "user-123", email: "demo@propqa.ai", name: "Demo", role: "user", phone: null };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ user: mockUser, access_token: "tok1", refresh_token: "ref1" }),
    } as Response);

    await useAuthStore.getState().login("demo@propqa.ai", "Demo1234!");

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.isGuest).toBe(false);
    expect(state.user?.email).toBe("demo@propqa.ai");
    expect(state.accessToken).toBe("tok1");
  });

  it("login() sets error on failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: "Invalid email or password." }),
    } as Response);

    await expect(useAuthStore.getState().login("bad@example.com", "wrong")).rejects.toThrow();
    expect(useAuthStore.getState().error).toBe("Invalid email or password.");
  });

  it("logout() clears auth state", async () => {
    // Set authenticated state
    useAuthStore.setState({
      user: { id: "u1", email: "u@e.com", name: "U", role: "user" },
      accessToken: "tok",
      isAuthenticated: true,
      isGuest: false,
    });
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) } as Response);

    await useAuthStore.getState().logout();

    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.isAuthenticated).toBe(false);
    expect(state.isGuest).toBe(true);
    expect(state.accessToken).toBeNull();
  });

  it("continueAsGuest() sets guest mode", () => {
    useAuthStore.setState({ isLoading: true });
    useAuthStore.getState().continueAsGuest();
    expect(useAuthStore.getState().isGuest).toBe(true);
    expect(useAuthStore.getState().isLoading).toBe(false);
  });

  it("clearError() clears the error", () => {
    useAuthStore.setState({ error: "Some error" });
    useAuthStore.getState().clearError();
    expect(useAuthStore.getState().error).toBeNull();
  });

  it("refreshTokens() returns false when no stored token", async () => {
    localStorage.removeItem("propqa_refresh_token");
    const result = await useAuthStore.getState().refreshTokens();
    expect(result).toBe(false);
  });

  it("withAuthHeaders returns Authorization header when authenticated", () => {
    useAuthStore.setState({ accessToken: "mytoken" });
    const { withAuthHeaders } = require("@/store/authStore");
    const headers = withAuthHeaders();
    expect(headers.Authorization).toBe("Bearer mytoken");
  });

  it("withAuthHeaders returns empty object when guest", () => {
    useAuthStore.setState({ accessToken: null });
    const { withAuthHeaders } = require("@/store/authStore");
    const headers = withAuthHeaders();
    expect(headers.Authorization).toBeUndefined();
  });
});
