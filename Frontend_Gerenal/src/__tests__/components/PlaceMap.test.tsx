import { beforeEach, describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlaceMap, { type ReplyMap } from "@/components/chat/PlaceMap";
import { StructuredAnswer } from "@/components/chat/StructuredAnswer";
import { usePropertyFocusStore } from "@/store/propertyFocusStore";

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

describe("PlaceMap for a search near stations", () => {
  const search: ReplyMap = {
    pins: [
      { lat: 25.08, lng: 55.14, label: "Marina Gate", detail: "0.8 km to DAMAC Properties Metro Station", kind: "listing", property_id: "101" },
      { lat: 25.07, lng: 55.13, label: "Marina Gate", detail: "0.3 km to DMCC Metro Station", kind: "listing", property_id: "102" },
      { lat: 25.0799, lng: 55.1475, label: "DAMAC Properties Metro Station", detail: "Red Metro line", kind: "metro", line: "red" },
    ],
    lines: [{ line: "tram", name: "Tram line", path: [[25.07, 55.13], [25.08, 55.14]] }],
  };

  it("numbers every listing and shows the id its card carries", () => {
    render(<PlaceMap map={search} />);
    const items = within(screen.getByRole("list", { name: "Places on the map" })).getAllByRole("button");
    expect(items[0]).toHaveTextContent("1Marina Gate101");
    expect(items[1]).toHaveTextContent("2Marina Gate102");
    expect(items[2]).toHaveTextContent("3DAMAC Properties Metro Station");
    expect(screen.getByText("2 listings on the map")).toBeInTheDocument();
  });

  it("names each station's line and each line drawn in the legend", () => {
    render(<PlaceMap map={search} />);
    const legend = within(screen.getByRole("list", { name: "Legend" }));
    expect(legend.getByText("Listing")).toBeInTheDocument();
    expect(legend.getByText("Red line")).toBeInTheDocument();
    expect(legend.getByText("Tram")).toBeInTheDocument();
  });

  beforeEach(() => usePropertyFocusStore.setState({ request: null }));

  it("opens a listing picked on the map in the properties panel", async () => {
    const user = userEvent.setup();
    render(<PlaceMap map={search} />);
    const items = within(screen.getByRole("list", { name: "Places on the map" })).getAllByRole("button");
    await user.click(items[1]);
    expect(usePropertyFocusStore.getState().request?.propertyId).toBe(102);
  });

  it("opens nothing for a station", async () => {
    const user = userEvent.setup();
    render(<PlaceMap map={search} />);
    const items = within(screen.getByRole("list", { name: "Places on the map" })).getAllByRole("button");
    await user.click(items[2]);
    expect(usePropertyFocusStore.getState().request).toBeNull();
  });

  it("hides the map and its list when collapsed, and shows them again", async () => {
    const user = userEvent.setup();
    render(<PlaceMap map={search} />);
    const toggle = screen.getByRole("button", { name: /2 listings on the map/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("list", { name: "Places on the map" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Legend" })).toBeNull();
    await user.click(toggle);
    expect(screen.getByRole("list", { name: "Places on the map" })).toBeVisible();
  });

  it("draws the rail lines under the pins", () => {
    const { container } = render(<PlaceMap map={search} />);
    expect(container.querySelectorAll(".leaflet-overlay-pane path")).toHaveLength(1);
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
