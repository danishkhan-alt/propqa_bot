/**
 * prefsStore.ts — Buyer Preferences + Saved Searches Zustand store.  🔮
 *
 * Persisted to localStorage under the key "propqa:prefs" so preferences
 * survive page refreshes and carry over to new sessions.
 *
 * Usage:
 *   const { buyerPreferences, setPreferences, personalizationEnabled } = usePrefsStore();
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

// ── Types ────────────────────────────────────────────────────────────────────

export interface BuyerPreferences {
  area?: string;
  bedrooms?: number | null;
  propertyType?: string;
  purpose?: "buy" | "rent" | null;
  priceMin?: number | null;
  priceMax?: number | null;
  amenities?: string[];
  language?: string;
}

export interface SavedSearch {
  searchId: string;
  label: string;
  query: string;
  filterSpec?: Record<string, unknown>;
  savedAt: string;
}

export interface PrefsState {
  /** The buyer's stated preferences (null = not yet set). */
  buyerPreferences: BuyerPreferences | null;

  /** User-created saved searches (max 50). */
  savedSearches: SavedSearch[];

  /** When true the RecommendationPanel is shown and searches are personalised. */
  personalizationEnabled: boolean;

  /** Whether preferences have been explicitly set (not just defaults). */
  hasPreferences: boolean;

  // ── Actions ──────────────────────────────────────────────────────────────

  /** Set or merge buyer preferences. */
  setPreferences: (prefs: Partial<BuyerPreferences>) => void;

  /** Replace all preferences at once. */
  replacePreferences: (prefs: BuyerPreferences) => void;

  /** Add a saved search (capped at 50). */
  addSavedSearch: (search: Omit<SavedSearch, "savedAt">) => void;

  /** Remove a saved search by ID. */
  removeSavedSearch: (searchId: string) => void;

  /** Enable or disable personalisation. */
  setPersonalizationEnabled: (enabled: boolean) => void;

  /** Clear all preferences (GDPR-style reset). */
  clearPreferences: () => void;

  /** Clear saved searches. */
  clearSavedSearches: () => void;
}

// ── Store ────────────────────────────────────────────────────────────────────

export const usePrefsStore = create<PrefsState>()(
  persist(
    (set, get) => ({
      buyerPreferences: null,
      savedSearches: [],
      personalizationEnabled: false,
      hasPreferences: false,

      setPreferences: (prefs) =>
        set((state) => ({
          buyerPreferences: { ...state.buyerPreferences, ...prefs },
          hasPreferences: true,
          personalizationEnabled: true,
        })),

      replacePreferences: (prefs) =>
        set({
          buyerPreferences: prefs,
          hasPreferences: true,
          personalizationEnabled: true,
        }),

      addSavedSearch: (search) =>
        set((state) => {
          const existing = state.savedSearches.filter(
            (s) => s.searchId !== search.searchId
          );
          const updated: SavedSearch[] = [
            { ...search, savedAt: new Date().toISOString() },
            ...existing,
          ].slice(0, 50);
          return { savedSearches: updated };
        }),

      removeSavedSearch: (searchId) =>
        set((state) => ({
          savedSearches: state.savedSearches.filter(
            (s) => s.searchId !== searchId
          ),
        })),

      setPersonalizationEnabled: (enabled) =>
        set({ personalizationEnabled: enabled }),

      clearPreferences: () =>
        set({
          buyerPreferences: null,
          hasPreferences: false,
          personalizationEnabled: false,
        }),

      clearSavedSearches: () => set({ savedSearches: [] }),
    }),
    {
      name: "propqa:prefs",
      partialize: (state) => ({
        buyerPreferences: state.buyerPreferences,
        savedSearches: state.savedSearches,
        personalizationEnabled: state.personalizationEnabled,
        hasPreferences: state.hasPreferences,
      }),
    }
  )
);

// ── Selectors (memoised) ─────────────────────────────────────────────────────

/** Returns true if the user has a saved area preference. */
export const selectHasAreaPreference = (state: PrefsState): boolean =>
  Boolean(state.buyerPreferences?.area);

/**
 * The preferences to attach to an outgoing chat request, or `null` when
 * none should be sent.
 *
 * Deliberately independent of `personalizationEnabled` — that flag only
 * controls whether the "For You" panel is shown. Gating the send on it
 * caused preferences to silently stop reaching the chat pipeline whenever
 * the panel was closed or the Sparkles toggle was switched off, and the
 * flag (being persisted to localStorage) then stayed stuck off across new
 * chats and server restarts until the user re-saved their preferences.
 */
export const selectOutgoingBuyerPreferences = (
  state: PrefsState
): BuyerPreferences | null => (state.hasPreferences ? state.buyerPreferences : null);

/** Returns the active search count. */
export const selectSavedSearchCount = (state: PrefsState): number =>
  state.savedSearches.length;
