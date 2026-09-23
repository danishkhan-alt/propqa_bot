import { describe, it, expect, beforeEach } from "vitest";
import { usePrefsStore, selectOutgoingBuyerPreferences } from "@/store/prefsStore";

describe("prefsStore", () => {
  beforeEach(() => {
    localStorage.clear();
    usePrefsStore.setState(
      {
        buyerPreferences: null,
        savedSearches: [],
        personalizationEnabled: false,
        hasPreferences: false,
      },
      false
    );
  });

  it("setPreferences() sets hasPreferences and personalizationEnabled", () => {
    usePrefsStore.getState().setPreferences({ area: "Downtown Dubai", purpose: "buy" });
    const state = usePrefsStore.getState();
    expect(state.hasPreferences).toBe(true);
    expect(state.personalizationEnabled).toBe(true);
    expect(state.buyerPreferences).toEqual({ area: "Downtown Dubai", purpose: "buy" });
  });

  describe("selectOutgoingBuyerPreferences", () => {
    it("returns null when no preferences have been set", () => {
      expect(selectOutgoingBuyerPreferences(usePrefsStore.getState())).toBeNull();
    });

    it("returns the preferences once set, regardless of personalizationEnabled", () => {
      usePrefsStore.getState().setPreferences({ area: "Downtown Dubai" });
      expect(selectOutgoingBuyerPreferences(usePrefsStore.getState())).toEqual({
        area: "Downtown Dubai",
      });

      // Regression: closing the "For You" panel (or toggling Sparkles off)
      // must NOT stop preferences from being sent to chat — this is the
      // exact bug where preferences appeared to "not carry" into new
      // chats / after a server restart until the user re-saved them.
      usePrefsStore.getState().setPersonalizationEnabled(false);
      expect(usePrefsStore.getState().personalizationEnabled).toBe(false);
      expect(selectOutgoingBuyerPreferences(usePrefsStore.getState())).toEqual({
        area: "Downtown Dubai",
      });
    });

    it("returns null again after clearPreferences()", () => {
      usePrefsStore.getState().setPreferences({ area: "Downtown Dubai" });
      usePrefsStore.getState().clearPreferences();
      expect(selectOutgoingBuyerPreferences(usePrefsStore.getState())).toBeNull();
    });
  });
});
