import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CardsPanel, type CardGroup } from "@/components/chat/CardsPanel";
import { usePropertyFocusStore } from "@/store/propertyFocusStore";

vi.mock("@/hooks/usePropertyContact", () => ({
  usePropertyContact: () => ({ fetchContact: vi.fn() }),
}));

const card = (id: number) => ({ id, title: `Listing ${id}`, price_max: 2_000_000 + id, rooms: 2 });

const groups: CardGroup[] = [
  { messageId: "older", userQuery: "Villas in Arabian Ranches", cards: [card(1), card(2)] },
  { messageId: "latest", userQuery: "Golden Visa homes", cards: [card(10), card(11), card(12), card(13), card(14)] },
];

describe("CardsPanel opening a listing picked elsewhere", () => {
  beforeEach(() => {
    usePropertyFocusStore.setState({ request: null });
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("turns to the page holding the listing, scrolls to it, and outlines it", () => {
    const { container } = render(<CardsPanel groups={groups} />);
    expect(container.querySelector('[data-property-id="14"]')).toBeNull();

    act(() => usePropertyFocusStore.getState().focusProperty(14));

    const target = container.querySelector('[data-property-id="14"]');
    expect(target).not.toBeNull();
    expect(target).toHaveClass("ring-2");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("expands a collapsed older search to show its listing", () => {
    const { container } = render(<CardsPanel groups={groups} />);
    expect(container.querySelector('[data-property-id="2"]')).toBeNull();

    act(() => usePropertyFocusStore.getState().focusProperty(2));

    expect(container.querySelector('[data-property-id="2"]')).toHaveClass("ring-2");
  });
});
