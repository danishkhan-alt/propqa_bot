/**
 * LeftIconRail — Figma conversation panel (220px) with a 64px collapsed rail.
 *
 * Expanded: AI mark + collapse, New Chat, Recent search + session list.
 * Collapsed: icon column (expand, New Chat, theme).
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Moon, Search, Sun, Trash2 } from "lucide-react";
import { cn, truncate } from "@/lib/utils";
import { forgetSession, forgetSessions, listSessions, type SessionSummary } from "@/api/sessionApi";
import { useAuthStore } from "@/store/authStore";

interface LeftIconRailProps {
  /** Expanded 220px panel vs 64px icon rail */
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  currentSessionId?: string | null;
  /** True while the active chat turn is streaming — falling edge triggers Recent refresh */
  isStreaming?: boolean;
  /** First user message for the active session — used to show the row before API catches up */
  sessionTitleHint?: string | null;
  onNewChat?: () => void;
  onSelectSession?: (sid: string) => void;
  /** Single-chat forget (no user_id / LTM wipe). Required for trash affordance. */
  onForgetSession?: (sid: string) => void | Promise<void>;
  /**
   * After the rail has forgotten every listed conversation — guest wipe +
   * fresh chat (or auth fresh chat only).
   */
  onForgetAll?: () => void | Promise<void>;
  className?: string;
}

const ICON_BTN =
  "flex size-6 shrink-0 items-center justify-center rounded text-[#747288] hover:bg-[#F4F6FA] focus:outline-none focus:ring-2 focus:ring-[#E8ECF3] disabled:pointer-events-none disabled:opacity-40";

const PANEL_CHROME =
  "rounded-[20px] border border-[#E8ECF3] bg-white p-5 shadow-[0px_5.9009px_35.4054px_rgba(20,20,24,0.02)]";

function toggleTheme() {
  document.documentElement.classList.toggle("dark");
  const isDark = document.documentElement.classList.contains("dark");
  try {
    localStorage.setItem("propqa_theme", isDark ? "dark" : "light");
  } catch {
    /* ignore */
  }
}

