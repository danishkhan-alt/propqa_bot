/**
 * Composer — Figma input card: textarea + bottom row
 * (tags | mic+send) idle · (waveform | stop+send) recording.
 *
 * Voice: OpenAI Realtime translation (any language → English) via Backend
 * ephemeral client secret + browser WebRTC.
 *
 * Attached listing chips (listing-scoped FAQ) sit above the bordered input.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import { ArrowUp, Home, Mic, X } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  createVoiceSession,
  VoiceSessionApiError,
} from "@/api/voiceSessionApi";
import {
  mergeVoiceTranscript,
  startVoiceRealtime,
  type VoiceRealtimeSession,
} from "@/lib/voiceRealtime";
import {
  VISIBLE_ATTACHED_CHIP_COUNT,
  type AttachedListing,
} from "@/lib/followUpSuggestions";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const MIN_HEIGHT = 48;
/** Cap so the composer grows into the chat area without dominating the viewport. */
const MAX_HEIGHT = 240;

/** Bar count / pattern inspired by Figma Frame 2147229405 (4px bars, 2px gap). */
const WAVE_BAR_COUNT = 64;
/** Quiet edge height (px) — Stroke/100 */
const WAVE_QUIET = 3;
/** Active center peaks (px) — Primary/400 */
const WAVE_PEAKS = [7, 13, 5, 7, 7, 7, 20, 38, 14, 20, 12, 12, 12, 7, 7, 12, 12, 12, 7, 7, 20, 38, 14, 20, 12, 12, 12, 7, 20, 38, 14, 20, 12, 12, 12] as const;
const WAVE_BASE_HEIGHTS = (() => {
  const heights = Array.from({ length: WAVE_BAR_COUNT }, () => WAVE_QUIET);
  const start = Math.floor((WAVE_BAR_COUNT - WAVE_PEAKS.length) / 2);
  WAVE_PEAKS.forEach((h, i) => {
    heights[start + i] = h;
  });
  return heights;
})();

export interface ComposerSuggestion {
  label: string;
  message: string;
}

interface ComposerProps {
  disabled?: boolean;
  /** True while an assistant turn is streaming — shows Stop instead of Send. */
  isStreaming?: boolean;
  onStop?: () => void;
  onSend: (text: string) => void;
  placeholder?: string;
  className?: string;
  /** Chat session id — used to rate-limit / identify voice session minting. */
  sessionId?: string | null;
  /** Chips shown inside the input footer when not recording */
  suggestions?: ComposerSuggestion[];
  onSuggestionClick?: (message: string) => void;
  /** Listings attached for listing-scoped FAQ mode. */
  attachedListings?: AttachedListing[];
  onRemoveAttached?: (propertyId: number) => void;
  onClearAttached?: () => void;
}

function buildBaseWaveHeights(): number[] {
  return WAVE_BASE_HEIGHTS.slice();
}

function VoiceWaveform({ active, levels }: { active: boolean; levels: number[] }) {
  return (
    <div
      className="flex h-[38px] min-w-0 flex-1 items-center gap-0.5 overflow-hidden"
      aria-hidden
    >
      {levels.map((h, i) => {
        const isActive = h > WAVE_QUIET + 1;
        return (
          <span
            key={i}
            className={cn(
              "w-1 shrink-0 rounded-[1px]",
              isActive ? "bg-[#59A4FF]" : "bg-[#D8DDE6]",
              active && isActive && "transition-[height] duration-75",
            )}
            style={{ height: `${Math.max(WAVE_QUIET, Math.round(h))}px` }}
          />
        );
      })}
    </div>
  );
}

