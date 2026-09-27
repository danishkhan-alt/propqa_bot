import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { MapPin } from "lucide-react";
import { cn } from "@/lib/utils";

export type MapPinKind = "listing" | "metro" | "nearby" | "place";

export interface ReplyMapPin {
  lat: number;
  lng: number;
  label: string;
  detail?: string;
  kind: MapPinKind | string;
}

export interface ReplyMap {
  pins: ReplyMapPin[];
  hidden_pins?: number;
}

// OpenStreetMap's own tiles need no key but are meant for light use; heavy traffic belongs
// on a keyed provider (MapTiler, Stadia, Mapbox), which only changes this constant.
// index.css mutes them so the pins stay the loudest thing on the map.
const TILES = {
  url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};

const KIND_STYLE: Record<MapPinKind, { color: string; label: string }> = {
  listing: { color: "#101527", label: "This listing" },
  metro: { color: "#D92D20", label: "Metro" },
  nearby: { color: "#1BAF7A", label: "Nearby" },
  place: { color: "#1D4ED8", label: "Place" },
};

const SINGLE_PIN_ZOOM = 15;
const MAX_FIT_ZOOM = 16;

function styleFor(kind: string) {
  return KIND_STYLE[kind as MapPinKind] ?? KIND_STYLE.place;
}

/** Each pin's number in the list; a listing pin shows a house instead, so it takes none. */
function pinNumbers(pins: ReplyMapPin[]): number[] {
  let next = 0;
  return pins.map((pin) => (pin.kind === "listing" ? 0 : ++next));
}

/** A numbered marker; the listing gets a house so it reads as "you are here". */
function markerIcon(pin: ReplyMapPin, number: number, active: boolean): L.DivIcon {
  const { color } = styleFor(pin.kind);
  const size = pin.kind === "listing" ? 30 : 24;
  const glyph =
    pin.kind === "listing"
      ? '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/></svg>'
      : String(number);
  return L.divIcon({
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    tooltipAnchor: [0, -size / 2],
    html: `<span class="propqa-pin${active ? " propqa-pin--active" : ""}" style="--pin:${color};width:${size}px;height:${size}px">${glyph}</span>`,
  });
}

/** Tooltip content built from text nodes: labels come from the data, never as markup. */
function tooltipContent(pin: ReplyMapPin): HTMLElement {
  const box = document.createElement("div");
  box.className = "propqa-pin-tip";
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
  return box;
}

const PANEL = "rounded-2xl border border-[#E8ECF3] bg-white shadow-[0px_0px_20px_3px_rgba(20,20,24,0.04)]";

/** Places the answer is about, pinned from the data, with a numbered list that drives the map. */
export default function PlaceMap({ map }: { map: ReplyMap }) {
  const pins = map.pins ?? [];
  const container = useRef<HTMLDivElement>(null);
  const leaflet = useRef<L.Map | null>(null);
  const markers = useRef<L.Marker[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const numbers = pinNumbers(pins);

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

    markers.current = pins.map((pin, index) =>
      L.marker([pin.lat, pin.lng], {
        icon: markerIcon(pin, numbers[index], false),
        keyboard: false,
        zIndexOffset: pin.kind === "listing" ? 1000 : 0,
      })
        .bindTooltip(tooltipContent(pin), { direction: "top", offset: [0, -4], className: "propqa-pin-tooltip" })
        .on("click", () => setActive(index))
        .addTo(instance),
    );

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
  }, [pins]);

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
  const kinds = Array.from(new Set(pins.map((pin) => (pin.kind in KIND_STYLE ? pin.kind : "place"))));

  return (
    <figure className={`${PANEL} flex flex-col overflow-hidden`}>
      <figcaption className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-[#101527]">
          <MapPin className="size-3.5 text-[#747288]" aria-hidden />
          {pins.length === 1 ? "On the map" : `${pins.length} places on the map`}
        </span>
        {kinds.length > 1 && (
          <ul className="flex flex-wrap gap-3" aria-label="Legend">
            {kinds.map((kind) => (
              <li key={kind} className="flex items-center gap-1.5 text-[11px] text-[#494A58]">
                <span className="size-2 rounded-full" style={{ background: styleFor(kind).color }} aria-hidden />
                {styleFor(kind).label}
              </li>
            ))}
          </ul>
        )}
      </figcaption>

      <div
        ref={container}
        className="propqa-map h-64 w-full border-y border-[#E8ECF3] bg-[#F5F7FA] sm:h-72"
        role="img"
        aria-label={`Map of ${pins.map((pin) => pin.label).join(", ")}`}
      />

      <ol className="grid max-h-48 gap-0.5 overflow-y-auto p-2 sm:grid-cols-2" aria-label="Places on the map">
        {pins.map((pin, index) => (
          <li key={`${pin.label}-${index}`}>
            <button
              type="button"
              onClick={() => setActive(index)}
              aria-pressed={active === index}
              className={cn(
                "flex w-full items-start gap-2 rounded-xl px-2 py-1.5 text-left transition-colors hover:bg-[#F5F7FA]",
                active === index && "bg-[#F0F4FF] hover:bg-[#F0F4FF]",
              )}
            >
              <span
                className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold text-white"
                style={{ background: styleFor(pin.kind).color }}
                aria-hidden
              >
                {pin.kind === "listing" ? <HomeGlyph /> : numbers[index]}
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-xs font-medium text-[#141B34]" dir="auto" title={pin.label}>
                  {pin.label}
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
    </figure>
  );
}

function HomeGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="size-3" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" />
    </svg>
  );
}