export function LeftIconRail({
  expanded = false,
  onExpandedChange,
  currentSessionId = null,
  isStreaming = false,
  sessionTitleHint = null,
  onNewChat,
  onSelectSession,
  onForgetSession,
  onForgetAll,
  className,
}: LeftIconRailProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [query, setQuery] = useState("");
  const { userId } = useAuthStore();
  const wasStreamingRef = useRef(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSessions({ userId, limit: 50 });
      setSessions(data);
    } catch {
      /* listSessions already logs */
    } finally {
      setLoading(false);
    }
  }, [userId]);

  // Load when the panel opens or the active session id changes (New Chat / load).
  useEffect(() => {
    if (expanded) void refresh();
  }, [expanded, refresh, currentSessionId]);

  // After a turn finishes, surface the new conversation in Recent without a reload.
  // Optimistic row first (API persistence can lag the done frame), then re-fetch.
  useEffect(() => {
    const finishedTurn = wasStreamingRef.current && !isStreaming;
    wasStreamingRef.current = isStreaming;
    if (!expanded || !finishedTurn) return;

    const title = (sessionTitleHint ?? "").trim();
    if (currentSessionId && title) {
      setSessions((prev) => {
        if (prev.some((s) => s.session_id === currentSessionId)) return prev;
        const now = new Date().toISOString();
        return [
          {
            session_id: currentSessionId,
            title,
            user_turns: 1,
            created_at: now,
            last_active: now,
          },
          ...prev,
        ];
      });
    }

    const timer = window.setTimeout(() => {
      void refresh();
    }, 500);
    return () => window.clearTimeout(timer);
  }, [expanded, isStreaming, currentSessionId, sessionTitleHint, refresh]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) => (s.title ?? "").toLowerCase().includes(q));
  }, [sessions, query]);

  async function handleForget(e: React.MouseEvent, sid: string) {
    e.stopPropagation();
    if (!onForgetSession) return;
    if (!confirm("Delete this conversation? This cannot be undone.")) return;
    // Forget without user_id — parent/API must not cascade LTM for one chat.
    await forgetSession(sid);
    setSessions((prev) => prev.filter((s) => s.session_id !== sid));
    await onForgetSession(sid);
  }

  async function handleClearAll() {
    if (!onForgetAll || sessions.length === 0 || clearing) return;
    if (!confirm("Delete all conversations? This cannot be undone.")) return;
    setClearing(true);
    try {
      const ids = sessions.map((s) => s.session_id);
      await forgetSessions(ids);
      setSessions([]);
      setQuery("");
      await onForgetAll();
    } finally {
      setClearing(false);
    }
  }

  function handleToggleExpanded() {
    onExpandedChange?.(!expanded);
  }

  if (!expanded) {
    return (
      <aside
        className={cn(
          "flex h-full w-16 shrink-0 flex-col items-center gap-6 self-stretch",
          PANEL_CHROME,
          className,
        )}
        aria-label="Quick actions"
      >
        <AiFillIcon className="size-6" />
        <button
          type="button"
          onClick={handleToggleExpanded}
          disabled={!onExpandedChange}
          className={ICON_BTN}
          aria-label="Toggle sidebar"
          aria-expanded={false}
          title={onExpandedChange ? "Expand conversations" : undefined}
        >
          <SidebarLeftIcon className="size-4" />
        </button>
        <div className="flex flex-col items-start gap-[18px]">
          <button
            type="button"
            onClick={onNewChat}
            disabled={!onNewChat}
            className={ICON_BTN}
            aria-label="New Chat"
            title={onNewChat ? "Start a new conversation" : undefined}
          >
            <LayerAddIcon className="size-4" />
          </button>
          <button
            type="button"
            onClick={toggleTheme}
            className={ICON_BTN}
            aria-label="Toggle theme"
          >
            <Sun className="size-4 dark:hidden" strokeWidth={1.5} />
            <Moon className="hidden size-4 dark:block" strokeWidth={1.5} />
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside
      className={cn(
        "flex h-full w-[220px] shrink-0 flex-col items-start gap-6 self-stretch",
        PANEL_CHROME,
        className,
      )}
      aria-label="Conversations"
    >
      <div className="flex h-6 w-full items-center justify-between gap-3.5">
        <AiFillIcon className="size-6" />
        <button
          type="button"
          onClick={handleToggleExpanded}
          className={ICON_BTN}
          aria-label="Toggle sidebar"
          aria-expanded
          title="Collapse conversations"
        >
          <SidebarLeftIcon className="size-4" />
        </button>
      </div>

      <div className="flex min-h-0 w-full flex-1 flex-col items-stretch gap-[18px]">
        <button
          type="button"
          onClick={onNewChat}
          disabled={!onNewChat}
          className={cn(
            "flex h-10 w-full items-center justify-center gap-2.5 rounded-full border border-[#D8DDE6] px-5",
            "text-sm font-medium leading-[1.5] text-[#494A58]",
            "hover:bg-[#F4F6FA] focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]",
            "disabled:pointer-events-none disabled:opacity-40",
          )}
          aria-label="New Chat"
        >
          <LayerAddIcon className="size-4" />
          New Chat
        </button>

        <div className="flex min-h-0 flex-1 flex-col items-stretch gap-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-medium leading-[1.5] text-[#747288]">Recent</p>
            {onForgetAll && (
              <button
                type="button"
                onClick={() => void handleClearAll()}
                disabled={sessions.length === 0 || clearing}
                className={cn(
                  "text-xs font-medium leading-[1.5] text-[#747288]",
                  "hover:text-[#EB526D] focus:outline-none focus:underline",
                  "disabled:pointer-events-none disabled:opacity-40",
                )}
                aria-label="Clear all conversations"
              >
                Clear all
              </button>
            )}
          </div>

          <div className="flex min-h-0 flex-1 flex-col items-stretch gap-1">
            <label className="flex h-10 w-full items-center gap-2 rounded-full border border-[#D8DDE6] px-4">
              <Search className="size-3.5 shrink-0 text-[#747288]" strokeWidth={1.2} aria-hidden />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search"
                className="min-w-0 flex-1 bg-transparent text-xs font-medium leading-[1.5] text-[#141B34] placeholder:text-[#747288] focus:outline-none"
                aria-label="Search conversations"
              />
            </label>

            <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
              {loading && sessions.length === 0 && (
                <p className="px-4 py-2.5 text-xs font-medium text-[#747288]">Loading…</p>
              )}
              {!loading && sessions.length === 0 && (
                <p className="px-4 py-2.5 text-xs font-medium leading-[1.5] tracking-[-0.01em] text-[#747288]">
                  No conversations yet.
                </p>
              )}
              {!loading && sessions.length > 0 && filtered.length === 0 && (
                <p className="px-4 py-2.5 text-xs font-medium text-[#747288]">No matches.</p>
              )}
              {filtered.map((session) => {
                const isActive = session.session_id === currentSessionId;
                // Active chat: prefer live first-user hint so follow-ups never
                // retitle the row while the API is catching up.
                const label =
                  isActive && (sessionTitleHint ?? "").trim()
                    ? sessionTitleHint!.trim()
                    : session.title;
                return (
                  <div
                    key={session.session_id}
                    className={cn(
                      "group flex h-[38px] w-full items-center gap-3 rounded-xl px-4",
                      isActive ? "bg-[#EDF0F5]" : "hover:bg-[#F4F6FA]",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => onSelectSession?.(session.session_id)}
                      className={cn(
                        "min-w-0 flex-1 truncate text-left text-xs font-medium leading-[1.5] tracking-[-0.01em]",
                        isActive ? "text-[#141B34]" : "text-[#747288]",
                      )}
                      title={label}
                    >
                      {truncate(label, 48)}
                    </button>
                    {onForgetSession && (
                      <button
                        type="button"
                        onClick={(e) => void handleForget(e, session.session_id)}
                        className="shrink-0 rounded p-0.5 text-[#747288] hover:text-[#EB526D] focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]"
                        aria-label={`Delete ${label || "conversation"}`}
                        title="Delete"
                      >
                        <Trash2 className="size-3" strokeWidth={1.5} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
function AiFillIcon({ className }: { className?: string }) {
  const rawId = useId();
  const gid = `ai-fill-${rawId.replace(/:/g, "")}`;
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden>
      <defs>
        <linearGradient id={gid} x1="3" y1="22" x2="21" y2="2" gradientUnits="userSpaceOnUse">
          <stop stopColor="#EB526D" />
          <stop offset="1" stopColor="#9885F0" />
        </linearGradient>
      </defs>
      <path
        fill={`url(#${gid})`}
        d="M12.9 2.35c-.28-.7-1.52-.7-1.8 0L9.4 7.4c-.1.25-.3.45-.55.55L3.9 9.6c-.7.28-.7 1.52 0 1.8l4.95 1.65c.25.1.45.3.55.55l1.7 5.05c.28.7 1.52.7 1.8 0l1.7-5.05c.1-.25.3-.45.55-.55L19.1 11.4c.7-.28.7-1.52 0-1.8l-4.95-1.65a1.1 1.1 0 0 1-.55-.55L12.9 2.35Z"
      />
      <path
        fill={`url(#${gid})`}
        d="M18.6 16.2c-.14-.36-.76-.36-.9 0l-.55 1.4a.4.4 0 0 1-.2.2l-1.4.55c-.36.14-.36.76 0 .9l1.4.55c.09.04.16.11.2.2l.55 1.4c.14.36.76.36.9 0l.55-1.4a.4.4 0 0 1 .2-.2l1.4-.55c.36-.14.36-.76 0-.9l-1.4-.55a.4.4 0 0 1-.2-.2l-.55-1.4Z"
      />
    </svg>
  );
}

/** Figma sidebar-left (panel with left rail). */
function SidebarLeftIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="1.5" y="2" width="13" height="12" rx="2.5" stroke="#747288" strokeWidth="1.2" />
      <path d="M6.25 2.5v11" stroke="#747288" strokeWidth="1.2" />
      <path d="M3.5 11h1.5M3.5 8.5h1.5" stroke="#747288" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M10 8h1.5" stroke="#747288" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

/** Figma layer-add (stacked tiles + plus). */
function LayerAddIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="1.5" y="1.5" width="8.5" height="8.5" rx="1.5" stroke="#494A58" strokeWidth="1.2" />
      <rect x="6" y="6" width="8.5" height="8.5" rx="1.5" stroke="#494A58" strokeWidth="1.2" />
      <path d="M10.25 8.75v5M7.75 11.25h5" stroke="#494A58" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

