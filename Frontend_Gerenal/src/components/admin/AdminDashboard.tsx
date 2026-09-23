/**
 * UserDashboard.tsx — Per-user "My Dashboard".
 *
 * Shows the authenticated user's own activity, session history,
 * saved searches, and buyer preferences.
 *
 * Tabs: Overview | Session History | Saved Searches | My Preferences
 *
 * Data sources (all already available in the frontend):
 *   - listSessions()       → session list from sessionApi
 *   - useAuthStore()       → name, email, role
 *   - usePrefsStore()      → buyer preferences, saved searches
 *   - analyticsApi.getEngagement() → graceful-zero fallback metrics
 */

import React, { useEffect, useState, useCallback } from "react";
import {
  LayoutGrid,
  History,
  Bookmark,
  SlidersHorizontal,
  RefreshCw,
  MessageSquare,
  TrendingUp,
  Search,
  Home,
  MapPin,
  BedDouble,
  Banknote,
  Tag,
  Sparkles,
  ExternalLink,
  Trash2,
  PenLine,
  Clock,
  CalendarDays,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore, getAuthUserId } from "@/store/authStore";
import { usePrefsStore } from "@/store/prefsStore";
import { listSessions } from "@/api/sessionApi";
import { analyticsApi } from "@/api/analyticsApi";
import { deletePreferences } from "@/api/preferencesApi";
import { getActiveSessionId } from "@/hooks/useChat";
import { PrefsPanel } from "@/components/recommendations/PrefsPanel";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { SessionSummary } from "@/api/sessionApi";
import type { EngagementData } from "@/api/analyticsApi";

// ── Types ─────────────────────────────────────────────────────────────────────

type TabId = "overview" | "history" | "searches" | "preferences";

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: "overview", label: "Overview", icon: <LayoutGrid className="size-4" /> },
  { id: "history", label: "Session History", icon: <History className="size-4" /> },
  { id: "searches", label: "Saved Searches", icon: <Bookmark className="size-4" /> },
  { id: "preferences", label: "My Preferences", icon: <SlidersHorizontal className="size-4" /> },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(raw: string | null | undefined): string {
  if (!raw) return "—";
  try {
    return new Date(raw).toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return raw;
  }
}

function fmtRelative(raw: string | null | undefined): string {
  if (!raw) return "—";
  try {
    const diff = Date.now() - new Date(raw).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 2) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 30) return `${days}d ago`;
    return fmtDate(raw);
  } catch {
    return raw;
  }
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

// ── Root component ─────────────────────────────────────────────────────────────

