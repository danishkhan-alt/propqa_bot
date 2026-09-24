import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface SessionProfile {
  family_size?: number | null;
  purpose?: string | null;
  budget_range?: string | null;
  timeline?: string | null;
}

const LABELS: Record<string, string> = {
  live: "Live in it",
  invest: "Invest",
  both: "Both",
  under_1m: "Under 1M",
  "1m_2m": "1M–2M",
  "2m_4m": "2M–4M",
  "4m_plus": "4M+",
  ready: "Ready to move",
  off_plan: "Off-plan",
};

interface SessionProfileState {
  profile: SessionProfile;
  merge: (patch: Record<string, unknown>) => void;
  clear: () => void;
}

export const useSessionProfileStore = create<SessionProfileState>()(
  persist(
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
    { name: "propqa:session-profile" },
  ),
);

export function profileChips(profile: SessionProfile): { key: string; label: string }[] {
  const chips: { key: string; label: string }[] = [];
  if (profile.family_size) chips.push({ key: "family_size", label: `Family of ${profile.family_size}` });
  if (profile.purpose) chips.push({ key: "purpose", label: LABELS[profile.purpose] || profile.purpose });
  if (profile.budget_range) chips.push({ key: "budget_range", label: LABELS[profile.budget_range] || profile.budget_range });
  if (profile.timeline) chips.push({ key: "timeline", label: LABELS[profile.timeline] || profile.timeline });
  return chips;
}

export function continuationFromProfile(profile: SessionProfile): string {
  const bits = profileChips(profile).map((chip) => chip.label);
  if (!bits.length) return "Compare these areas with what you already know about me.";
  return `Compare these areas using this: ${bits.join(", ")}.`;
}
