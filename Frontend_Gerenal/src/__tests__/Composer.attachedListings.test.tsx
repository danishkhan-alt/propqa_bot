/**
 * Composer attached-listing chips + listing FAQ suggestion wiring.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Composer } from "@/components/chat/Composer";
import {
  LISTING_FAQ_SUGGESTION_CHIPS,
  MAX_ATTACHED_PROPERTY_IDS,
  VISIBLE_ATTACHED_CHIP_COUNT,
  type AttachedListing,
} from "@/lib/followUpSuggestions";

function makeListings(n: number): AttachedListing[] {
  return Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    title: `Listing ${i + 1} Premium Villa`,
  }));
}

describe("Composer attached listing chips", () => {
  it("renders visible chips and +N more overflow", () => {
    const listings = makeListings(5);
    const onRemove = vi.fn();
    render(
      <Composer
        onSend={vi.fn()}
        attachedListings={listings}
        onRemoveAttached={onRemove}
        suggestions={LISTING_FAQ_SUGGESTION_CHIPS}
      />,
    );
    expect(screen.getByTestId("attached-listing-chips")).toBeInTheDocument();
    expect(screen.getByText("Listing 1 Premium Villa")).toBeInTheDocument();
    expect(screen.getByText(`+${5 - VISIBLE_ATTACHED_CHIP_COUNT} more`)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask about this listing…")).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
  });

  it("calls onRemoveAttached when chip X is clicked while disabled", () => {
    const onRemove = vi.fn();
    render(
      <Composer
        disabled
        onSend={vi.fn()}
        attachedListings={makeListings(1)}
        onRemoveAttached={onRemove}
      />,
    );
    fireEvent.click(screen.getByLabelText(/Remove Listing 1/i));
    expect(onRemove).toHaveBeenCalledWith(1);
  });

  it("does not show chips when empty", () => {
    render(<Composer onSend={vi.fn()} attachedListings={[]} />);
    expect(screen.queryByTestId("attached-listing-chips")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Type your question to AI...")).toBeInTheDocument();
  });
});

describe("attached listing cap constant", () => {
  it("caps at 8", () => {
    expect(MAX_ATTACHED_PROPERTY_IDS).toBe(8);
    expect(VISIBLE_ATTACHED_CHIP_COUNT).toBe(3);
  });
});
