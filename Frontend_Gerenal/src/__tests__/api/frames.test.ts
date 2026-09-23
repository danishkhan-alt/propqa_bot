import { describe, expect, it } from "vitest";
import { legacyEventToFrames } from "@/api/frames";
import { describeStep, STEP_LABELS } from "@/lib/pipelineLabels";

describe("legacyEventToFrames", () => {
  it("passes through parallel on step frames", () => {
    const frames = legacyEventToFrames({
      step: "search_domain",
      status: "ok",
      ms: 12,
      parallel: true,
      payload: { domain: "market_intel" },
    });
    expect(frames).toEqual([
      {
        type: "step",
        step: "search_domain",
        status: "ok",
        ms: 12,
        parallel: true,
        payload: { domain: "market_intel" },
      },
    ]);
  });

  it("omits parallel when the flag is not true", () => {
    const frames = legacyEventToFrames({
      step: "coverage_check",
      status: "running",
    });
    expect(frames[0]).toMatchObject({
      type: "step",
      step: "coverage_check",
      parallel: undefined,
    });
  });

  it("maps type=cancelled before done", () => {
    const frames = legacyEventToFrames({
      type: "cancelled",
      run_id: "abc",
    });
    expect(frames).toEqual([{ type: "cancelled", run_id: "abc" }]);
  });

  it("maps done+metadata.cancelled to cancelled", () => {
    const frames = legacyEventToFrames({
      type: "done",
      metadata: { cancelled: true },
      run_id: "r1",
    });
    expect(frames).toEqual([{ type: "cancelled", run_id: "r1" }]);
  });

  it("maps legacy cancelled+done true to cancelled", () => {
    const frames = legacyEventToFrames({ cancelled: true, done: true });
    expect(frames[0]?.type).toBe("cancelled");
  });
});

describe("pipelineLabels coverage/verify steps", () => {
  it("maps coverage_check and verify_gate to Verifying", () => {
    expect(STEP_LABELS.coverage_check).toBe("Verifying");
    expect(STEP_LABELS.verify_gate).toBe("Verifying");
    expect(
      describeStep({
        type: "step",
        step: "coverage_check",
        payload: { missing: ["communities_intel"] },
      }),
    ).toBe("Something was missing — fetching the rest");
    expect(describeStep({ type: "step", step: "verify_gate" })).toBe(
      "Checking the answer against the data",
    );
  });

  it("maps search_domain ids to product-safe labels (not snake_case or Agent)", () => {
    expect(
      describeStep({
        type: "step",
        step: "search_domain",
        payload: { domain: "market_intel" },
      }),
    ).toBe("Checking market stats");
    expect(
      describeStep({
        type: "step",
        step: "search_domain",
        payload: { domain: "property_search" },
      }),
    ).toBe("Searching listings");
    expect(
      describeStep({
        type: "step",
        step: "search_domain",
        payload: { domain: "location_intel" },
      }),
    ).toBe("Checking areas");
    expect(
      describeStep({
        type: "step",
        step: "search_domain",
        payload: { domain: "communities_intel" },
      }),
    ).toBe("Checking community guides");
    expect(
      describeStep({
        type: "step",
        step: "search_domain",
        payload: { domain: "offplan_projects" },
      }),
    ).toBe("Checking off-plan projects");
    expect(
      describeStep({
        type: "step",
        step: "search_domain",
        payload: { domain: "rta_intel" },
      }),
    ).toBe("Checking transport");
    expect(
      describeStep({
        type: "step",
        step: "search_domain",
        payload: { domain: "unknown_domain" },
      }),
    ).toBe("Searching listings and guides");
    expect(
      describeStep({ type: "step", step: "propqa_core" }),
    ).toBe("Searching listings and guides");
    expect(STEP_LABELS.lead_offer_emitted).toBe("Contacts");
  });
});
