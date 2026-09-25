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

// Chats whose profile is kept; the oldest is dropped beyond this.
const MAX_KEPT_SESSIONS = 50;

interface SessionProfileState {
  /** The chat the profile below belongs to. */
  sessionId: string | null;
  profile: SessionProfile;
  bySession: Record<string, SessionProfile>;
  /** Switch to a chat's own profile. A new chat starts empty. */
  activate: (sessionId: string | null) => void;
  merge: (patch: Record<string, unknown>) => void;
  clear: () => void;
}

type PersistedProfile = Pick<SessionProfileState, "sessionId" | "profile" | "bySession">;

function keep(bySession: Record<string, SessionProfile>, sessionId: string | null, profile: SessionProfile) {
  if (!sessionId) return bySession;
  const { [sessionId]: _previous, ...rest } = bySession;
  const next = Object.keys(profile).length ? { ...rest, [sessionId]: profile } : rest;
  const ids = Object.keys(next);
  for (const id of ids.slice(0, Math.max(0, ids.length - MAX_KEPT_SESSIONS))) delete next[id];
  return next;
}

export const useSessionProfileStore = create<SessionProfileState>()(
  persist<SessionProfileState, [], [], PersistedProfile>(
    (set) => ({
      sessionId: null,
      profile: {},
      bySession: {},
      activate: (sessionId) =>
        set((state) =>
          state.sessionId === sessionId
            ? state
            : { sessionId, profile: (sessionId && state.bySession[sessionId]) || {} },
        ),
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
          return { profile: next, bySession: keep(state.bySession, state.sessionId, next) };
        }),
      clear: () => set((state) => ({ profile: {}, bySession: keep(state.bySession, state.sessionId, {}) })),
    }),
    {
      name: "propqa:session-profile",
      version: 2,
      partialize: (state) => ({ sessionId: state.sessionId, profile: state.profile, bySession: state.bySession }),
      // v0 and v1 kept one profile for every chat, so it leaked into new ones. It is not
      // known which chat it came from, so it is dropped rather than guessed.
      migrate: () => ({ sessionId: null, profile: {}, bySession: {} }),
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
