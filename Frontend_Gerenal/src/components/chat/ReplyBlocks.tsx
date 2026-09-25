import { useState } from "react";
import { CircleAlert, CircleCheck, Lightbulb } from "lucide-react";

export interface StatTile {
  label: string;
  value: string;
}

export interface FigureBar {
  label: string;
  value: number;
  display: string;
}

export interface LinePoint {
  value: number | null;
  display: string;
}

export interface LineSeries {
  name: string;
  points: LinePoint[];
}

export type ReplyFigures =
  | { layout: "stats"; tiles: StatTile[] }
  | { layout: "table"; headers: string[]; rows: string[][]; caption?: string[]; hidden_rows?: number }
  | { layout: "bar"; title: string; bars: FigureBar[]; hidden_rows?: number }
  | { layout: "line"; title: string; labels: string[]; series: LineSeries[]; hidden_rows?: number };

export interface ReplyExplainer {
  kind: "steps" | "pros_cons" | "callout";
  title?: string;
  points: string[];
  cautions?: string[];
}

const PANEL = "rounded-2xl border border-[#E8ECF3] bg-white shadow-[0px_0px_20px_3px_rgba(20,20,24,0.04)]";

/** Figures copied from the lookup rows: key-figure tiles, a small table, or a bar comparison. */
export function FiguresBlock({ figures }: { figures: ReplyFigures }) {
  if (figures.layout === "stats") {
    if (!figures.tiles?.length) return null;
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {figures.tiles.map((tile) => (
          <div key={tile.label} className={`${PANEL} flex flex-col gap-0.5 px-4 py-3`}>
            <span className="text-[11px] font-medium leading-4 text-[#747288]">{tile.label}</span>
            <span className="text-base font-semibold leading-6 text-[#101527] tabular-nums">{tile.value}</span>
          </div>
        ))}
      </div>
    );
  }

  if (figures.layout === "table") {
    if (!figures.rows?.length) return null;
    return (
      <div className={`${PANEL} overflow-x-auto`}>
        <table className="w-full min-w-max text-left text-xs">
          <thead>
            <tr className="border-b border-[#E8ECF3] text-[#747288]">
              {figures.headers.map((header, i) => (
                <th key={`${header}-${i}`} scope="col" className={`px-3 py-2 font-medium ${i > 0 ? "text-right" : ""}`}>
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {figures.rows.map((row, r) => (
              <tr key={r} className="border-b border-[#F0F2F7] last:border-0">
                {row.map((cell, i) => (
                  <td
                    key={i}
                    className={`px-3 py-2 ${i > 0 ? "text-right tabular-nums text-[#101527]" : "font-medium text-[#141B34]"}`}
                  >
                    <FigureCell value={cell} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {figures.caption?.length ? (
          <p className="px-3 pb-2 pt-1 text-[11px] text-[#747288]">{figures.caption.join(" · ")}</p>
        ) : null}
        <HiddenRows count={figures.hidden_rows} />
      </div>
    );
  }

  if (figures.layout === "line") {
    if (!figures.series?.length || figures.labels?.length < 2) return null;
    return <LineFigure figures={figures} />;
  }

  if (figures.layout === "bar") {
    if (!figures.bars?.length) return null;
    const max = Math.max(...figures.bars.map((bar) => bar.value), 0) || 1;
    return (
      <figure className={`${PANEL} flex flex-col gap-2 px-4 py-3`}>
        <figcaption className="text-xs font-semibold text-[#101527]">{figures.title}</figcaption>
        <ul className="flex flex-col gap-1.5">
          {figures.bars.map((bar) => (
            <li key={bar.label} className="grid grid-cols-[minmax(0,7rem)_1fr_auto] items-center gap-2 text-xs">
              <span className="truncate text-[#494A58]" title={bar.label}>
                {bar.label}
              </span>
              <span className="h-2 rounded-full bg-[#F0F2F7]" aria-hidden>
                <span
                  className="block h-2 rounded-full bg-[#1D4ED8]"
                  style={{ width: `${Math.max((bar.value / max) * 100, 2)}%` }}
                />
              </span>
              <span className="font-medium tabular-nums text-[#101527]">{bar.display}</span>
            </li>
          ))}
        </ul>
        <HiddenRows count={figures.hidden_rows} />
      </figure>
    );
  }

  return null;
}

/** A change arrives as "▲ 8.9%" or "▼ 1.2%": the arrow carries the direction in color, the figure stays in ink. */
function FigureCell({ value }: { value: string }) {
  if (!value) return <>—</>;
  const direction = value.startsWith("▲") ? "up" : value.startsWith("▼") ? "down" : null;
  if (!direction) return <>{value}</>;
  return (
    <span className="inline-flex items-center gap-1">
      <span aria-hidden className={direction === "up" ? "text-[#157A45]" : "text-[#B42318]"}>
        {value.slice(0, 1)}
      </span>
      <span className="sr-only">{direction === "up" ? "up" : "down"}</span>
      {value.slice(1).trim()}
    </span>
  );
}

// Categorical order is fixed; a series keeps its hue whatever else is shown.
const SERIES_COLORS = ["#1D4ED8", "#EB6834", "#1BAF7A"];
const CHART = { width: 560, height: 180, left: 8, right: 8, top: 12, bottom: 24 };

type LineFigures = Extract<ReplyFigures, { layout: "line" }>;

function latestIndex(points: LinePoint[]): number {
  for (let i = points.length - 1; i >= 0; i -= 1) if (points[i].value !== null) return i;
  return -1;
}

/** One to three series over periods: 2px lines, a marker on the latest point, a hover readout of every value. */
function LineFigure({ figures }: { figures: LineFigures }) {
  const [active, setActive] = useState<number | null>(null);
  const { labels, series } = figures;
  const values = series.flatMap((s) => s.points.map((p) => p.value)).filter((v): v is number => v !== null);
  if (!values.length) return null;
  let low = Math.min(...values);
  let high = Math.max(...values);
  if (low === high) {
    low -= 1;
    high += 1;
  }
  const pad = (high - low) * 0.1;
  low -= pad;
  high += pad;
  const plotWidth = CHART.width - CHART.left - CHART.right;
  const plotHeight = CHART.height - CHART.top - CHART.bottom;
  const x = (i: number) => CHART.left + (labels.length === 1 ? plotWidth / 2 : (i / (labels.length - 1)) * plotWidth);
  const y = (v: number) => CHART.top + (1 - (v - low) / (high - low)) * plotHeight;
  const ticks = [0, 0.5, 1].map((f) => low + pad + f * (high - low - 2 * pad));
  const xLabels = Array.from(new Set([0, Math.floor((labels.length - 1) / 2), labels.length - 1]));

  const path = (points: LinePoint[]) => {
    let d = "";
    let open = false;
    points.forEach((point, i) => {
      if (point.value === null) {
        open = false;
        return;
      }
      d += `${open ? "L" : "M"}${x(i).toFixed(1)},${y(point.value).toFixed(1)}`;
      open = true;
    });
    return d;
  };

  const onMove = (event: React.PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - box.left) / box.width;
    setActive(Math.round(Math.min(Math.max(ratio, 0), 1) * (labels.length - 1)));
  };

  return (
    <figure className={`${PANEL} flex flex-col gap-2 px-4 py-3`}>
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        {figures.title && <span className="text-xs font-semibold text-[#101527]">{figures.title}</span>}
        {series.length > 1 && (
          <ul className="flex flex-wrap gap-3" aria-label="Series">
            {series.map((s, i) => (
              <li key={s.name} className="flex items-center gap-1.5 text-[11px] text-[#494A58]">
                <span className="h-0.5 w-3 rounded-full" style={{ background: SERIES_COLORS[i] }} aria-hidden />
                {s.name}
              </li>
            ))}
          </ul>
        )}
      </figcaption>
      <div className="relative">
        <svg
          viewBox={`0 0 ${CHART.width} ${CHART.height}`}
          className="h-auto w-full overflow-visible"
          role="img"
          aria-label={`${figures.title || series.map((s) => s.name).join(", ")}, ${labels[0]} to ${labels[labels.length - 1]}`}
        >
          {ticks.map((tick) => (
            <line
              key={tick}
              x1={CHART.left}
              x2={CHART.width - CHART.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="#F0F2F7"
              strokeWidth={1}
            />
          ))}
          {xLabels.map((i) => (
            <text
              key={i}
              x={x(i)}
              y={CHART.height - 6}
              textAnchor={i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle"}
              className="fill-[#747288] text-[11px]"
            >
              {labels[i]}
            </text>
          ))}
          {active !== null && (
            <line x1={x(active)} x2={x(active)} y1={CHART.top} y2={CHART.top + plotHeight} stroke="#C9CEDA" strokeWidth={1} />
          )}
          {series.map((s, i) => {
            const marker = active ?? latestIndex(s.points);
            const point = s.points[marker];
            return (
              <g key={s.name}>
                <path d={path(s.points)} fill="none" stroke={SERIES_COLORS[i]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                {point && point.value !== null && (
                  <circle cx={x(marker)} cy={y(point.value)} r={4} fill={SERIES_COLORS[i]} stroke="#FFFFFF" strokeWidth={2} />
                )}
              </g>
            );
          })}
          <rect
            x={CHART.left}
            y={0}
            width={plotWidth}
            height={CHART.height}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => setActive(null)}
          />
        </svg>
        {active !== null && (
          <div
            className="pointer-events-none absolute top-0 rounded-lg border border-[#E8ECF3] bg-white px-2.5 py-1.5 text-[11px] shadow-sm"
            style={{
              left: `${(x(active) / CHART.width) * 100}%`,
              transform: active > (labels.length - 1) / 2 ? "translateX(calc(-100% - 8px))" : "translateX(8px)",
            }}
          >
            <p className="font-medium text-[#101527]">{labels[active]}</p>
            {series.map((s, i) => (
              <p key={s.name} className="flex items-center gap-1.5 tabular-nums text-[#494A58]">
                <span className="size-1.5 rounded-full" style={{ background: SERIES_COLORS[i] }} aria-hidden />
                {series.length > 1 ? `${s.name}: ` : ""}
                {s.points[active]?.display || "—"}
              </p>
            ))}
          </div>
        )}
      </div>
      <p className="text-[11px] text-[#747288]">
        Latest ({labels[labels.length - 1]}):{" "}
        {series.map((s) => `${series.length > 1 ? `${s.name} ` : ""}${s.points[s.points.length - 1]?.display || "—"}`).join(" · ")}
      </p>
      <HiddenRows count={figures.hidden_rows} />
    </figure>
  );
}

function HiddenRows({ count }: { count?: number }) {
  if (!count) return null;
  return <p className="px-3 pb-2 text-[11px] text-[#979CAE]">+{count} more not shown</p>;
}

/** A short written aid: ordered steps, pros and cons, or one callout. */
export function ExplainerBlock({ explainer }: { explainer: ReplyExplainer }) {
  const points = explainer.points ?? [];
  const cautions = explainer.cautions ?? [];

  if (explainer.kind === "callout") {
    if (!points.length) return null;
    return (
      <aside className="flex gap-2.5 rounded-2xl border border-[#F1E3C8] bg-[#FBF7EF] px-4 py-3">
        <Lightbulb className="mt-0.5 size-4 shrink-0 text-[#8A5A12]" aria-hidden />
        <div className="flex flex-col gap-1 text-xs leading-5 text-[#494A58]">
          {explainer.title && <p className="font-semibold text-[#101527]">{explainer.title}</p>}
          {points.map((point) => (
            <p key={point}>{point}</p>
          ))}
        </div>
      </aside>
    );
  }

  if (explainer.kind === "steps") {
    if (!points.length) return null;
    return (
      <section className={`${PANEL} flex flex-col gap-2 px-4 py-3`}>
        {explainer.title && <h3 className="text-sm font-semibold text-[#101527]">{explainer.title}</h3>}
        <ol className="flex flex-col gap-2">
          {points.map((point, i) => (
            <li key={point} className="flex gap-2.5 text-xs leading-5 text-[#494A58]">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-[#E8F1FF] text-[11px] font-semibold text-[#1D4ED8]">
                {i + 1}
              </span>
              <span className="pt-px">{point}</span>
            </li>
          ))}
        </ol>
      </section>
    );
  }

  if (explainer.kind === "pros_cons") {
    if (!points.length && !cautions.length) return null;
    return (
      <section className={`${PANEL} flex flex-col gap-2 px-4 py-3`}>
        {explainer.title && <h3 className="text-sm font-semibold text-[#101527]">{explainer.title}</h3>}
        <div className="grid gap-3 sm:grid-cols-2">
          <PointList items={points} tone="positive" />
          <PointList items={cautions} tone="warning" />
        </div>
      </section>
    );
  }

  return null;
}

function PointList({ items, tone }: { items: string[]; tone: "positive" | "warning" }) {
  if (!items.length) return null;
  const Icon = tone === "positive" ? CircleCheck : CircleAlert;
  const color = tone === "positive" ? "text-[#157A45]" : "text-[#8A5A12]";
  const heading = tone === "positive" ? "Upsides" : "Watch out for";
  return (
    <div className="flex flex-col gap-1.5">
      <p className={`text-[11px] font-semibold uppercase tracking-wide ${color}`}>{heading}</p>
      <ul className="flex flex-col gap-1.5" aria-label={heading}>
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-xs leading-5 text-[#494A58]">
            <Icon className={`mt-0.5 size-3.5 shrink-0 ${color}`} aria-hidden />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
