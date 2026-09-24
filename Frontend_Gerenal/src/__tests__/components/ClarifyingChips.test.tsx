import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClarifyingChips } from "@/components/chat/ClarifyingChips";

const questions = [
  {
    id: "purpose",
    label: "Living in it, investing, or both?",
    type: "single_select" as const,
    options: [
      { id: "live", label: "Live in it" },
      { id: "invest", label: "Invest" },
    ],
  },
  {
    id: "budget_range",
    label: "Roughly what budget, in AED?",
    type: "single_select" as const,
    options: [
      { id: "under_1m", label: "Under 1M" },
      { id: "1m_2m", label: "1M–2M" },
    ],
  },
];

describe("ClarifyingChips", () => {
  it("walks questions one at a time and submits the answers", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(
      <ClarifyingChips questions={questions} ctaLabel="Compare these areas" onSubmit={onSubmit} />,
    );

    expect(screen.getByRole("progressbar")).toHaveTextContent("Question 1 of 2");
    expect(screen.getByRole("radio", { name: "Live in it" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "Under 1M", hidden: true })).not.toBeVisible();

    await user.click(screen.getByRole("radio", { name: "Live in it" }));
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(screen.getByRole("progressbar")).toHaveTextContent("Question 2 of 2");
    expect(screen.getByRole("radio", { name: "Under 1M" })).toBeVisible();
    await user.click(screen.getByRole("radio", { name: "Under 1M" }));
    await user.click(screen.getByRole("button", { name: "Compare these areas" }));

    expect(onSubmit).toHaveBeenCalledWith({ purpose: "live", budget_range: "under_1m" });
  });
});