export function UserDashboard() {
  const { user } = useAuthStore();
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const handleRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Page header */}
      <div className="flex h-14 shrink-0 items-center justify-between border-b px-6">
        <div className="flex items-center gap-3">
          <Avatar className="size-9">
            <AvatarFallback className="text-xs">
              {initials(user?.name ?? "U")}
            </AvatarFallback>
          </Avatar>
          <div>
            <h1 className="text-lg font-semibold leading-tight">My Dashboard</h1>
            <p className="text-sm text-muted-foreground">
              {user?.name} · {user?.email}
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={loading}
        >
          <RefreshCw className={cn(loading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as TabId)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div className="shrink-0 border-b px-6 py-2">
          <TabsList className="h-auto w-full justify-start gap-1 bg-transparent p-0">
            {TABS.map((tab) => (
              <TabsTrigger
                key={tab.id}
                value={tab.id}
                className="gap-2 data-[state=active]:bg-muted data-[state=active]:shadow-none"
              >
                {tab.icon}
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-6">
            <TabsContent value="overview" className="mt-0">
              <OverviewTab refreshKey={refreshKey} onLoadingChange={setLoading} />
            </TabsContent>
            <TabsContent value="history" className="mt-0">
              <HistoryTab refreshKey={refreshKey} onLoadingChange={setLoading} />
            </TabsContent>
            <TabsContent value="searches" className="mt-0">
              <SavedSearchesTab />
            </TabsContent>
            <TabsContent value="preferences" className="mt-0">
              <PreferencesTab />
            </TabsContent>
          </div>
        </ScrollArea>
      </Tabs>
    </div>
  );
}

// ── Tab 1: Overview ────────────────────────────────────────────────────────────

function OverviewTab({
  refreshKey,
  onLoadingChange,
}: {
  refreshKey: number;
  onLoadingChange: (v: boolean) => void;
}) {
  const { user } = useAuthStore();
  const { buyerPreferences, hasPreferences } = usePrefsStore();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [engagement, setEngagement] = useState<EngagementData | null>(null);
  const [loading, setLoading] = useState(true);
  const [prefsPanelOpen, setPrefsPanelOpen] = useState(false);

  useEffect(() => {
    setLoading(true);
    onLoadingChange(true);
    Promise.all([
      listSessions({ limit: 100 }),
      analyticsApi.getEngagement(30),
    ]).then(([s, e]) => {
      setSessions(s);
      setEngagement(e);
      setLoading(false);
      onLoadingChange(false);
    });
  }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <SkeletonGrid />;

  const totalMessages = sessions.reduce((acc, s) => acc + (s.user_turns ?? 0), 0);
  const avgMessages =
    sessions.length > 0 ? (totalMessages / sessions.length).toFixed(1) : "0";
  const memberSince =
    sessions.length > 0
      ? fmtDate(
          [...sessions].sort((a, b) =>
            (a.created_at ?? "").localeCompare(b.created_at ?? ""),
          )[0].created_at,
        )
      : "—";

  const recentSessions = [...sessions]
    .sort((a, b) => (b.last_active ?? "").localeCompare(a.last_active ?? ""))
    .slice(0, 5);

  return (
    <div className="flex flex-col gap-6">
      {/* Profile */}
      <Card>
        <CardContent className="flex items-center gap-4 p-5 pt-5">
          <Avatar className="size-14">
            <AvatarFallback className="text-lg font-semibold">
              {initials(user?.name ?? "U")}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-semibold">{user?.name}</h2>
            <p className="truncate text-sm text-muted-foreground">{user?.email}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Member since {memberSince}
            </p>
          </div>
          <Badge variant="secondary" className="shrink-0 capitalize">
            {user?.role ?? "user"}
          </Badge>
        </CardContent>
      </Card>

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard
          icon={<History className="size-4 text-foreground" />}
          label="Total Sessions"
          value={String(sessions.length)}
        />
        <KpiCard
          icon={<MessageSquare className="size-4 text-foreground" />}
          label="Messages Sent"
          value={String(totalMessages)}
        />
        <KpiCard
          icon={<TrendingUp className="size-4 text-foreground" />}
          label="Avg / Session"
          value={avgMessages}
        />
        <KpiCard
          icon={<Search className="size-4 text-foreground" />}
          label="Lead Rate"
          value={
            engagement
              ? `${(engagement.metrics.lead_conversion_rate * 100).toFixed(0)}%`
              : "—"
          }
        />
      </div>

      {/* Recent activity */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Recent Activity
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {recentSessions.length === 0 ? (
            <div className="px-6 pb-6">
              <EmptyState
                icon={<History className="size-6 text-muted-foreground/50" />}
                title="No sessions yet"
                body="Start a conversation and your activity will appear here."
              />
            </div>
          ) : (
            <div>
              {recentSessions.map((s, i) => (
                <React.Fragment key={s.session_id}>
                  {i > 0 && <Separator />}
                  <div className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50">
                    <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted p-1.5">
                      <MessageSquare className="size-3.5 text-muted-foreground" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {s.title || "Untitled Session"}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {s.user_turns} message{s.user_turns !== 1 ? "s" : ""}
                      </p>
                    </div>
                    <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                      <Clock className="size-3" />
                      {fmtRelative(s.last_active)}
                    </span>
                  </div>
                </React.Fragment>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Buyer preferences */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Buyer Preferences
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 text-xs"
            onClick={() => setPrefsPanelOpen(true)}
          >
            <PenLine className="size-3" />
            {hasPreferences ? "Edit" : "Set Preferences"}
          </Button>
        </CardHeader>
        <CardContent>
          {hasPreferences && buyerPreferences ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              {buyerPreferences.area && (
                <PrefChip icon={<MapPin className="size-3" />} label="Area" value={buyerPreferences.area} />
              )}
              {buyerPreferences.purpose && (
                <PrefChip icon={<Tag className="size-3" />} label="Purpose" value={buyerPreferences.purpose} />
              )}
              {buyerPreferences.bedrooms != null && (
                <PrefChip
                  icon={<BedDouble className="size-3" />}
                  label="Bedrooms"
                  value={`${buyerPreferences.bedrooms}+`}
                />
              )}
              {buyerPreferences.propertyType && (
                <PrefChip icon={<Home className="size-3" />} label="Type" value={buyerPreferences.propertyType} />
              )}
              {(buyerPreferences.priceMin || buyerPreferences.priceMax) && (
                <PrefChip
                  icon={<Banknote className="size-3" />}
                  label="Budget"
                  value={[
                    buyerPreferences.priceMin ? `AED ${buyerPreferences.priceMin.toLocaleString()}` : null,
                    buyerPreferences.priceMax ? `AED ${buyerPreferences.priceMax.toLocaleString()}` : null,
                  ]
                    .filter(Boolean)
                    .join(" – ")}
                />
              )}
            </div>
          ) : (
            <EmptyState
              icon={<SlidersHorizontal className="size-6 text-muted-foreground/50" />}
              title="No preferences set"
              body="Set your buyer preferences to personalise your search experience."
              action={
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3 gap-1.5"
                  onClick={() => setPrefsPanelOpen(true)}
                >
                  <SlidersHorizontal />
                  Set Preferences
                </Button>
              }
            />
          )}
        </CardContent>
      </Card>

      <PrefsPanel open={prefsPanelOpen} onOpenChange={setPrefsPanelOpen} />
    </div>
  );
}

// ── Tab 2: Session History ─────────────────────────────────────────────────────

function HistoryTab({
  refreshKey,
  onLoadingChange,
}: {
  refreshKey: number;
  onLoadingChange: (v: boolean) => void;
}) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    onLoadingChange(true);
    listSessions({ limit: 100 }).then((s) => {
      setSessions(
        [...s].sort((a, b) =>
          (b.last_active ?? "").localeCompare(a.last_active ?? ""),
        ),
      );
      setLoading(false);
      onLoadingChange(false);
    });
  }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <SkeletonGrid />;

  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
        All Sessions ({sessions.length})
      </h3>

      {sessions.length === 0 ? (
        <EmptyState
          icon={<History className="size-7 text-muted-foreground/50" />}
          title="No session history"
          body="Your past conversations will appear here once you start chatting."
        />
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="px-4 text-xs uppercase tracking-wide">Session</TableHead>
                <TableHead className="px-4 text-right text-xs uppercase tracking-wide">Messages</TableHead>
                <TableHead className="hidden px-4 text-xs uppercase tracking-wide md:table-cell">Created</TableHead>
                <TableHead className="px-4 text-xs uppercase tracking-wide">Last Active</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sessions.map((s) => (
                <TableRow key={s.session_id}>
                  <TableCell className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted p-1.5">
                        <MessageSquare className="size-3.5 text-muted-foreground" />
                      </div>
                      <span className="max-w-xs truncate font-medium">
                        {s.title || "Untitled Session"}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="px-4 py-3 text-right font-medium">
                    {s.user_turns}
                  </TableCell>
                  <TableCell className="hidden px-4 py-3 text-xs text-muted-foreground md:table-cell">
                    <span className="flex items-center gap-1">
                      <CalendarDays className="size-3" />
                      {fmtDate(s.created_at)}
                    </span>
                  </TableCell>
                  <TableCell className="px-4 py-3 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Clock className="size-3" />
                      {fmtRelative(s.last_active)}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

// ── Tab 3: Saved Searches ─────────────────────────────────────────────────────

function SavedSearchesTab() {
  const { savedSearches, removeSavedSearch } = usePrefsStore();

  function resumeInChat(query: string) {
    window.history.pushState({}, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));
    try {
      sessionStorage.setItem("propqa_resume_query", query);
    } catch { /* ignore */ }
  }

  if (savedSearches.length === 0) {
    return (
      <EmptyState
        icon={<Bookmark className="size-7 text-muted-foreground/50" />}
        title="No saved searches"
        body="Save searches from your conversations to quickly resume them here."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
        Saved Searches ({savedSearches.length})
      </h3>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {savedSearches.map((s) => (
          <Card key={s.searchId} className="flex flex-col">
            <CardHeader className="flex-row items-start justify-between space-y-0 pb-2">
              <div className="flex min-w-0 items-center gap-2">
                <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted p-1.5">
                  <Search className="size-3.5 text-muted-foreground" />
                </div>
                <CardTitle className="truncate text-sm">{s.label}</CardTitle>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 shrink-0 text-muted-foreground hover:text-destructive"
                onClick={() => removeSavedSearch(s.searchId)}
                aria-label="Remove saved search"
              >
                <Trash2 />
              </Button>
            </CardHeader>
            <CardContent className="pb-2">
              <p className="line-clamp-2 rounded-md bg-muted px-2.5 py-2 text-xs leading-relaxed text-muted-foreground">
                {s.query}
              </p>
            </CardContent>
            <CardFooter className="justify-between pt-0">
              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <CalendarDays className="size-3" />
                {fmtDate(s.savedAt)}
              </span>
              <Button
                variant="link"
                size="sm"
                className="h-auto gap-1 px-0 text-xs"
                onClick={() => resumeInChat(s.query)}
              >
                Resume
                <ExternalLink className="size-3" />
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ── Tab 4: My Preferences ─────────────────────────────────────────────────────

function PreferencesTab() {
  const {
    buyerPreferences,
    hasPreferences,
    personalizationEnabled,
    setPersonalizationEnabled,
    clearPreferences,
  } = usePrefsStore();
  const [prefsPanelOpen, setPrefsPanelOpen] = useState(false);

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      {/* Personalization toggle */}
      <Card>
        <CardContent className="flex items-center justify-between gap-4 p-5 pt-5">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-full bg-muted">
              <Sparkles className="size-4 text-primary" />
            </div>
            <div>
              <p className="text-sm font-semibold">Personalised Recommendations</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Show the recommendations panel alongside your search results
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Label htmlFor="personalization-switch" className="sr-only">
              Personalised Recommendations
            </Label>
            <Switch
              id="personalization-switch"
              checked={personalizationEnabled}
              onCheckedChange={setPersonalizationEnabled}
            />
          </div>
        </CardContent>
      </Card>

      {/* Preferences detail */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-sm">Buyer Preferences</CardTitle>
          <div className="flex items-center gap-2">
            {hasPreferences && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1 text-xs text-muted-foreground hover:text-destructive"
                onClick={() => {
                  if (confirm("Clear all your buyer preferences? This cannot be undone.")) {
                    clearPreferences();
                    // Clear the Redis-backed mirror too — otherwise the old
                    // values survive server-side and silently come back via
                    // boot-time hydration or a GET from another device. Also
                    // flush this tab's session-level filter-spec
                    // carry-forward so an already-applied preference isn't
                    // replayed on the next vague chat message.
                    const userId = getAuthUserId();
                    if (userId) {
                      void deletePreferences({ userId, sessionId: getActiveSessionId() });
                    }
                  }
                }}
              >
                <Trash2 className="size-3" />
                Clear
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1 text-xs"
              onClick={() => setPrefsPanelOpen(true)}
            >
              <PenLine className="size-3" />
              {hasPreferences ? "Edit" : "Set Preferences"}
            </Button>
          </div>
        </CardHeader>

        {hasPreferences && buyerPreferences ? (
          <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <PrefRow icon={<MapPin className="size-4" />} label="Preferred Area" value={buyerPreferences.area} />
            <PrefRow
              icon={<Tag className="size-4" />}
              label="Purpose"
              value={
                buyerPreferences.purpose
                  ? buyerPreferences.purpose.charAt(0).toUpperCase() + buyerPreferences.purpose.slice(1)
                  : undefined
              }
            />
            <PrefRow
              icon={<BedDouble className="size-4" />}
              label="Bedrooms"
              value={buyerPreferences.bedrooms != null ? `${buyerPreferences.bedrooms}+` : undefined}
            />
            <PrefRow icon={<Home className="size-4" />} label="Property Type" value={buyerPreferences.propertyType} />
            <PrefRow
              icon={<Banknote className="size-4" />}
              label="Min Budget"
              value={
                buyerPreferences.priceMin
                  ? `AED ${buyerPreferences.priceMin.toLocaleString()}`
                  : undefined
              }
            />
            <PrefRow
              icon={<Banknote className="size-4" />} label="Max Budget"
              value={
                buyerPreferences.priceMax
                  ? `AED ${buyerPreferences.priceMax.toLocaleString()}`
                  : undefined
              }
            />
          </CardContent>
        ) : (
          <CardContent className="flex flex-col items-center py-8 text-center">
            <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-muted">
              <SlidersHorizontal className="size-5 text-muted-foreground/50" />
            </div>
            <p className="mb-1 text-sm font-medium">No preferences configured</p>
            <CardDescription className="mb-4">
              Tell us what you&apos;re looking for so we can personalise your experience.
            </CardDescription>
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setPrefsPanelOpen(true)}
            >
              <PenLine className="size-3" />
              Set Preferences
            </Button>
          </CardContent>
        )}
      </Card>

      <PrefsPanel open={prefsPanelOpen} onOpenChange={setPrefsPanelOpen} />
    </div>
  );
}

// ── Shared UI components ───────────────────────────────────────────────────────

function KpiCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4 pt-4">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
          {icon}
        </div>
        <div>
          <p className="text-xl font-bold leading-none">{value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function PrefChip({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-muted px-3 py-2">
      <span className="shrink-0 text-muted-foreground">{icon}</span>
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-wide leading-none text-muted-foreground">
          {label}
        </p>
        <p className="mt-0.5 truncate text-xs font-semibold">{value}</p>
      </div>
    </div>
  );
}

function PrefRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value?: string;
}) {
  if (!value) return null;
  return (
    <div className="flex items-center gap-3">
      <span className="shrink-0 text-muted-foreground">{icon}</span>
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-sm font-medium">{value}</p>
      </div>
    </div>
  );
}

function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <Card className="border-dashed shadow-none">
      <CardContent className="flex flex-col items-center px-6 py-10 text-center">
        <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-muted">
          {icon}
        </div>
        <p className="mb-1 text-sm font-semibold">{title}</p>
        <CardDescription className="max-w-xs leading-relaxed">{body}</CardDescription>
        {action}
      </CardContent>
    </Card>
  );
}

function SkeletonGrid() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-20 rounded-xl" />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-16 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-40 rounded-xl" />
    </div>
  );
}
