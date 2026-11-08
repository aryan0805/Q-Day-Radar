"use client";

// A figure from the data. It renders as <span data-src="file:path"> so the gate can recompute it;
// hover or focus shows where it comes from: file, path, one label, optional notes and extras.
import { useId, useState } from "react";
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
  | "computed from data";

const LABEL_COLOUR: Record<ProvLabel, string> = {
  hardware: "var(--q)",
  simulated: "var(--sim-text)",
  "trend extrapolation": "var(--warn)",
  "published estimate": "var(--text-1)",
  "published standard": "var(--text-1)",
  "fictional demo input": "var(--text-2)",
  "design choice": "var(--text-2)",
  "model estimate": "var(--warn)",
  "computed from data": "var(--text-2)",
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

export function Fig(props: FigProps) {
  const { src, label, unit, note, extra, nullText, className, ...fmt } = props;
  const [open, setOpen] = useState(false);
  const id = useId();
  const [file, path] = splitRef(src);
  const text = show(src, fmt, nullText);
  return (
    <span className={`fig-wrap ${className ?? ""}`} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <span
        className="fig"
        data-src={src}
        data-scale={fmt.scale && fmt.scale !== 1 ? fmt.scale : undefined}
        tabIndex={0}
        aria-describedby={open ? id : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        {text}
      </span>
      {unit && resolve(file, path) !== null ? <span className="fig-unit">{unit}</span> : null}
      {open ? (
        <span role="tooltip" id={id} className="fig-tip">
          <span className="fig-tip-row">
            <span style={{ color: LABEL_COLOUR[label], fontWeight: 600 }}>{label}</span>
          </span>
          <span className="fig-tip-row">
            {file}.json ·{" "}
            <code data-literal="provenance path, an identifier">{path}</code>
          </span>
          {note ? <span className="fig-tip-row">{note}</span> : null}
          {extra?.map((x) => (
            <span className="fig-tip-row" key={x.name + x.src}>
              {x.name}{" "}
              <span data-src={x.src} data-scale={x.scale && x.scale !== 1 ? x.scale : undefined}>
                {show(x.src, x)}
              </span>
            </span>
          ))}
        </span>
      ) : null}
    </span>
  );
}
