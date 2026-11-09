// A figure from the data. It renders as <span data-src="file:path"> so the gate can recompute it;
// hover or focus shows where it comes from: file, path, one label, optional notes and extras.
import { fmtNumber, type NumFmt } from "../lib/format";
import { resolve } from "../lib/data";

export type ProvLabel =
  | "hardware"
  | "simulated"
  | "trend extrapolation"
  | "published estimate"
  | "published standard"
  | "fictional demo input"
  | "design choice"
  | "model estimate"
  | "computed from data"
  | "computed from data, using design-choice exposure weights";

export const LABEL_COLOUR: Record<ProvLabel, string> = {
  hardware: "var(--q)",
  simulated: "var(--sim-text)",
  "trend extrapolation": "var(--warn)",
  "published estimate": "var(--text-1)",
  "published standard": "var(--text-1)",
  "fictional demo input": "var(--text-2)",
  "design choice": "var(--text-2)",
  "model estimate": "var(--warn)",
  "computed from data": "var(--text-2)",
  "computed from data, using design-choice exposure weights": "var(--text-2)",
};

export interface Extra extends NumFmt {
  name: string;
  src: string;
}

export interface FigProps extends NumFmt {
  src: string; // "<file>:<path>"
  label: ProvLabel;
  unit?: string;
  note?: string;
  extra?: Extra[];
  nullText?: string;
  className?: string;
}

export function show(src: string, f: NumFmt, nullText = "none"): string {
  const [file = "", path = ""] = splitRef(src);
  const v = resolve(file, path);
  if (v === null || v === undefined) return nullText;
  if (typeof v === "number") return fmtNumber(v, f);
  return String(v);
}

export function splitRef(src: string): [string, string] {
  const i = src.indexOf(":");
  return [src.slice(0, i), src.slice(i + 1)];
}

/** A figure from the data. Plain markup, no hooks: one shared host (FigTipHost) shows the
 *  provenance tooltip on hover, focus or tap from the data-* attributes below, so a page with
 *  hundreds of figures hydrates cheaply. */
export function Fig(props: FigProps) {
  const { src, label, unit, note, extra, nullText, className, ...fmt } = props;
  const [file, path] = splitRef(src);
  const text = show(src, fmt, nullText);
  return (
    <span className={`fig-wrap ${className ?? ""}`}>
      <span
        className="fig"
        data-src={src}
        data-scale={fmt.scale && fmt.scale !== 1 ? fmt.scale : undefined}
        data-label={label}
        data-note={note}
        data-extra={extra && extra.length ? JSON.stringify(extra) : undefined}
        tabIndex={0}
      >
        {text}
      </span>
      {unit && resolve(file, path) !== null ? <span className="fig-unit">{unit}</span> : null}
    </span>
  );
}
