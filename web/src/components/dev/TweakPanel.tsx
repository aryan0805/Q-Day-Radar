"use client";

// QDAY_TWEAK_PANEL: development only (spec §8.2). Loaded by TweakLoader through a dynamic import
// behind `process.env.NODE_ENV === "development"`, so this module is not in the production
// build; tests/phase5 checks that this sentinel is absent from out/.
// It rewrites the design tokens as CSS variables on <html>. "Copy tokens" gives the JSON to paste
// to builder, who commits the values into tokens.css.

import { useCallback, useState } from "react";

const COLOURS = ["q", "threat", "warn", "pqc", "sim", "sim-text", "text-1", "text-2"] as const;
const RANGES = [
  { name: "glow", min: 0, max: 2, step: 0.05, unit: "" },
  { name: "dur-ui", min: 0, max: 600, step: 10, unit: "ms" },
  { name: "dur-reveal", min: 0, max: 1500, step: 25, unit: "ms" },
  { name: "bg-density", min: 0.5, max: 2, step: 0.05, unit: "" },
  { name: "bg-speed", min: 0, max: 2, step: 0.05, unit: "" },
] as const;

function read(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}

/** Numeric value of a token; the browser reports durations in seconds (".18s"), the sliders use ms. */
function num(name: string, fallback: number): number {
  const v = read(name);
  const n = Number.parseFloat(v);
  if (Number.isNaN(n)) return fallback;
  return v.endsWith("ms") || !v.endsWith("s") ? n : n * 1000;
}

function toHex(value: string): string {
  // A colour read from an @supports (oklch) declaration is not a hex string: paint it on a canvas.
  if (/^#[0-9a-f]{6}$/i.test(value)) return value;
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return "#000000";
  ctx.fillStyle = "#000000";
  ctx.fillStyle = value;
  ctx.fillRect(0, 0, 1, 1);
  const [r = 0, g = 0, b = 0] = ctx.getImageData(0, 0, 1, 1).data;
  return `#${[r, g, b].map((n) => n.toString(16).padStart(2, "0")).join("")}`;
}

export default function TweakPanel() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState(false);

  const set = useCallback((name: string, value: string) => {
    document.documentElement.style.setProperty(`--${name}`, value);
    setValues((v) => ({ ...v, [name]: value }));
  }, []);

  const current = (name: string, fallback: string) => values[name] ?? fallback;

  return (
    <aside
      aria-label="Design tweaks (development only)"
      style={{
        position: "fixed",
        right: "1rem",
        bottom: "1rem",
        zIndex: 100,
        width: "18rem",
        maxHeight: "80dvh",
        overflow: "auto",
        padding: "1rem",
        background: "var(--bg-2)",
        border: "1px solid var(--line)",
        borderRadius: "6px",
        fontSize: "0.8125rem",
      }}
    >
      <h2 style={{ fontSize: "1rem", margin: "0 0 0.75rem" }}>Tweaks</h2>
      {COLOURS.map((c) => (
        <label key={c} style={{ display: "flex", justifyContent: "space-between", marginBlock: 4 }}>
          {c}
          <input
            type="color"
            value={current(c, toHex(read(c)))}
            onChange={(e) => set(c, e.target.value)}
          />
        </label>
      ))}
      {RANGES.map((r) => (
        <label key={r.name} style={{ display: "block", marginBlock: 8 }}>
          {r.name} {values[r.name] ?? `${num(r.name, 1)}${r.unit}`}
          <input
            type="range"
            min={r.min}
            max={r.max}
            step={r.step}
            defaultValue={num(r.name, 1)}
            onChange={(e) => set(r.name, `${e.target.value}${r.unit}`)}
            style={{ width: "100%" }}
          />
        </label>
      ))}
      <button
        type="button"
        className="btn"
        onClick={() => {
          const out: Record<string, string> = {};
          for (const c of COLOURS) out[c] = values[c] ?? toHex(read(c));
          for (const r of RANGES) out[r.name] = values[r.name] ?? `${num(r.name, 1)}${r.unit}`;
          void navigator.clipboard.writeText(JSON.stringify(out, null, 2)).then(() => setCopied(true));
        }}
      >
        {copied ? "Copied" : "Copy tokens"}
      </button>
    </aside>
  );
}
