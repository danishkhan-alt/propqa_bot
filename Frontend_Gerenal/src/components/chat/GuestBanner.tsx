/**
 * GuestBanner — Figma "Unlock full AI features" modal for guest conversion.
 *
 * Shown after search_count / agent_click / comparison triggers (same panel).
 */

import { useCallback, useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export type BannerTrigger = "search_count" | "agent_click" | "comparison";

interface GuestBannerProps {
  /** Kept for call-site compatibility; Figma copy is shared across triggers. */
  trigger: BannerTrigger;
  onSignUp: () => void;
  /** Opens login — "I already have an account." */
  onSignIn?: () => void;
  onDismiss?: () => void;
  className?: string;
}

const SEARCH_QUERY_PARTS: { text: string; bold?: boolean }[] = [
  { text: "3-bed villa for sale in " },
  { text: "Dubai Hills Estate", bold: true },
  { text: " under " },
  { text: "AED 3.5M", bold: true },
  { text: " with " },
  { text: "a flexible payment plan", bold: true },
];

function FloatingPill({
  label,
  className,
  opacity = 0.5,
  textSize = "text-[10px]",
}: {
  label: string;
  className?: string;
  opacity?: number;
  textSize?: string;
}) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute rounded-full bg-[#FAFCFF] px-[9px] py-[9px] shadow-[0_0_15px_rgba(112,181,246,0.6)]",
        className,
      )}
      style={{ opacity }}
      aria-hidden
    >
      <span className={cn("font-medium leading-[1.5] text-[rgba(26,20,51,0.6)]", textSize)}>
        {label}
      </span>
    </div>
  );
}

export function GuestBanner({
  trigger: _trigger,
  onSignUp,
  onSignIn,
  onDismiss,
  className,
}: GuestBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  const titleId = useId();
  const descId = useId();

  const handleDismiss = useCallback(() => {
    setDismissed(true);
    onDismiss?.();
  }, [onDismiss]);

  useEffect(() => {
    if (dismissed) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [dismissed]);

  useEffect(() => {
    if (dismissed) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") handleDismiss();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dismissed, handleDismiss]);

  if (dismissed || typeof document === "undefined") return null;

  function handleSignUp() {
    handleDismiss();
    onSignUp();
  }

  function handleSignIn() {
    handleDismiss();
    (onSignIn ?? onSignUp)();
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-[rgba(20,20,24,0.35)] p-4"
      role="presentation"
      onClick={handleDismiss}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        className={cn(
          "relative flex w-full max-w-[400px] flex-col overflow-hidden rounded-[20px] bg-white shadow-[0_16px_48px_rgba(20,20,24,0.12)]",
          className,
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Illustration */}
        <div
          className="relative isolate flex h-[203px] w-full shrink-0 items-center justify-center overflow-hidden px-6 py-[9px]"
          style={{
            backgroundColor: "#E8ECF3",
            backgroundImage:
              "radial-gradient(circle, rgba(15,69,150,0.06) 1.2px, transparent 1.2px)",
            backgroundSize: "14px 14px",
            boxShadow:
              "inset -3px -3px 19px rgba(124,164,248,0.1), inset 3px 3px 19px rgba(124,164,248,0.1)",
          }}
        >
          <FloatingPill
            label="Close to metro and groceries"
            opacity={0.2}
            textSize="text-[9px]"
            className="left-0 top-[32px]"
          />
          <FloatingPill
            label="Close to metro and groceries"
            opacity={0.2}
            textSize="text-[9px]"
            className="right-0 top-[16px]"
          />
          <FloatingPill
            label="Safe area, easy commute to JLT or Downtown"
            opacity={0.5}
            className="bottom-[28px] left-[-12px] max-w-[230px]"
          />
          <FloatingPill
            label="Safe area, easy commute to JLT or Downtown"
            opacity={0.5}
            className="bottom-[56px] right-[-20px] max-w-[230px]"
          />

          <div className="relative z-[6] w-full max-w-[342px] rounded-[19px] border border-[rgba(27,96,244,0.1)] bg-white/[0.01] p-[9.5px]">
            <div className="flex items-center gap-3 rounded-[13px] bg-[#FAFCFF] px-[13px] py-[13px] shadow-[0_0_16px_#1B60F4]">
              <p className="min-w-0 flex-1 text-[13px] font-medium leading-[1.5] text-[rgba(26,20,51,0.6)]">
                {SEARCH_QUERY_PARTS.map((part, i) =>
                  part.bold ? (
                    <span key={i} className="font-semibold text-[#1A1433]">
                      {part.text}
                    </span>
                  ) : (
                    <span key={i}>{part.text}</span>
                  ),
                )}
              </p>
              <img
                src="/AI_Icon.svg"
                alt=""
                width={32}
                height={32}
                className="size-8 shrink-0"
                draggable={false}
              />
            </div>
          </div>

          <button
            type="button"
            onClick={handleDismiss}
            aria-label="Close"
            className="absolute right-2 top-2 z-[7] flex size-10 items-center justify-center rounded-full border border-[#D8DDE6] bg-white text-[#141B34] transition-colors hover:bg-[#F5F7FA]"
          >
            <X className="size-4" strokeWidth={1.2} />
          </button>
        </div>

        {/* Copy + CTAs */}
        <div className="flex flex-col gap-4 px-6 pb-6 pt-0">
          <div className="flex flex-col items-center gap-2 pt-4">
            <h2
              id={titleId}
              className="w-full text-center text-lg font-medium leading-[1.4] text-[#141B34]"
            >
              Unlock full AI features
            </h2>
            <p
              id={descId}
              className="max-w-[324px] text-center text-sm font-normal leading-[1.5] text-[#494A58]"
            >
              You have reached your trial message limit. Sign in or sign up in seconds to continue
              the conversation and save your favorites.
            </p>
          </div>

          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={handleSignUp}
              className="flex h-10 w-full items-center justify-center rounded-full bg-[#1B60F4] px-5 text-sm font-semibold leading-[1.5] text-white transition-opacity hover:opacity-95"
            >
              Sign Up
            </button>
            <button
              type="button"
              onClick={handleSignIn}
              className="flex h-9 w-full items-center justify-center rounded-3xl px-3 text-xs font-medium leading-[1.5] tracking-[-0.01em] text-[#747288] transition-colors hover:text-[#494A58]"
            >
              I already have an account.
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
