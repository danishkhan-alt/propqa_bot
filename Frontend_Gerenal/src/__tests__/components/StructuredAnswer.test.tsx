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

describe("StructuredAnswer blocks", () => {
  it("shows key figures as tiles", () => {
    render(
      <StructuredAnswer
        reply={{
          intro_text: "Prices in Dubai Marina.",
          figures: {
            layout: "stats",
            tiles: [
              { label: "Average sale price", value: "AED 4.33M" },
              { label: "Sales", value: "3,216" },
            ],
          },
        }}
        interactive
      />,
    );
    expect(screen.getByText("Average sale price")).toBeInTheDocument();
    expect(screen.getByText("AED 4.33M")).toBeInTheDocument();
  });

  it("compares rows in a table with a header per figure", () => {
    render(
      <StructuredAnswer
        reply={{
          figures: {
            layout: "table",
            headers: ["Area", "Average rent"],
            rows: [
              ["JVC", "AED 60,000"],
              ["JLT", "AED 75,000"],
            ],
            hidden_rows: 3,
          },
        }}
        interactive
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Average rent" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "AED 75,000" })).toBeInTheDocument();
    expect(screen.getByText("+3 more not shown")).toBeInTheDocument();
  });

  it("shows a change with its direction and a repeated period once, under the table", () => {
    render(
      <StructuredAnswer
        reply={{
          figures: {
            layout: "table",
            headers: ["Bedrooms", "Median price", "Yearly change"],
            rows: [
              ["1-bed", "AED 1.07M", "▲ 9.9%"],
              ["2-bed", "AED 1.55M", "▼ 1.2%"],
            ],
            caption: ["As of: May 2026"],
          },
        }}
        interactive
      />,
    );
    expect(screen.getByRole("cell", { name: /^up\s*9\.9%$/ })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: /^down\s*1\.2%$/ })).toBeInTheDocument();
    expect(screen.getByText("As of: May 2026")).toBeInTheDocument();
  });

  it("draws a line per series with a legend and the latest values", () => {
    render(
      <StructuredAnswer
        reply={{
          figures: {
            layout: "line",
            title: "",
            labels: ["2024", "2025", "2026"],
            series: [
              { name: "Apartments", points: [{ value: 100, display: "100" }, { value: 110, display: "110" }, { value: 120, display: "120" }] },
              { name: "Villas", points: [{ value: 100, display: "100" }, { value: null, display: "" }, { value: 140, display: "140" }] },
            ],
          },
        }}
        interactive
      />,
    );
    expect(screen.getByRole("list", { name: "Series" })).toHaveTextContent("ApartmentsVillas");
    expect(screen.getByRole("img", { name: "Apartments, Villas, 2024 to 2026" })).toBeInTheDocument();
    expect(screen.getByText("Latest (2026): Apartments 120 · Villas 140")).toBeInTheDocument();
  });

  it("draws a bar per row, labelled with its value", () => {
    render(
      <StructuredAnswer
        reply={{
          figures: {
            layout: "bar",
            title: "Sales",
            bars: [
              { label: "2023", value: 120, display: "120" },
              { label: "2024", value: 180, display: "180" },
            ],
          },
        }}
        interactive
      />,
    );
    expect(screen.getByText("Sales")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("numbers the steps of an explainer", () => {
    render(
      <StructuredAnswer
        reply={{
          explainer: { kind: "steps", title: "Buying off-plan", points: ["Reserve the unit", "Sign the SPA"] },
        }}
        interactive
      />,
    );
    expect(screen.getByRole("heading", { name: "Buying off-plan" })).toBeInTheDocument();
    const steps = screen.getAllByRole("listitem");
    expect(steps[1]).toHaveTextContent("2Sign the SPA");
  });

  it("splits pros and cautions", () => {
    render(
      <StructuredAnswer
        reply={{ explainer: { kind: "pros_cons", points: ["Lower entry price"], cautions: ["Handover risk"] } }}
        interactive
      />,
    );
    expect(screen.getByRole("list", { name: "Upsides" })).toHaveTextContent("Lower entry price");
    expect(screen.getByRole("list", { name: "Watch out for" })).toHaveTextContent("Handover risk");
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
