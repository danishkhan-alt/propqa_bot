import { useEffect, useId, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { ChevronDown, MapPin } from "lucide-react";
import { cn } from "@/lib/utils";
import { usePropertyFocusStore } from "@/store/propertyFocusStore";

export type MapPinKind = "listing" | "metro" | "tram" | "nearby" | "place";
export type RailLineKey = "red" | "green" | "tram" | "";

export interface ReplyMapPin {
  lat: number;
  lng: number;
  label: string;
  detail?: string;
  kind: MapPinKind | string;
  /** A station's rail line, which colors its pin. */
  line?: RailLineKey | string;
  /** Ties a listing pin to its photo card. */
  property_id?: string;
}

export interface ReplyMapLine {
  line: RailLineKey | string;
  name: string;
  /** [lat, lng] points along the track. */
  path: [number, number][];
}

export interface ReplyMap {
  pins: ReplyMapPin[];
  hidden_pins?: number;
  lines?: ReplyMapLine[];
}

// OpenStreetMap's own tiles need no key but are meant for light use; heavy traffic belongs
// on a keyed provider (MapTiler, Stadia, Mapbox), which only changes this constant.
// index.css mutes them so the pins stay the loudest thing on the map.
const TILES = {
  url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};

const LINE_STYLE: Record<Exclude<RailLineKey, "">, { color: string; label: string }> = {
  red: { color: "#D92D20", label: "Red line" },
  green: { color: "#15803D", label: "Green line" },
  tram: { color: "#0E7490", label: "Tram" },
};

const KIND_STYLE: Record<MapPinKind, { color: string; label: string }> = {
  listing: { color: "#101527", label: "Listing" },
  metro: { color: "#D92D20", label: "Metro" },
  tram: LINE_STYLE.tram,
  nearby: { color: "#C2410C", label: "Nearby" },
  place: { color: "#1D4ED8", label: "Place" },
};

const SINGLE_PIN_ZOOM = 15;
const MAX_FIT_ZOOM = 16;

/** A station takes its line's color and name; everything else is styled by its kind. */
function styleFor(pin: Pick<ReplyMapPin, "kind" | "line">) {
  if ((pin.kind === "metro" || pin.kind === "tram") && pin.line && pin.line in LINE_STYLE) {
    return LINE_STYLE[pin.line as keyof typeof LINE_STYLE];
  }
  return KIND_STYLE[pin.kind as MapPinKind] ?? KIND_STYLE.place;
}

/** Each pin's number in the list, or 0 for a lone listing, which shows a house instead. */
function pinNumbers(pins: ReplyMapPin[]): number[] {
  const loneListing = pins.filter((pin) => pin.kind === "listing").length === 1;
  let next = 0;
  return pins.map((pin) => (loneListing && pin.kind === "listing" ? 0 : ++next));
}

const HOUSE_PATH = "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z";

/** A numbered marker. Listings are larger and dark, so they read as what the search found. */
function markerIcon(pin: ReplyMapPin, number: number, active: boolean): L.DivIcon {
  const { color } = styleFor(pin);
  const size = pin.kind === "listing" ? 28 : 22;
  const glyph =
    number === 0
      ? `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="${HOUSE_PATH}"/></svg>`
      : String(number);
  return L.divIcon({
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    tooltipAnchor: [0, -size / 2],
    html: `<span class="propqa-pin${active ? " propqa-pin--active" : ""}" style="--pin:${color};width:${size}px;height:${size}px">${glyph}</span>`,
  });
}

/** The listing a pin stands for, when its card can be opened in the properties panel. */
function listingId(pin: ReplyMapPin): number | null {
  if (pin.kind !== "listing" || !pin.property_id) return null;
  const id = Number(pin.property_id);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** Tooltip content built from text nodes: labels come from the data, never as markup. */
function tooltipContent(pin: ReplyMapPin): HTMLElement {
  const box = document.createElement("div");
  const title = document.createElement("p");
  title.className = "propqa-pin-tip__title";
  title.dir = "auto";
  title.textContent = pin.label;
  box.appendChild(title);
  if (pin.detail) {
    const detail = document.createElement("p");
    detail.className = "propqa-pin-tip__detail";
    detail.textContent = pin.detail;
    box.appendChild(detail);
  }
  if (listingId(pin) !== null) {
    const hint = document.createElement("p");
    hint.className = "propqa-pin-tip__detail";
    hint.textContent = "Click to open the listing";
    box.appendChild(hint);
  }
  return box;
}

/** Legend entries for what is on the map: kinds of pin, and each line drawn or served. */
function legendEntries(pins: ReplyMapPin[], lines: ReplyMapLine[]) {
  const entries = new Map<string, { color: string; label: string }>();
  const listings = pins.filter((pin) => pin.kind === "listing").length;
  for (const pin of pins) {
    const style = styleFor(pin);
    const label = pin.kind === "listing" && listings === 1 ? "This listing" : style.label;
    entries.set(label, { color: style.color, label });
  }
  for (const line of lines) {
    const style = LINE_STYLE[line.line as keyof typeof LINE_STYLE];
    if (style) entries.set(style.label, style);
  }
  return Array.from(entries.values());
}

const PANEL = "rounded-2xl border border-[#E8ECF3] bg-white shadow-[0px_0px_20px_3px_rgba(20,20,24,0.04)]";

/** Places the answer is about, pinned from the data, with a numbered list that drives the map. */
export default function PlaceMap({ map }: { map: ReplyMap }) {
  const pins = map.pins ?? [];
  const lines = map.lines ?? [];
  const container = useRef<HTMLDivElement>(null);
  const leaflet = useRef<L.Map | null>(null);
  const markers = useRef<L.Marker[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [open, setOpen] = useState(true);
  const mapId = useId();
  const focusProperty = usePropertyFocusStore((state) => state.focusProperty);
  const numbers = pinNumbers(pins);

  // Picking a listing, on the map or in the list, also opens its card in the properties panel.
  const pick = useRef((index: number) => setActive(index));
  pick.current = (index: number) => {
    setActive(index);
    const id = pins[index] ? listingId(pins[index]) : null;
    if (id !== null) focusProperty(id);
  };

  useEffect(() => {
    if (!container.current || !pins.length) return;
    const instance = L.map(container.current, {
      scrollWheelZoom: false,
      zoomControl: false,
      attributionControl: true,
    });
    L.control.zoom({ position: "topright" }).addTo(instance);
    instance.attributionControl.setPrefix(false);
    L.tileLayer(TILES.url, { attribution: TILES.attribution, maxZoom: 19 }).addTo(instance);

    // Tracks sit under the pins and never take a click meant for a pin.
    for (const line of lines) {
      const style = LINE_STYLE[line.line as keyof typeof LINE_STYLE];
      if (!style || line.path.length < 2) continue;
      L.polyline(line.path, {
        color: style.color,
        weight: 4,
        opacity: 0.45,
        lineCap: "round",
        lineJoin: "round",
        interactive: false,
      }).addTo(instance);
    }

    markers.current = pins.map((pin, index) =>
      L.marker([pin.lat, pin.lng], {
        icon: markerIcon(pin, numbers[index], false),
        keyboard: false,
        zIndexOffset: pin.kind === "listing" ? 1000 : 0,
      })
        .bindTooltip(tooltipContent(pin), { direction: "top", offset: [0, -4], className: "propqa-pin-tooltip" })
        .on("click", () => pick.current(index))
        .addTo(instance),
    );

    // Frame the pins, not the lines: a line can run far past what the answer is about.
    if (pins.length === 1) {
      instance.setView([pins[0].lat, pins[0].lng], SINGLE_PIN_ZOOM);
    } else {
      instance.fitBounds(L.latLngBounds(pins.map((pin) => [pin.lat, pin.lng] as L.LatLngTuple)), {
        padding: [44, 44],
        maxZoom: MAX_FIT_ZOOM,
      });
    }
    leaflet.current = instance;

    // The chat column resizes with the sidebar; Leaflet must re-measure or tiles go missing.
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => instance.invalidateSize()) : null;
    observer?.observe(container.current);
    return () => {
      observer?.disconnect();
      instance.remove();
      leaflet.current = null;
      markers.current = [];
    };
    // numbers is derived from pins, so pins and lines alone decide when the map is rebuilt.
  }, [pins, lines]);

  useEffect(() => {
    markers.current.forEach((marker, index) => {
      marker.setIcon(markerIcon(pins[index], numbers[index], index === active));
      if (index === active) marker.openTooltip();
      else marker.closeTooltip();
    });
    if (active !== null && leaflet.current && pins[active]) {
      const zoom = Math.max(leaflet.current.getZoom(), SINGLE_PIN_ZOOM - 1);
      leaflet.current.flyTo([pins[active].lat, pins[active].lng], zoom, { duration: 0.5 });
    }
  }, [active, pins]);

  if (!pins.length) return null;
  const bodyId = `place-map-${mapId}`;
  const legend = legendEntries(pins, lines);
  const listings = pins.filter((pin) => pin.kind === "listing").length;
  const heading =
    pins.length === 1
      ? "On the map"
      : listings > 1
        ? `${listings} listings on the map`
        : `${pins.length} places on the map`;

  return (
    <figure className={`${PANEL} flex flex-col overflow-hidden`}>
      <figcaption className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls={bodyId}
          className="-mx-1 flex items-center gap-1.5 rounded-md px-1 text-xs font-semibold text-[#101527] hover:bg-[#F5F7FA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#E8ECF3]"
        >
          <ChevronDown
            className={cn("size-3.5 text-[#747288] transition-transform duration-200", !open && "-rotate-90")}
            aria-hidden
          />
          <MapPin className="size-3.5 text-[#747288]" aria-hidden />
          {heading}
          <span className="sr-only">{open ? "(hide map)" : "(show map)"}</span>
        </button>
        {open && legend.length > 1 && (
          <ul className="flex flex-wrap gap-3" aria-label="Legend">
            {legend.map((entry) => (
              <li key={entry.label} className="flex items-center gap-1.5 text-[11px] text-[#494A58]">
                <span className="size-2 rounded-full" style={{ background: entry.color }} aria-hidden />
                {entry.label}
              </li>
            ))}
          </ul>
        )}
      </figcaption>

      {/* Hidden rather than unmounted, so the map keeps its view; Leaflet re-measures on show. */}
      <div id={bodyId} hidden={!open}>
        <div
          ref={container}
          className="propqa-map h-64 w-full border-y border-[#E8ECF3] bg-[#F5F7FA] sm:h-72"
          role="img"
          aria-label={`Map of ${pins.map((pin) => pin.label).join(", ")}`}
        />

        <ol className="grid max-h-56 gap-0.5 overflow-y-auto p-2 sm:grid-cols-2" aria-label="Places on the map">
          {pins.map((pin, index) => (
            <li key={pin.property_id ?? `${pin.label}-${index}`}>
              <button
                type="button"
                onClick={() => pick.current(index)}
                aria-pressed={active === index}
                className={cn(
                  "flex w-full items-start gap-2 rounded-xl px-2 py-1.5 text-left transition-colors hover:bg-[#F5F7FA]",
                  active === index && "bg-[#F0F4FF] hover:bg-[#F0F4FF]",
                )}
              >
                <span
                  className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold text-white"
                  style={{ background: styleFor(pin).color }}
                  aria-hidden
                >
                  {numbers[index] === 0 ? <HomeGlyph /> : numbers[index]}
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate text-xs font-medium text-[#141B34]" dir="auto" title={pin.label}>
                      {pin.label}
                    </span>
                    {pin.property_id && (
                      <span
                        className="shrink-0 rounded border border-dashed border-[#D8DDE6] px-1 text-[10px] leading-4 text-[#747288]"
                        title="Property ID, as on its card"
                      >
                        {pin.property_id}
                      </span>
                    )}
                  </span>
                  {pin.detail && <span className="truncate text-[11px] text-[#747288]">{pin.detail}</span>}
                </span>
              </button>
            </li>
          ))}
        </ol>
        {map.hidden_pins ? (
          <p className="px-4 pb-2 text-[11px] text-[#979CAE]">+{map.hidden_pins} more not shown</p>
        ) : null}
      </div>
    </figure>
  );
}

function HomeGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="size-3" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round">
      <path d={HOUSE_PATH} />
    </svg>
  );
}
