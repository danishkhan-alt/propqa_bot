import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlaceMap, { type ReplyMap } from "@/components/chat/PlaceMap";
import { StructuredAnswer } from "@/components/chat/StructuredAnswer";

const map: ReplyMap = {
  pins: [
    { lat: 25.2012, lng: 55.3471, label: "Harbour Gate Tower 2", detail: "", kind: "listing" },
    { lat: 25.21937, lng: 55.33869, label: "Creek Metro Station", detail: "Green Metro line · 1.5 km away", kind: "metro" },
    { lat: 25.2003, lng: 55.348, label: "<b>Creek Park</b>", detail: "0.1 km away", kind: "nearby" },
  ],
  hidden_pins: 2,
};

describe("PlaceMap", () => {
  it("lists every pin, numbering all but the listing", () => {
    render(<PlaceMap map={map} />);
    const list = screen.getByRole("list", { name: "Places on the map" });
    const items = within(list).getAllByRole("button");
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveTextContent("1Creek Metro Station");
    expect(items[1]).toHaveTextContent("Green Metro line · 1.5 km away");
    expect(items[2]).toHaveTextContent("2");
    expect(screen.getByText("3 places on the map")).toBeInTheDocument();
    expect(screen.getByText("+2 more not shown")).toBeInTheDocument();
  });

  it("shows a legend only when pins differ in kind", () => {
    const { rerender } = render(<PlaceMap map={map} />);
    expect(within(screen.getByRole("list", { name: "Legend" })).getByText("Metro")).toBeInTheDocument();
    rerender(<PlaceMap map={{ pins: [map.pins[1]] }} />);
    expect(screen.queryByRole("list", { name: "Legend" })).toBeNull();
    expect(screen.getByText("On the map")).toBeInTheDocument();
  });

  it("keeps a label from the data as text, never markup", () => {
    const { container } = render(<PlaceMap map={map} />);
    expect(screen.getByText("<b>Creek Park</b>")).toBeInTheDocument();
    expect(container.querySelector(".leaflet-container b")).toBeNull();
  });

  it("marks the place picked in the list", async () => {
    const user = userEvent.setup();
    render(<PlaceMap map={map} />);
    const metro = screen.getByRole("button", { name: /Creek Metro Station/ });
    await user.click(metro);
    expect(metro).toHaveAttribute("aria-pressed", "true");
  });
});

describe("StructuredAnswer map", () => {
  it("loads the map only for a reply that has pins", async () => {
    const { rerender } = render(<StructuredAnswer reply={{ intro_text: "Two stations.", map }} interactive={false} />);
    expect(await screen.findByRole("list", { name: "Places on the map" })).toBeInTheDocument();
    rerender(<StructuredAnswer reply={{ intro_text: "Two stations.", map: null }} interactive={false} />);
    expect(screen.queryByRole("list", { name: "Places on the map" })).toBeNull();
  });
});
