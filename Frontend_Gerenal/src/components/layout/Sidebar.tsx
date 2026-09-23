/**
 * Sidebar — session history panel with new chat and session list.
 */

import { useState, useEffect, useCallback } from "react";
import { Plus, MessageSquare, Trash2, ChevronRight, Brain } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { formatRelativeTime, truncate } from "@/lib/utils";
import { listSessions, forgetSession, type SessionSummary } from "@/api/sessionApi";
import { useAuthStore } from "@/store/authStore";

interface SidebarProps {
  isOpen: boolean;
  currentSessionId: string | null;
  onNewChat: () => void;
  onSelectSession: (sid: string) => void;
  onForgetSession: (sid: string) => void;
  onToggleMemoryPanel?: () => void;
  onClose?: () => void;
  className?: string;
}

export function Sidebar({
  isOpen,
  currentSessionId,
  onNewChat,
  onSelectSession,
  onForgetSession,
  onToggleMemoryPanel,
  onClose,
  className,
}: SidebarProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const { userId } = useAuthStore();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSessions({ userId, limit: 50 });
      setSessions(data);
    } catch {
      // Ignore
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    if (isOpen) refresh();
  }, [isOpen, refresh, currentSessionId]);

  async function handleForget(e: React.MouseEvent, sid: string) {
    e.stopPropagation();
    if (!confirm("Delete this conversation? This cannot be undone.")) return;
    await forgetSession(sid, { userId });
    setSessions((prev) => prev.filter((s) => s.session_id !== sid));
    if (sid === currentSessionId) onForgetSession(sid);
  }

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="sidebar-overlay md:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={cn(
          "flex h-full w-64 min-h-0 shrink-0 flex-col overflow-hidden border-r bg-sidebar transition-all duration-200",
          !isOpen && "-ml-64",
          isOpen && "ml-0",
          "absolute left-0 top-0 z-50 md:relative md:z-auto",
          className,
        )}
      >
        {/* Header */}
        <div className="flex h-12 shrink-0 items-center justify-between border-b px-3">
          <span className="truncate text-sm font-semibold text-sidebar-foreground">Conversations</span>
          <Button size="sm" variant="outline" className="h-7 shrink-0 gap-1 text-xs" onClick={onNewChat}>
            <Plus className="size-3.5" /> New
          </Button>
        </div>

        {/* Session list */}
        <ScrollArea className="min-h-0 flex-1">
          <div className="flex w-full min-w-0 flex-col gap-0.5 px-3 py-2">
            {loading && sessions.length === 0 && (
              <div className="py-8 text-center text-xs text-muted-foreground">Loading…</div>
            )}
            {!loading && sessions.length === 0 && (
              <div className="py-8 text-center text-xs text-muted-foreground">
                No conversations yet.
                <br />Start a new chat to begin.
              </div>
            )}
            {sessions.map((session) => (
              <SessionItem
                key={session.session_id}
                session={session}
                isActive={session.session_id === currentSessionId}
                onSelect={() => onSelectSession(session.session_id)}
                onForget={(e) => handleForget(e, session.session_id)}
              />
            ))}
          </div>
        </ScrollArea>

        {/* Footer */}
        <div className="shrink-0 border-t px-3 py-2">
          <Separator className="mb-2" />
          {onToggleMemoryPanel && (
            <button
              onClick={onToggleMemoryPanel}
              className="flex w-full min-w-0 items-center gap-2 rounded-md py-1.5 text-xs text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
            >
              <Brain className="size-4" />
              Memory & Knowledge
              <ChevronRight className="ml-auto size-3" />
            </button>
          )}
        </div>
      </aside>
    </>
  );
}

function SessionItem({
  session,
  isActive,
  onSelect,
  onForget,
}: {
  session: SessionSummary;
  isActive: boolean;
  onSelect: () => void;
  onForget: (e: React.MouseEvent) => void;
}) {
  return (
    <div
      className={cn(
        "group flex w-full min-w-0 items-start gap-2 rounded-md py-1.5 transition-colors",
        isActive
          ? "bg-sidebar-primary/10 text-sidebar-primary"
          : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        className="flex min-w-0 flex-1 items-start gap-2 text-left"
      >
        <MessageSquare className="mt-0.5 size-3.5 shrink-0 opacity-70" />
        <div className="min-w-0 flex-1 overflow-hidden">
          <p className="truncate text-xs font-medium">{truncate(session.title, 40)}</p>
          <p className="truncate text-[10px] text-muted-foreground">
            {session.user_turns} msgs · {formatRelativeTime(session.created_at ?? null)}
          </p>
        </div>
      </button>
      <button
        type="button"
        onClick={onForget}
        className="mr-1 mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground/50 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
        title="Delete"
      >
        <Trash2 className="size-3" />
      </button>
    </div>
  );
}
