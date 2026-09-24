import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StructuredAnswer, type StructuredReply } from "@/components/chat/StructuredAnswer";
import { ListingSummary } from "@/components/chat/ListingSummary";

const reply: StructuredReply = {
  intro_text: "Three homes fit, from **AED 1.2M**.",
  question: {
    id: "goal",
    prompt: "Is this a home for you, or an investment?",
    options: [
      { id: "live", label: "A home for me", reply: "It's a home for me to live in." },
      { id: "invest", label: "An investment", reply: "I'm buying it as an investment." },
    ],
  },
  suggested_followups: ["Show ready homes instead"],
  data_source_note: "live asking prices",
};

describe("StructuredAnswer", () => {
  it("renders the answer as markdown", () => {
    render(<StructuredAnswer reply={reply} interactive />);
    expect(screen.getByText("AED 1.2M").tagName).toBe("STRONG");
    expect(screen.getByText("Source: live asking prices")).toBeInTheDocument();
  });

  it("answers the question with one tap", async () => {
    const onQuickReply = vi.fn();
    const user = userEvent.setup();
    render(<StructuredAnswer reply={reply} interactive onQuickReply={onQuickReply} />);

    await user.click(screen.getByRole("button", { name: "An investment" }));

    expect(onQuickReply).toHaveBeenCalledTimes(1);
    const [question, option] = onQuickReply.mock.calls[0];
    expect(question.id).toBe("goal");
    expect(option.reply).toBe("I'm buying it as an investment.");
  });

  it("sends a follow-up as the user would say it", async () => {
    const onFollowup = vi.fn();
    const user = userEvent.setup();
    render(<StructuredAnswer reply={reply} interactive onFollowup={onFollowup} />);

    await user.click(screen.getByRole("button", { name: /Show ready homes instead/ }));

    expect(onFollowup).toHaveBeenCalledWith("Show ready homes instead");
  });

  it("keeps an older reply readable but inert, showing the answer given", () => {
    render(
      <StructuredAnswer
        reply={reply}
        interactive={false}
        answeredId="invest"
        onQuickReply={vi.fn()}
        onFollowup={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "A home for me" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "An investment" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: /Show ready homes instead/ })).not.toBeInTheDocument();
  });
});

describe("ListingSummary", () => {
  it("summarises the result set and opens the panel", async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(
      <ListingSummary
        cards={[
          { id: 1, price_min: "1200000", image_url: "https://cdn.test/1.jpg" },
          { id: 2, price_min: "1438888" },
        ]}
        onOpen={onOpen}
      />,
    );

    expect(screen.getByText("2 properties matched")).toBeInTheDocument();
    expect(screen.getByText("AED 1.2M – 1.44M")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /View 2 properties/ }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});
