/**
 * Header — Figma marketing chrome (light bar, Layer_v1 logo, CTAs).
 *
 * Guests see Sign Up. Authenticated users
 * see UserMenu (+ optional personalization / back-to-chat). Theme, New Chat,
 * and conversation history live on LeftIconRail. Center nav (Buy/Rent/…) is omitted.
 */

import { Sparkles, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { UserMenu } from "@/components/auth/UserMenu";
import { useAuthStore } from "@/store/authStore";
import { cn } from "@/lib/utils";

const HEADER_LOGO_SRC = "/propqa-header-logo.svg";

interface HeaderProps {
  /** Kept for App wiring compatibility; sidebar toggle lives outside Header */
  onToggleSidebar?: () => void;
  onSignIn?: () => void;
  onRegister?: () => void;
  onShowHistory?: () => void;
  /** Kept for App wiring; Clear Chat is rendered by LeftIconRail */
  onNewChat?: () => void;
  /** Toggle the RecommendationPanel — authenticated users only */
  onTogglePersonalization?: () => void;
  /**
   * Whether the "For You" recommendations panel is currently shown
   * (controls icon highlight only). Saved preferences are always used
   * for search/filtering regardless of this flag.
   */
  personalizationEnabled?: boolean;
  /** Back-to-chat link — shown on the /dashboard route */
  onBackToChat?: () => void;
  className?: string;
}

export function Header({
  onRegister,
  onShowHistory,
  onTogglePersonalization,
  personalizationEnabled,
  onBackToChat,
  className,
}: HeaderProps) {
  const { isAuthenticated } = useAuthStore();

  return (
    <header
      className={cn(
        "relative z-10 flex h-20 shrink-0 items-center justify-between bg-transparent px-8 sm:px-12",
        className,
      )}
    >
      <div className="flex items-center gap-3">
        {onBackToChat && (
          <button
            onClick={onBackToChat}
            className="flex items-center gap-1.5 rounded-full px-2 py-1 text-sm font-medium text-[#141B34] hover:bg-[#EDF0F5] focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]"
            aria-label="Back to chat"
          >
            <ArrowLeft className="size-4" />
            <span className="hidden sm:block">Back to Chat</span>
          </button>
        )}
        <img
          src={HEADER_LOGO_SRC}
          alt="PropQA"
          className="h-8 w-auto max-w-[146px] object-contain object-left"
          width={146}
          height={32}
        />
      </div>

      <div className="flex items-center gap-6">
        {onTogglePersonalization && (
          <button
            onClick={onTogglePersonalization}
            className={cn(
              "rounded-full p-2 focus:outline-none transition-colors",
              personalizationEnabled
                ? "bg-[#EDF0F5] text-[#141B34]"
                : "text-[#141B34]/70 hover:bg-[#EDF0F5]",
            )}
            aria-label={personalizationEnabled ? "Hide recommendations panel" : "Show recommendations panel"}
            title={personalizationEnabled ? "Recommendations panel shown — click to hide" : "Show personalised recommendations panel"}
          >
            <Sparkles className="size-4" />
          </button>
        )}

        {isAuthenticated ? (
          <UserMenu onShowHistory={onShowHistory} />
        ) : (
          <Button
            type="button"
            variant="outline"
            className="h-12 w-[100px] gap-2.5 rounded-3xl border border-[#141B34] bg-transparent px-5 py-2.5 text-sm font-semibold leading-[1.5] text-[#141B34] shadow-none hover:bg-[#EDF0F5] hover:text-[#141B34]"
            onClick={onRegister}
          >
            Sign Up
          </Button>
        )}
      </div>
    </header>
  );
}
