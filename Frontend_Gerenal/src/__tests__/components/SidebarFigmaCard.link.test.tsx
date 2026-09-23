import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PropertyCards } from "@/components/chat/PropertyCards";

vi.mock("@/hooks/usePropertyContact", () => ({
  usePropertyContact: () => ({ fetchContact: vi.fn() }),
}));

describe("SidebarFigmaCard listing link", () => {
  it("wraps the details column in a PropQA listing tab link", () => {
    render(
      <PropertyCards
        layout="sidebar"
        cards={[
          {
            id: 21143,
            slug: "villas-for-sale-dubai-dubai-south-residential-district-south-bay-south-bay-1-21143",
            title: "Villa | South Bay 1, south Bay, Residential District, Dubai South, Dubai | for Sale",
            address: "South Bay 1, South Bay, Residential District, Dubai South, Dubai",
            price_max: 5150000,
            rooms: 5,
            baths: 6,
            area: 9357,
            type: "Villa",
          },
        ]}
      />,
    );

    const links = screen.getAllByRole("link", { name: /open .* on propqa/i });
    expect(links.length).toBeGreaterThanOrEqual(1);
    for (const link of links) {
      expect(link).toHaveAttribute(
        "href",
        "https://propqa.ai/property/villas-for-sale-dubai-dubai-south-residential-district-south-bay-south-bay-1-21143",
      );
      expect(link).toHaveAttribute("target", "_blank");
    }
    expect(screen.getByText("5,150,000")).toBeInTheDocument();
  });
});
