/**
 * OpenAI Realtime translation over WebRTC (browser mic → English transcript).
 *
 * Uses an ephemeral client_secret from Backend; never the long-lived API key.
 * Remote translated audio is ignored — Composer only consumes transcript deltas.
 *
 * Important: when the speaker already uses the target language (English→English),
 * OpenAI may emit silence on ``session.output_transcript`` while
 * ``session.input_transcript`` keeps flowing. Locking onto the first output
 * delta and ignoring input freezes the Composer after a few words.
 */

export const TRANSLATION_CALLS_URL =
  "https://api.openai.com/v1/realtime/translations/calls";

/** How long without output deltas before falling back to input (same-lang silence). */
export const VOICE_OUTPUT_STALL_MS = 1600;

export interface VoiceRealtimeHandlers {
  /**
   * English transcript text for the Composer.
   * ``replaceAll`` replaces the streamed buffer (preferred — dual input/output merge).
   * ``resetStreamed`` clears prior deltas then appends (legacy switch path).
   */
  onTranscriptDelta: (
    delta: string,
    opts?: { resetStreamed?: boolean; replaceAll?: boolean },
  ) => void;
  onError?: (message: string) => void;
  onStarted?: () => void;
  onStopped?: () => void;
}

export interface VoiceRealtimeSession {
  stop: () => Promise<void>;
}

/** Pure helper — merge base typed text with streaming English deltas. */
export function mergeVoiceTranscript(
  baseText: string,
  streamedEnglish: string,
): string {
  const base = baseText.trimEnd();
  const streamed = streamedEnglish.trimStart();
  if (!base) return streamed;
  if (!streamed) return base;
  const needsSpace = !/\s$/.test(base) && !/^\s/.test(streamed);
  return needsSpace ? `${base} ${streamed}` : `${base}${streamed}`;
}

/**
 * Choose which transcript buffer fills the Composer.
 *
 * OpenAI may silence ``output_transcript`` when source≈target (English→English)
 * while ``input_transcript`` keeps growing. Prefer the Whisper source when it is
 * Latin and ahead; prefer translated ``output`` for non-Latin sources (Arabic).
 */
export function pickComposerVoiceText(
  inputAcc: string,
  outputAcc: string,
  opts: { lastOutputAtMs: number; nowMs: number; stallMs?: number },
): string {
  const stallMs = opts.stallMs ?? VOICE_OUTPUT_STALL_MS;
  const input = inputAcc;
  const output = outputAcc;
  if (!output.trim()) return input;
  if (!input.trim()) return output;

  // Arabic / CJK / etc. — Composer needs the English translation.
  if (!looksLikeLatinScript(input)) return output;

  // Latin source (usually English dictation): keep Whisper when it is ahead of
  // a silent/lagging translation stream so the UI does not freeze on a few words.
  if (input.trim().length > output.trim().length) return input;

  const outputStalled = opts.nowMs - opts.lastOutputAtMs >= stallMs;
  if (!outputStalled) return output;
  return input.trim() ? input : output;
}

/** True when most letters are Latin — used to detect English→English silence. */
export function looksLikeLatinScript(text: string): boolean {
  const letters = text.replace(
    /[^a-zA-Z\u00C0-\u024F\u0600-\u06FF\u0750-\u077F\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF\u0900-\u097F]/g,
    "",
  );
  if (!letters) return true;
  const latin = (letters.match(/[a-zA-Z\u00C0-\u024F]/g) || []).length;
  return latin / letters.length >= 0.65;
}

/** Transcript kind for English Composer fill. */
export type VoiceTranscriptKind = "output" | "input";

export interface VoiceTranscriptPiece {
  kind: VoiceTranscriptKind;
  text: string;
}

/**
 * Incremental transcript deltas for translation sessions.
 * Prefer ``output`` (target language). ``input`` is source-language and is
 * only useful as English fallback when target==source (no output deltas).
 */
export function classifyTranscriptDelta(
  event: Record<string, unknown>,
): VoiceTranscriptPiece | null {
  const type = typeof event.type === "string" ? event.type : "";
  if (!type.endsWith(".delta")) return null;
  const text =
    typeof event.delta === "string" && event.delta
      ? event.delta
      : typeof event.transcript === "string" && event.transcript
        ? event.transcript
        : null;
  if (!text) return null;
  if (type.includes("output_transcript")) return { kind: "output", text };
  if (
    type.includes("input_transcript") ||
    type.includes("input_audio_transcription")
  ) {
    return { kind: "input", text };
  }
  return null;
}

/** Incremental English deltas only — never full completed transcripts (avoids double-append). */
export function extractTranscriptDelta(event: Record<string, unknown>): string | null {
  const piece = classifyTranscriptDelta(event);
  // Prefer translated/output; keep legacy helper behavior for unit tests.
  if (!piece) return null;
  if (piece.kind === "output") return piece.text;
  if (
    typeof event.type === "string" &&
    (event.type.includes("input_transcript") ||
      event.type.includes("input_audio_transcription"))
  ) {
    return piece.text;
  }
  return null;
}

async function waitForIceGatheringComplete(
  pc: RTCPeerConnection,
  timeoutMs = 4000,
): Promise<void> {
  if (pc.iceGatheringState === "complete") return;
  await new Promise<void>((resolve) => {
    const done = () => {
      pc.removeEventListener("icegatheringstatechange", onChange);
      window.clearTimeout(timer);
      resolve();
    };
    const onChange = () => {
      if (pc.iceGatheringState === "complete") done();
    };
    const timer = window.setTimeout(done, timeoutMs);
    pc.addEventListener("icegatheringstatechange", onChange);
  });
}