function AttachedListingChip({
  listing,
  onRemove,
}: {
  listing: AttachedListing;
  onRemove?: (propertyId: number) => void;
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-[140px] items-center gap-1.5 rounded-full",
        "bg-[#E8ECF3] px-2.5 py-1 text-xs font-medium text-[#494A58]",
      )}
    >
      <Home className="size-3.5 shrink-0 text-[#747288]" aria-hidden />
      <span className="min-w-0 truncate" title={listing.title}>
        {listing.title}
      </span>
      {onRemove && (
        <button
          type="button"
          onClick={() => onRemove(listing.id)}
          className="flex shrink-0 items-center justify-center rounded-full p-0.5 text-[#747288] hover:bg-[#D8DDE6] hover:text-[#141B34] focus:outline-none focus:ring-1 focus:ring-[#979CAE]"
          aria-label={`Remove ${listing.title}`}
        >
          <X className="size-3" strokeWidth={2.25} />
        </button>
      )}
    </span>
  );
}

export function Composer({
  disabled,
  isStreaming = false,
  onStop,
  onSend,
  placeholder,
  className,
  sessionId,
  suggestions,
  onSuggestionClick,
  attachedListings = [],
  onRemoveAttached,
  onClearAttached: _onClearAttached,
}: ComposerProps) {
  const [value, setValue] = useState("");
  const [focused, setFocused] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [waveLevels, setWaveLevels] = useState(buildBaseWaveHeights);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const voiceSessionRef = useRef<VoiceRealtimeSession | null>(null);
  const rafRef = useRef(0);
  const baseTextRef = useRef("");
  const streamedRef = useRef("");
  const wantRecordingRef = useRef(false);
  const startingRef = useRef(false);

  const hasAttached = attachedListings.length > 0;
  const visibleChips = attachedListings.slice(0, VISIBLE_ATTACHED_CHIP_COUNT);
  const overflowCount = Math.max(0, attachedListings.length - VISIBLE_ATTACHED_CHIP_COUNT);

  const stopAudioGraph = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
  }, []);

  const stopRecording = useCallback(async () => {
    wantRecordingRef.current = false;
    startingRef.current = false;
    const session = voiceSessionRef.current;
    voiceSessionRef.current = null;
    stopAudioGraph();
    setIsRecording(false);
    setIsConnecting(false);
    setWaveLevels(buildBaseWaveHeights());
    if (session) {
      try {
        await session.stop();
      } catch {
        /* already stopped */
      }
    }
  }, [stopAudioGraph]);

  useEffect(() => () => {
    void stopRecording();
  }, [stopRecording]);

  // Focus textarea when the first listing is attached (mobile: chips become visible).
  useEffect(() => {
    if (attachedListings.length === 1) {
      textareaRef.current?.focus();
    }
  }, [attachedListings.length]);

  function autoResize() {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const scrollH = ta.scrollHeight;
    const newH = Math.min(Math.max(scrollH, MIN_HEIGHT), MAX_HEIGHT);
    ta.style.height = `${newH}px`;
    ta.style.overflowY = scrollH > MAX_HEIGHT ? "auto" : "hidden";
  }

  function resetHeight() {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = isStreaming ? "0px" : `${MIN_HEIGHT}px`;
    ta.style.overflowY = "hidden";
  }

  // Seed the textarea height once; thereafter autoResize owns the DOM style
  // (do not put a fixed height in the React `style` prop — it would clobber growth).
  useEffect(() => {
    resetHeight();
  }, []);

  useLayoutEffect(() => {
    if (isStreaming || !value) {
      resetHeight();
      return;
    }
    autoResize();
  }, [value, isStreaming]);

  function startWavePulse() {
    const pulse = () => {
      if (!wantRecordingRef.current) return;
      const t = Date.now() / 220;
      setWaveLevels(
        WAVE_BASE_HEIGHTS.map((h, i) => {
          if (h <= WAVE_QUIET) return WAVE_QUIET;
          const wobble = 0.55 + 0.45 * Math.sin(t + i * 0.35);
          return Math.min(38, Math.max(WAVE_QUIET, h * wobble));
        }),
      );
      rafRef.current = requestAnimationFrame(pulse);
    };
    rafRef.current = requestAnimationFrame(pulse);
  }

  async function startRecording() {
    if (disabled) {
      toast("Wait for the current reply to finish, then try voice again.");
      return;
    }
    if (isRecording || startingRef.current || isConnecting) return;
    toast("Starting voice…");
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      toast("Voice input isn’t supported in this browser.");
      return;
    }

    startingRef.current = true;
    setIsConnecting(true);
    baseTextRef.current = value.trim() ? `${value.trim()} ` : "";
    streamedRef.current = "";
    wantRecordingRef.current = true;

    try {
      const { client_secret } = await createVoiceSession({ sessionId, timeoutMs: 15_000 });
      if (!wantRecordingRef.current) {
        startingRef.current = false;
        setIsConnecting(false);
        return;
      }

      const session = await startVoiceRealtime(client_secret, {
        onTranscriptDelta: (delta, opts) => {
          if (!wantRecordingRef.current) return;
          if (opts?.replaceAll) {
            streamedRef.current = delta;
          } else {
            if (opts?.resetStreamed) streamedRef.current = "";
            streamedRef.current += delta;
          }
          setValue(mergeVoiceTranscript(baseTextRef.current, streamedRef.current));
        },
        onError: (message) => {
          toast(message || "Voice input stopped unexpectedly.");
          void stopRecording();
        },
      });

      if (!wantRecordingRef.current) {
        await session.stop();
        startingRef.current = false;
        setIsConnecting(false);
        return;
      }

      // Only show Listening after WebRTC is actually up (avoids fake Listening on hung API).
      voiceSessionRef.current = session;
      setIsConnecting(false);
      setIsRecording(true);
      setWaveLevels(buildBaseWaveHeights());
      startWavePulse();
      startingRef.current = false;
    } catch (err) {
      startingRef.current = false;
      setIsConnecting(false);
      wantRecordingRef.current = false;
      const message =
        err instanceof VoiceSessionApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Couldn’t start voice input.";
      toast(message);
      await stopRecording();
    }
  }

  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    setValue(e.target.value);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter inserts a newline (browser default).
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    if (isRecording) void stopRecording();
    onSend(text);
    setValue("");
    resetHeight();
    textareaRef.current?.focus();
  }

  const canSend = !disabled && !isStreaming && value.trim().length > 0;

  const resolvedPlaceholder =
    placeholder ??
    (isRecording
      ? "Listening…"
      : isConnecting
        ? "Connecting voice…"
        : disabled
          ? "Waiting for response…"
          : hasAttached
            ? "Ask about this listing…"
            : "Type your question to AI...");

  return (
    <div className={cn("relative w-full shrink-0", className)}>
      {hasAttached && (
        <div
          className="absolute inset-x-3 -top-3 z-10 flex flex-wrap items-center gap-1.5"
          data-testid="attached-listing-chips"
        >
          {visibleChips.map((listing) => (
            <AttachedListingChip
              key={listing.id}
              listing={listing}
              onRemove={onRemoveAttached}
            />
          ))}
          {overflowCount > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    "inline-flex items-center rounded-full bg-[#E8ECF3] px-2.5 py-1",
                    "text-xs font-medium text-[#494A58]",
                    "hover:bg-[#D8DDE6] focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]",
                  )}
                  aria-label={`${overflowCount} more attached properties`}
                >
                  +{overflowCount} more
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="start"
                side="top"
                className="w-64 rounded-2xl border-[#E8ECF3] p-2 shadow-lg"
              >
                <DropdownMenuLabel className="px-2 py-1.5 text-xs font-medium text-[#747288]">
                  Attached properties
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {attachedListings.map((listing) => (
                  <DropdownMenuItem
                    key={listing.id}
                    className="flex cursor-default items-center gap-2 rounded-full bg-[#E8ECF3]/60 px-2.5 py-1.5 focus:bg-[#E8ECF3]"
                    onSelect={(e) => e.preventDefault()}
                  >
                    <Home className="size-3.5 shrink-0 text-[#747288]" aria-hidden />
                    <span className="min-w-0 flex-1 truncate text-xs font-medium text-[#494A58]" title={listing.title}>
                      {listing.title}
                    </span>
                    {onRemoveAttached && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onRemoveAttached(listing.id);
                        }}
                        className="flex shrink-0 items-center justify-center rounded-full p-0.5 text-[#747288] hover:bg-[#D8DDE6] hover:text-[#141B34]"
                        aria-label={`Remove ${listing.title}`}
                      >
                        <X className="size-3" strokeWidth={2.25} />
                      </button>
                    )}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      )}

      <div
        className={cn(
          "flex flex-col justify-between rounded-2xl bg-white",
          "border transition-colors",
          isStreaming ? "min-h-0 gap-2 p-2" : "min-h-[120px] gap-4 p-4",
          focused || isRecording || isConnecting ? "border-[#979CAE]" : "border-[#D8DDE6]",
          hasAttached && !isStreaming && "pt-6",
        )}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          disabled={disabled || isStreaming}
          placeholder={isStreaming ? "" : resolvedPlaceholder}
          rows={1}
          className={cn(
            "w-full resize-none bg-transparent text-sm font-medium leading-[1.5] text-[#141B34]",
            "placeholder:text-[#747288] focus:outline-none disabled:cursor-not-allowed",
            isStreaming ? "h-0 min-h-0 flex-none overflow-hidden p-0 opacity-0" : "min-h-12 flex-1 disabled:opacity-50",
          )}
          style={isStreaming ? { height: 0, minHeight: 0, overflowY: "hidden" } : { minHeight: MIN_HEIGHT, overflowY: "hidden" }}
          aria-label="Message"
          aria-hidden={isStreaming}
        />

        <div className="flex items-center gap-3">
          {isRecording ? (
            <VoiceWaveform active levels={waveLevels} />
          ) : isStreaming ? (
            <p className="min-w-0 flex-1 truncate text-xs text-[#747288]">Answering…</p>
          ) : (
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
              {suggestions?.map((chip) => (
                <button
                  key={chip.message}
                  type="button"
                  onClick={() => onSuggestionClick?.(chip.message)}
                  className="rounded-full border border-[#E8ECF3] bg-[#F5F7FA] px-3 py-1.5 text-xs font-medium text-[#747288] transition-colors hover:bg-[#EDF0F5] hover:text-[#494A58] focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]"
                >
                  {chip.label}
                </button>
              ))}
            </div>
          )}

          <div className="flex shrink-0 items-center gap-2">
            {isRecording ? (
              <button
                type="button"
                onClick={() => void stopRecording()}
                className="relative flex size-10 items-center justify-center rounded-full focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]"
                aria-label="Stop recording"
              >
                <span
                  className="absolute inset-0 rounded-full border-[1.25px] border-[#141B34]"
                  aria-hidden
                />
                <span
                  className="size-3 rounded-[3px] bg-[#141B34]"
                  aria-hidden
                />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void startRecording()}
                className={cn(
                  "flex size-10 items-center justify-center rounded-3xl",
                  "bg-[rgba(71,85,132,0.1)] text-[#141B34] transition-colors",
                  "hover:bg-[rgba(71,85,132,0.16)] focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]",
                  (disabled || isConnecting) && "opacity-40",
                )}
                aria-label={isConnecting ? "Connecting voice input" : "Start voice input"}
              >
                <Mic className="size-4" strokeWidth={1.75} />
              </button>
            )}

            {isStreaming ? (
              <button
                type="button"
                onClick={() => onStop?.()}
                className={cn(
                  "relative flex size-10 shrink-0 items-center justify-center rounded-full",
                  "focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]",
                )}
                aria-label="Stop generating"
              >
                <span
                  className="absolute inset-0 rounded-full border-[1.25px] border-[#141B34]"
                  aria-hidden
                />
                <span
                  className="size-3 rounded-[3px] bg-[#141B34]"
                  aria-hidden
                />
              </button>
            ) : (
              <button
                type="button"
                onClick={submit}
                disabled={!canSend}
                className={cn(
                  "flex size-10 shrink-0 items-center justify-center rounded-3xl bg-[#1B60F4] text-white transition-colors",
                  "focus:outline-none focus:ring-2 focus:ring-[#E8ECF3]",
                  canSend ? "hover:bg-[#1554d9]" : "opacity-40",
                )}
                aria-label="Send"
              >
                <ArrowUp className="size-4" strokeWidth={2.25} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
