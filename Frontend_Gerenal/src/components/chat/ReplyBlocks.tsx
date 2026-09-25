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

export type ReplyFigures =
  | { layout: "stats"; tiles: StatTile[] }
  | { layout: "table"; headers: string[]; rows: string[][]; hidden_rows?: number }
  | { layout: "bar"; title: string; bars: FigureBar[]; hidden_rows?: number };

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
                    {cell || "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <HiddenRows count={figures.hidden_rows} />
      </div>
    );
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
