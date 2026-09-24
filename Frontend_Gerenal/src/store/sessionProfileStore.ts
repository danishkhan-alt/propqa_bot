import { create } from "zustand";
import { persist } from "zustand/middleware";

/** Buyer facts the backend keeps per chat. Values mirror the backend's closed sets. */
export interface SessionProfile {
  family_size?: number | null;
  goal?: string | null;
  budget_range?: string | null;
  timeline?: string | null;
}

const LABELS: Record<string, string> = {
  live: "Home to live in",
  invest: "Investment",
  both: "Live + invest",
  under_1m: "Under AED 1M",
  "1m_2m": "AED 1M–2M",
  "2m_4m": "AED 2M–4M",
  "4m_plus": "AED 4M+",
  ready: "Ready to move",
  off_plan: "Open to off-plan",
};

interface SessionProfileState {
  profile: SessionProfile;
  merge: (patch: Record<string, unknown>) => void;
  clear: () => void;
}

type PersistedProfile = Pick<SessionProfileState, "profile">;

export const useSessionProfileStore = create<SessionProfileState>()(
  persist<SessionProfileState, [], [], PersistedProfile>(
    (set) => ({
      profile: {},
      merge: (patch) =>
        set((state) => {
          const next: SessionProfile = { ...state.profile };
          for (const [key, value] of Object.entries(patch)) {
            if (value === null || value === undefined || value === "") {
              delete next[key as keyof SessionProfile];
            } else {
              (next as Record<string, unknown>)[key] = value;
            }
          }
          return { profile: next };
        }),
      clear: () => set({ profile: {} }),
    }),
    {
      name: "propqa:session-profile",
      version: 1,
      partialize: (state) => ({ profile: state.profile }),
      // v0 stored the live/invest answer as `purpose`.
      migrate: (persisted) => {
        const stored = ((persisted ?? {}) as { profile?: SessionProfile & { purpose?: string } }).profile ?? {};
        const { purpose, ...rest } = stored;
        return { profile: purpose ? { ...rest, goal: purpose } : rest };
      },
    },
  ),
);

export function profileChips(profile: SessionProfile): { key: string; label: string }[] {
  const chips: { key: string; label: string }[] = [];
  if (profile.family_size) chips.push({ key: "family_size", label: `Family of ${profile.family_size}` });
  if (profile.goal) chips.push({ key: "goal", label: LABELS[profile.goal] || profile.goal });
  if (profile.budget_range) chips.push({ key: "budget_range", label: LABELS[profile.budget_range] || profile.budget_range });
  if (profile.timeline) chips.push({ key: "timeline", label: LABELS[profile.timeline] || profile.timeline });
  return chips;
}