/**
 * Start mic capture + WebRTC peer connection to OpenAI Realtime translation.
 */
export async function startVoiceRealtime(
  clientSecret: string,
  handlers: VoiceRealtimeHandlers,
): Promise<VoiceRealtimeSession> {
  const secret = clientSecret.trim();
  if (!secret) {
    throw new Error("Missing voice session secret.");
  }

  let pc: RTCPeerConnection | null = null;
  let mediaStream: MediaStream | null = null;
  let dataChannel: RTCDataChannel | null = null;
  let remoteAudio: HTMLAudioElement | null = null;
  let stopped = false;
  let inputAcc = "";
  let outputAcc = "";
  let lastOutputAtMs = 0;

  const publishComposerText = () => {
    const text = pickComposerVoiceText(inputAcc, outputAcc, {
      lastOutputAtMs,
      nowMs: Date.now(),
    });
    handlers.onTranscriptDelta(text, { replaceAll: true });
  };

  const cleanup = () => {
    if (dataChannel) {
      try {
        dataChannel.close();
      } catch {
        /* already closed */
      }
      dataChannel = null;
    }
    if (mediaStream) {
      for (const track of mediaStream.getTracks()) {
        try {
          track.stop();
        } catch {
          /* ignore */
        }
      }
      mediaStream = null;
    }
    if (remoteAudio) {
      try {
        remoteAudio.pause();
        remoteAudio.srcObject = null;
      } catch {
        /* ignore */
      }
      remoteAudio = null;
    }
    if (pc) {
      try {
        pc.close();
      } catch {
        /* ignore */
      }
      pc = null;
    }
  };

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        channelCount: 1,
      },
      video: false,
    });

    pc = new RTCPeerConnection();

    pc.onconnectionstatechange = () => {
      if (stopped || !pc) return;
      if (pc.connectionState === "failed") {
        handlers.onError?.("Voice connection lost.");
      }
    };

    // Attach remote track muted — OpenAI WebRTC examples require the media
    // path; we keep volume at 0 so Composer stays text-only.
    remoteAudio = new Audio();
    remoteAudio.autoplay = true;
    remoteAudio.volume = 0;
    pc.ontrack = (ev) => {
      if (!remoteAudio) return;
      remoteAudio.srcObject = ev.streams[0] ?? null;
    };

    for (const track of mediaStream.getAudioTracks()) {
      pc.addTrack(track, mediaStream);
    }

    dataChannel = pc.createDataChannel("oai-events");
    dataChannel.addEventListener("open", () => {
      // Belt-and-suspenders: mint already sets transcription; re-assert for WebRTC.
      try {
        dataChannel?.send(
          JSON.stringify({
            type: "session.update",
            session: {
              audio: {
                output: { language: "en" },
                input: {
                  transcription: { model: "gpt-realtime-whisper" },
                },
              },
            },
          }),
        );
      } catch {
        /* ignore */
      }
    });
    dataChannel.addEventListener("close", () => {
      if (!stopped) handlers.onError?.("Voice session ended unexpectedly.");
    });
    dataChannel.addEventListener("message", (ev) => {
      if (stopped) return;
      let event: Record<string, unknown>;
      try {
        event = JSON.parse(String(ev.data)) as Record<string, unknown>;
      } catch {
        return;
      }
      if (event.type === "error") {
        const err = event.error;
        const msg =
          err && typeof err === "object" && typeof (err as { message?: unknown }).message === "string"
            ? (err as { message: string }).message
            : "Voice session error.";
        handlers.onError?.(msg);
        return;
      }
      const piece = classifyTranscriptDelta(event);
      if (!piece) return;
      if (piece.kind === "output") {
        outputAcc += piece.text;
        lastOutputAtMs = Date.now();
        publishComposerText();
        return;
      }
      inputAcc += piece.text;
      publishComposerText();
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitForIceGatheringComplete(pc);
    const localSdp = pc.localDescription?.sdp ?? offer.sdp ?? "";

    const sdpResponse = await fetch(TRANSLATION_CALLS_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${secret}`,
        "Content-Type": "application/sdp",
      },
      body: localSdp,
    });

    if (!sdpResponse.ok) {
      cleanup();
      throw new Error("Could not connect the voice session.");
    }

    const answerSdp = await sdpResponse.text();
    await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
    handlers.onStarted?.();
  } catch (err) {
    cleanup();
    const name = err instanceof DOMException ? err.name : "";
    if (name === "NotAllowedError" || name === "PermissionDeniedError") {
      throw new Error("Microphone permission is required for voice input.");
    }
    if (name === "NotFoundError") {
      throw new Error("No microphone was found.");
    }
    if (err instanceof Error && err.message) throw err;
    throw new Error("Couldn’t start voice input.");
  }

  return {
    stop: async () => {
      if (stopped) return;
      stopped = true;
      // Ask translation session to flush remaining transcript before teardown.
      try {
        if (dataChannel && dataChannel.readyState === "open") {
          dataChannel.send(JSON.stringify({ type: "session.close" }));
        }
      } catch {
        /* ignore */
      }
      // Brief grace so late transcript deltas can arrive before teardown.
      await new Promise<void>((resolve) => {
        window.setTimeout(resolve, 350);
      });
      cleanup();
      handlers.onStopped?.();
    },
  };
}
