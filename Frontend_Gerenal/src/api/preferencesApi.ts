/**
 * Preferences API client — mirrors buyer preferences into the Redis-backed
 * LongTermMemory profile so they survive a cleared localStorage, a new
 * device/browser, or a server restart (defense-in-depth; localStorage via
 * prefsStore remains the source of truth for the current browser).
 */

import { withAuthHeaders } from "@/store/authStore";
import type { BuyerPreferences } from "@/store/prefsStore";

export async function savePreferences({
  userId,
  preferences,
}: {
  userId: string;
  preferences: Partial<BuyerPreferences>;
}): Promise<boolean> {
  if (!userId) return false;
  try {
    const res = await fetch("/api/preferences", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...withAuthHeaders() },
      credentials: "same-origin",
      body: JSON.stringify({ user_id: userId, preferences }),
    });
    return res.ok;
  } catch (err) {
    console.warn("[preferencesApi] savePreferences failed:", err);
    return false;
  }
}

export async function getPreferences({
  userId,
}: {
  userId: string;
}): Promise<BuyerPreferences | null> {
  if (!userId) return null;
  try {
    const res = await fetch(`/api/preferences?user_id=${encodeURIComponent(userId)}`, {
      credentials: "same-origin",
      headers: withAuthHeaders(),
    });
    if (!res.ok) return null;
    const data = await res.json() as { preferences: BuyerPreferences | null };
    return data?.preferences ?? null;
  } catch (err) {
    console.warn("[preferencesApi] getPreferences failed:", err);
    return null;
  }
}

/**
 * Clear the Redis-backed copy of a user's buyer preferences.
 *
 * Must be called whenever the "My Property Preferences" panel is reset —
 * `savePreferences` merges patches server-side (so a partial save never
 * wipes unrelated keys), which means without an explicit clear the old
 * values keep resurrecting themselves via boot-time hydration on the next
 * chat turn, or a `getPreferences` fetch on a new device/browser, even
 * after the user reset the panel in this one.
 *
 * Also passes the current tab's `sessionId` (when known) so the backend can
 * flush that session's `last_filter_spec` carry-forward memory — otherwise
 * a preference-derived filter (e.g. area/type) already baked into THIS
 * conversation's short-term memory from an earlier turn would keep getting
 * replayed on the next vague message, even though the preferences panel
 * was just reset.
 */
export async function deletePreferences({
  userId,
  sessionId,
}: {
  userId: string;
  sessionId?: string | null;
}): Promise<boolean> {
  if (!userId) return false;
  try {
    const params = new URLSearchParams({ user_id: userId });
    if (sessionId) params.set("session_id", sessionId);
    const res = await fetch(`/api/preferences?${params.toString()}`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: withAuthHeaders(),
    });
    return res.ok;
  } catch (err) {
    console.warn("[preferencesApi] deletePreferences failed:", err);
    return false;
  }
}
