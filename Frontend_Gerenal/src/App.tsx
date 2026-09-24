/**
 * App — main layout shell.
 *
 * Topology: Header | LeftIconRail + ChatView + MemoryPanel [+ RecommendationPanel]
 * Dashboard route: /dashboard renders UserDashboard for all authenticated users.
 * Auth gate opens automatically on first visit (or when user clicks Sign In).
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";
import { ChevronLeft } from "lucide-react";
import { Header } from "@/components/layout/Header";
import { LeftIconRail } from "@/components/layout/LeftIconRail";
import { MemoryPanel } from "@/components/layout/MemoryPanel";
import { MessageList, type MessageListHandle, WELCOME_SUGGESTION_CHIPS } from "@/components/chat/MessageList";
import { PropertiesSidebar } from "@/components/chat/PropertiesSidebar";
import type { CardGroup } from "@/components/chat/CardsPanel";
import { HitlPrompt } from "@/components/chat/HitlPrompt";
import { Composer } from "@/components/chat/Composer";
import { SessionStrip } from "@/components/chat/SessionStrip";
import { AuthGate } from "@/components/auth/AuthGate";
import { useChat } from "@/hooks/useChat";
import { useAuthStore } from "@/store/authStore";
import { useChatStore } from "@/store/chatStore";
import { usePrefsStore } from "@/store/prefsStore";
import { continuationFromProfile, useSessionProfileStore } from "@/store/sessionProfileStore";
import { RecommendationPanel } from "@/components/recommendations/RecommendationPanel";
import { PrefsPanel } from "@/components/recommendations/PrefsPanel";
import { UserDashboard } from "@/components/admin/AdminDashboard";
import { compactContext } from "@/api/sessionApi";
import { cn } from "@/lib/utils";
import { filterMessagesForCardGroups } from "@/lib/cardGroups";
import {
  LISTING_FAQ_SUGGESTION_CHIPS,
  MAX_ATTACHED_PROPERTY_IDS,
  MAX_INQUIRY_PROPERTY_IDS,
  looksLikeFreshInventorySearch,
  type AttachedListing,
} from "@/lib/followUpSuggestions";
import { pickFigmaCardTitle, pickCardImages } from "@/lib/propertyCard";
import type { PropertyCard } from "@/store/chatStore";

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [propertiesPanelOpen, setPropertiesPanelOpen] = useState(true);
  const [authGateOpen, setAuthGateOpen] = useState(false);
  const [authGateTab, setAuthGateTab] = useState<"login" | "register">("login");

  // Dashboard route: show UserDashboard when URL path is /dashboard
  const [currentPath, setCurrentPath] = useState(
    typeof window !== "undefined" ? window.location.pathname : "/"
  );
  useEffect(() => {
    const handler = () => setCurrentPath(window.location.pathname);
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);
  const isAdminRoute = currentPath === "/dashboard";

  // Preferences store — initialised on mount (no-op if already loaded from localStorage)
  const { personalizationEnabled, setPersonalizationEnabled, hasPreferences } = usePrefsStore();
  const [prefsPanelOpen, setPrefsPanelOpen] = useState(false);

  function handleTogglePersonalization() {
    // Defensive guard: the Header only wires this handler up for
    // authenticated users (see onTogglePersonalization below), but guard
    // here too since preferences are a signed-in-only feature.
    if (!useAuthStore.getState().isAuthenticated) return;
    if (personalizationEnabled) {
      // Panel is showing → hide it
      setPersonalizationEnabled(false);
    } else if (hasPreferences) {
      // Preferences already configured → just show the panel
      setPersonalizationEnabled(true);
    } else {
      // No preferences yet → open setup dialog first
      setPrefsPanelOpen(true);
    }
  }

  const msgListRef = useRef<MessageListHandle>(null);

  const {
    messages,
    isStreaming,
    loadingStatus,
    sessionId,
    guestBanner,
    sendMessage,
    cancelResponse,
    resumeHitl,
    startNewChat,
    loadSession,
    handleForgetSession,
    handleForgetAllConversations,
    dismissGuestBanner,
    sendLeadCaptureSubmit,
    sendLeadDismiss,
    submitLeadForMessage,
    submitLeadForProperty,
  } = useChat();

  const [inquiryPropertyIds, setInquiryPropertyIds] = useState<number[]>([]);
  const [attachedListings, setAttachedListings] = useState<AttachedListing[]>([]);
  const attachedIdsRef = useRef<number[]>([]);

  useEffect(() => {
    attachedIdsRef.current = attachedListings.map((l) => l.id);
  }, [attachedListings]);

  const toggleAttachedProperty = useCallback((propertyId: number, card: PropertyCard) => {
    setAttachedListings((prev) => {
      let next: AttachedListing[];
      if (prev.some((l) => l.id === propertyId)) {
        next = prev.filter((l) => l.id !== propertyId);
      } else if (prev.length >= MAX_ATTACHED_PROPERTY_IDS) {
        toast.message(`You can attach up to ${MAX_ATTACHED_PROPERTY_IDS} listings`);
        return prev;
      } else {
        const title = pickFigmaCardTitle(card);
        const imageUrl = pickCardImages(card)[0];
        toast.message("Added to AI chat");
        next = [{ id: propertyId, title, imageUrl }, ...prev];
      }
      // Keep ref in sync immediately (avoid empty IDs if send races useEffect).
      attachedIdsRef.current = next.map((l) => l.id);
      return next;
    });
  }, []);

  const removeAttachedProperty = useCallback((propertyId: number) => {
    setAttachedListings((prev) => {
      const next = prev.filter((l) => l.id !== propertyId);
      attachedIdsRef.current = next.map((l) => l.id);
      return next;
    });
  }, []);

  const clearAttachedListings = useCallback(() => {
    attachedIdsRef.current = [];
    setAttachedListings([]);
  }, []);

  const toggleInquiryProperty = useCallback((propertyId: number) => {
    setInquiryPropertyIds((prev) => {
      if (prev.includes(propertyId)) {
        return prev.filter((id) => id !== propertyId);
      }
      if (prev.length >= MAX_INQUIRY_PROPERTY_IDS) {
        toast.message(`You can add up to ${MAX_INQUIRY_PROPERTY_IDS} listings to an inquiry`);
        return prev;
      }
      return [...prev, propertyId];
    });
  }, []);

  const handleNewChat = useCallback(async () => {
    clearAttachedListings();
    await startNewChat();
  }, [clearAttachedListings, startNewChat]);

  const handleSelectSession = useCallback(
    (sid: string) => {
      clearAttachedListings();
      void loadSession(sid);
    },
    [clearAttachedListings, loadSession],
  );

  const sendWithFocusedIds = useCallback(
    (text: string, opts?: { skipUserAppend?: boolean }) => {
      // New catalog searches while chips are attached must leave listing-FAQ
      // mode — otherwise the concierge answers about the attached listing
      // (or inherits its filters) instead of running property_search.
      let ids = attachedIdsRef.current;
      const clearedForFreshSearch =
        ids.length > 0 && looksLikeFreshInventorySearch(text);
      if (clearedForFreshSearch) {
        attachedIdsRef.current = [];
        setAttachedListings([]);
        ids = [];
      }
      return sendMessage(text, {
        ...opts,
        focusedPropertyIds: ids,
      });
    },
    [sendMessage],
  );

  const submitClarifying = useCallback(
    (answers: Record<string, string>) => {
      useSessionProfileStore.getState().merge(answers);
      const text = continuationFromProfile(useSessionProfileStore.getState().profile);
      void sendWithFocusedIds(text, { skipUserAppend: true });
    },
    [sendWithFocusedIds],
  );

  const { isGuest, isAuthenticated, isLoading: authLoading, initialize } = useAuthStore();
  const chatStore = useChatStore();

  // Initialise auth on mount
  useEffect(() => {
    initialize().then(() => {
      const { isGuest, isAuthenticated } = useAuthStore.getState();
      // Show auth gate on very first visit (no session cookie + no refresh token)
      const hasVisited = !!localStorage.getItem("propqa_has_visited");
      if (isGuest && !hasVisited) {
        localStorage.setItem("propqa_has_visited", "1");
        setAuthGateOpen(true);
      }
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // /dashboard (My Dashboard → includes the "My Preferences" tab) is a
  // signed-in-only surface. Guests navigating there directly (or staying
  // after a logout) get bounced back to the chat with the sign-in dialog
  // open, so preferences never become reachable in guest mode.
  useEffect(() => {
    if (authLoading || !isAdminRoute || isAuthenticated) return;
    window.history.pushState({}, "", "/");
    setCurrentPath("/");
    openSignIn();
  }, [isAdminRoute, isAuthenticated, authLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to bottom when messages change
  useEffect(() => {
    msgListRef.current?.scrollToBottom();
  }, [messages.length, isStreaming]);

  // Collect assistant messages that carry cards, in order — paired with the
  // preceding user message. Zero-match follow-ups keep prior groups visible.
  const cardGroups: CardGroup[] = [];
  const cardBearing = filterMessagesForCardGroups(messages);
  for (const m of cardBearing) {
    const i = messages.findIndex((x) => x.id === m.id);
    const preceding = [...messages.slice(0, i)].reverse().find((x) => x.role === "user");
    cardGroups.push({
      messageId: m.id,
      userQuery: preceding?.content ?? "",
      cards: m.cards as CardGroup["cards"],
      searchUrl: m.searchUrl,
      appliedFilters: m.appliedFilters,
      timestamp: m.timestamp,
    });
  }
  const hasCards = cardGroups.length > 0;

  // Re-open the properties shell whenever a new result set appears.
  useEffect(() => {
    if (hasCards) setPropertiesPanelOpen(true);
  }, [hasCards]);

  async function handleCompact() {
    const result = await compactContext(sessionId);
    if (result) toast.success("Context compacted successfully.");
    else toast.error("Failed to compact context.");
  }

  async function handleForgetAll() {
    if (!confirm("Forget this entire session? This cannot be undone.")) return;
    await handleForgetSession(sessionId);
    toast("Session cleared.");
  }

  function openSignIn() {
    setAuthGateTab("login");
    setAuthGateOpen(true);
  }

  function openRegister() {
    setAuthGateTab("register");
    setAuthGateOpen(true);
  }

  if (authLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex items-center gap-2 text-muted-foreground">
          <span className="typing-dot" />
          <span className="typing-dot" />
          <span className="typing-dot" />
        </div>
      </div>
    );
  }

  // ── User Dashboard route ─────────────────────────────────────────────────────
  // Signed-in-only (includes the "My Preferences" tab) — the redirect
  // effect above bounces guests back to "/", but guard the render too so
  // UserDashboard (and its preferences UI) never flashes on screen first.
  if (isAdminRoute) {
    if (!isAuthenticated) {
      return null;
    }
    return (
      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-white">
        <Header
          onSignIn={openSignIn}
          onRegister={openRegister}
          onBackToChat={() => { window.history.pushState({}, "", "/"); setCurrentPath("/"); }}
        />
        <div className="relative z-10 flex min-h-0 flex-1 gap-1 overflow-hidden px-8 pb-3 sm:px-12">
          <LeftIconRail />
          <div className="min-h-0 min-w-0 flex-1 overflow-hidden rounded-[20px] border border-[#E8ECF3] bg-white p-5 shadow-[0px_5.9009px_35.4054px_rgba(20,20,24,0.02)]">
            <UserDashboard />
          </div>
        </div>
        <AuthGate
          open={authGateOpen}
          onOpenChange={setAuthGateOpen}
          defaultTab={authGateTab}
          onContinueAsGuest={() => setAuthGateOpen(false)}
        />
      </div>
    );
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-white">
      <Header
          onSignIn={openSignIn}
          onRegister={openRegister}
          onShowHistory={isAuthenticated ? () => setSidebarOpen(true) : undefined}
          onTogglePersonalization={isAuthenticated ? handleTogglePersonalization : undefined}
          personalizationEnabled={personalizationEnabled}
        />

      <div className="relative z-10 flex min-h-0 flex-1 flex-col gap-1 overflow-hidden px-8 pb-3 sm:px-12 md:flex-row md:items-stretch">
        <div className="flex min-h-0 min-w-0 flex-1 gap-1 overflow-hidden">
          <LeftIconRail
            expanded={sidebarOpen}
            onExpandedChange={setSidebarOpen}
            currentSessionId={sessionId}
            isStreaming={isStreaming}
            sessionTitleHint={messages.find((m) => m.role === "user")?.content ?? null}
            onNewChat={() => void handleNewChat()}
            onSelectSession={handleSelectSession}
            onForgetSession={handleForgetSession}
            onForgetAll={handleForgetAllConversations}
          />

          {/* Chat with AI Assistant — Figma card */}
          <main
            className={cn(
              "relative flex min-h-0 min-w-0 flex-1 flex-col gap-3.5 overflow-clip",
              "rounded-[20px] border border-[#E8ECF3] bg-white p-5",
              "shadow-[0px_5.9009px_35.4054px_rgba(20,20,24,0.02)]",
            )}
          >
            <div className="flex shrink-0 items-center gap-4">
              <button
                type="button"
                className="flex size-6 shrink-0 items-center justify-center text-[#141B34] hover:opacity-70 focus:outline-none"
                aria-label="Back"
                onClick={() => {
                  if (messages.length > 0) void handleNewChat();
                }}
              >
                <ChevronLeft className="size-4" strokeWidth={1.5} />
              </button>
              <h1 className="text-lg font-medium leading-[1.4] text-[#141B34]">AI Assistant</h1>
            </div>
            <div className="h-px w-full shrink-0 bg-[#D8DDE6]" />

            <div className="flex min-h-0 flex-1 flex-col overflow-clip">
              <MessageList
                ref={msgListRef}
                messages={messages}
                sessionId={sessionId}
                isLoading={isStreaming}
                loadingStatus={loadingStatus}
                liveSteps={chatStore.steps}
                guestBanner={guestBanner}
                onRetry={(p) => sendWithFocusedIds(p, { skipUserAppend: true })}
                onSignUp={openRegister}
                onSignIn={openSignIn}
                onDismissGuestBanner={dismissGuestBanner}
                onSubmitLead={submitLeadForMessage}
                onSuggestionClick={(q) => void sendWithFocusedIds(q)}
                onClarify={submitClarifying}
                selectedInquiryPropertyIds={inquiryPropertyIds}
                onSelectedInquiryPropertyIdsChange={setInquiryPropertyIds}
                className="min-h-0 min-w-0 flex-1 basis-0 overflow-y-auto"
              />

              {chatStore.pendingHitl.length > 0 && (
                <div className="shrink-0 border-t border-[#E8ECF3]">
                  <HitlPrompt
                    frames={chatStore.pendingHitl}
                    sessionId={sessionId}
                    onResume={resumeHitl}
                    onSuggestionResubmit={(q) => void sendWithFocusedIds(q)}
                    onLeadCaptureSubmit={sendLeadCaptureSubmit}
                    onDismiss={sendLeadDismiss}
                  />
                </div>
              )}

              <SessionStrip />
              <Composer
                className="shrink-0"
                sessionId={sessionId}
                disabled={chatStore.pendingHitl.length > 0}
                isStreaming={isStreaming}
                onStop={cancelResponse}
                onSend={(text) => void sendWithFocusedIds(text)}
                suggestions={
                  attachedListings.length > 0
                    ? LISTING_FAQ_SUGGESTION_CHIPS
                    : WELCOME_SUGGESTION_CHIPS
                }
                onSuggestionClick={(q) => void sendWithFocusedIds(q)}
                attachedListings={attachedListings}
                onRemoveAttached={removeAttachedProperty}
                onClearAttached={clearAttachedListings}
              />
            </div>
          </main>
        </div>

        {hasCards && propertiesPanelOpen && (
          <div
            className={cn(
              "flex min-h-0 max-h-[45vh] w-full shrink-0 flex-col overflow-hidden md:max-h-none md:max-w-[660px]",
              "rounded-[20px] border border-[#E8ECF3] bg-white p-5",
              "shadow-[0px_5.9009px_35.4054px_rgba(20,20,24,0.02)]",
            )}
          >
            <p className="mb-4 shrink-0 text-xl font-medium capitalize leading-[1.4] text-[#141B34]">
              Selected property
            </p>
            <PropertiesSidebar
              open={propertiesPanelOpen}
              onOpenChange={setPropertiesPanelOpen}
              groups={cardGroups}
              sessionId={sessionId}
              inquiryPropertyIds={inquiryPropertyIds}
              onToggleInquiryProperty={toggleInquiryProperty}
              attachedPropertyIds={attachedListings.map((l) => l.id)}
              onToggleAttachedProperty={toggleAttachedProperty}
              onSubmitLead={async (data) => {
                const pid = data.property_ids[0];
                if (pid) await submitLeadForProperty(pid, data);
              }}
              className="min-h-0 w-full max-h-none flex-1 border-0 bg-transparent shadow-none md:w-full md:max-w-none"
            />
          </div>
        )}

        {hasCards && !propertiesPanelOpen && (
          <PropertiesSidebar
            open={false}
            onOpenChange={setPropertiesPanelOpen}
            groups={cardGroups}
            sessionId={sessionId}
            inquiryPropertyIds={inquiryPropertyIds}
            onToggleInquiryProperty={toggleInquiryProperty}
            attachedPropertyIds={attachedListings.map((l) => l.id)}
            onToggleAttachedProperty={toggleAttachedProperty}
          />
        )}

        <RecommendationPanel
          visible={isAuthenticated && personalizationEnabled}
          recommendations={[]}
          onClose={() => setPersonalizationEnabled(false)}
        />

        {memoryOpen && (
          <MemoryPanel
            isOpen={memoryOpen}
            sessionId={sessionId}
            summary={
              chatStore.envelope?.suggestions
                ?.map((s) => (typeof s === "string" ? s : s.label))
                .join(" ") ?? ""
            }
            knowledge={chatStore.health as Record<string, unknown> | undefined}
            recallHits={chatStore.recallHits}
            contextUsage={chatStore.contextUsage}
            onClose={() => setMemoryOpen(false)}
            onCompact={handleCompact}
            onForgetAll={handleForgetAll}
          />
        )}
      </div>

      <AuthGate
        open={authGateOpen}
        onOpenChange={setAuthGateOpen}
        defaultTab={authGateTab}
        onContinueAsGuest={() => setAuthGateOpen(false)}
      />

      <PrefsPanel open={prefsPanelOpen} onOpenChange={setPrefsPanelOpen} />
    </div>
  );
}
