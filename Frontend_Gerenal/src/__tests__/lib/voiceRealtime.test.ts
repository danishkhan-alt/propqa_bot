import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("@/store/authStore", () => ({
  withAuthHeaders: (base: Record<string, string> = {}) => base,
  getAuthUserId: () => "",
}));

import { createVoiceSession, VoiceSessionApiError } from "@/api/voiceSessionApi";
import {
  classifyTranscriptDelta,
  extractTranscriptDelta,
  mergeVoiceTranscript,
  pickComposerVoiceText,
  looksLikeLatinScript,
} from "@/lib/voiceRealtime";

describe("mergeVoiceTranscript", () => {
  it("returns streamed text when base is empty", () => {
    expect(mergeVoiceTranscript("", "Hello")).toBe("Hello");
    expect(mergeVoiceTranscript("   ", "Hello")).toBe("Hello");
  });

  it("returns base when streamed is empty", () => {
    expect(mergeVoiceTranscript("Typed", "")).toBe("Typed");
  });

  it("joins base and streamed with a single space when needed", () => {
    expect(mergeVoiceTranscript("Find flats", "in Dubai Marina")).toBe(
      "Find flats in Dubai Marina",
    );
  });

  it("does not double-space when base already ends with whitespace", () => {
    expect(mergeVoiceTranscript("Find flats ", "in Dubai")).toBe("Find flats in Dubai");
  });
});

describe("pickComposerVoiceText", () => {
  it("uses input when output is empty (English→English)", () => {
    expect(
      pickComposerVoiceText("two bedroom in Marina", "", {
        lastOutputAtMs: 0,
        nowMs: 5000,
      }),
    ).toBe("two bedroom in Marina");
  });

  it("prefers longer Latin input over a short/silent translation", () => {
    expect(
      pickComposerVoiceText(
        "two bedroom apartment in Dubai Marina please",
        "two bed",
        { lastOutputAtMs: 9000, nowMs: 9100, stallMs: 1600 },
      ),
    ).toBe("two bedroom apartment in Dubai Marina please");
  });

  it("prefers live output when it is ahead of Latin input", () => {
    expect(
      pickComposerVoiceText("hola", "Hello I want an apartment in Marina", {
        lastOutputAtMs: 9000,
        nowMs: 9500,
        stallMs: 1600,
      }),
    ).toBe("Hello I want an apartment in Marina");
  });

  it("keeps translation output for non-Latin (Arabic) source", () => {
    expect(
      pickComposerVoiceText("شقة غرفتين في المارينا من فضلك", "two bedroom", {
        lastOutputAtMs: 1000,
        nowMs: 5000,
        stallMs: 1600,
      }),
    ).toBe("two bedroom");
  });
});

describe("looksLikeLatinScript", () => {
  it("detects English vs Arabic", () => {
    expect(looksLikeLatinScript("Find flats in Dubai")).toBe(true);
    expect(looksLikeLatinScript("شقة في دبي")).toBe(false);
  });
});

describe("classifyTranscriptDelta", () => {
  it("classifies output vs input transcript deltas", () => {
    expect(
      classifyTranscriptDelta({
        type: "session.output_transcript.delta",
        delta: "Hello",
      }),
    ).toEqual({ kind: "output", text: "Hello" });
    expect(
      classifyTranscriptDelta({
        type: "session.input_transcript.delta",
        delta: "Hola",
      }),
    ).toEqual({ kind: "input", text: "Hola" });
  });
});

describe("extractTranscriptDelta", () => {
  it("reads session.output_transcript.delta", () => {
    expect(
      extractTranscriptDelta({
        type: "session.output_transcript.delta",
        delta: "Hello",
      }),
    ).toBe("Hello");
  });

  it("reads session.input_transcript.delta (same-language fallback)", () => {
    expect(
      extractTranscriptDelta({
        type: "session.input_transcript.delta",
        delta: "Hello",
      }),
    ).toBe("Hello");
  });

  it("ignores completed / done full transcripts", () => {
    expect(
      extractTranscriptDelta({
        type: "session.output_transcript.done",
        transcript: "Hello world",
      }),
    ).toBeNull();
  });

  it("returns null for unrelated events", () => {
    expect(extractTranscriptDelta({ type: "session.created" })).toBeNull();
  });
});

describe("createVoiceSession", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("POSTs session_id and returns client_secret", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ client_secret: "ek_abc", expires_at: 99 }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    const result = await createVoiceSession({ sessionId: "sess-1" });

    expect(result).toEqual({ client_secret: "ek_abc", expires_at: 99 });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/realtime/voice-session",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ session_id: "sess-1" }),
      }),
    );
  });

  it("throws VoiceSessionApiError on 503", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({
        detail: { code: "voice_unavailable", message: "Voice is unavailable." },
      }),
    }) as unknown as typeof fetch;

    await expect(createVoiceSession({ sessionId: "s" })).rejects.toBeInstanceOf(
      VoiceSessionApiError,
    );
  });
});
