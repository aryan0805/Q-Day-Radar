"use client";

// One tooltip for the whole page. It listens on the document for hover, focus and tap on a traced
// figure (.fig) or a glossary term (.gloss) and draws the tooltip from the element's data-*
// attributes. Escape closes it. Keeping this out of the figures keeps hydration cheap.
import { useEffect, useRef, useState } from "react";
import type { Term } from "../lib/glossary";
import { resolve } from "../lib/data";
import { fmtNumber } from "../lib/format";
import { LABEL_COLOUR, type ProvLabel } from "./Fig";

interface Extra {
  name: string;
  src: string;
  scale?: number;
  digits?: number;
  sci?: boolean;
  group?: boolean;
  sign?: boolean;
}

interface Open {
  el: HTMLElement;
  top: number;
  left: number;
  flip: boolean;
}

function split(src: string): [string, string] {
  const i = src.indexOf(":");
  return [src.slice(0, i), src.slice(i + 1)];
}

function value(x: Extra): string {
  const [f, p] = split(x.src);
  const v = resolve(f, p);
  if (v === null || v === undefined) return "none";
  return typeof v === "number" ? fmtNumber(v, x) : String(v);
}

export function FigTipHost() {
  const [open, setOpen] = useState<Open | null>(null);
  const current = useRef<HTMLElement | null>(null);
  const openedAt = useRef(0);
  const [glossary, setGlossary] = useState<Record<string, Term> | null>(null);

  useEffect(() => {
    const target = (e: Event): HTMLElement | null => (e.target as HTMLElement | null)?.closest?.(".fig, .gloss") ?? null;
    const show = (el: HTMLElement) => {
      const r = el.getBoundingClientRect();
      const left = Math.max(8, Math.min(r.left, window.innerWidth - 360));
      current.current = el;
      openedAt.current = performance.now();
      setOpen({ el, top: r.bottom + 6, left, flip: r.bottom > window.innerHeight - 220 });
    };
    const hide = () => {
      current.current = null;
      setOpen(null);
    };
    const over = (e: PointerEvent) => {
      const el = target(e);
      if (el && e.pointerType === "mouse") show(el);
    };
    const out = (e: PointerEvent) => {
      if (target(e) && e.pointerType === "mouse") hide();
    };
    const focus = (e: FocusEvent) => {
      const el = target(e);
      if (el) show(el);
    };
    const blur = (e: FocusEvent) => {
      if (target(e)) hide();
    };
    const click = (e: MouseEvent) => {
      const el = target(e);
      if (!el) return hide();
      // A tap toggles; a mouse click keeps the tooltip the hover opened.
      // (the focus that a tap causes has just opened it, so ignore a toggle straight after)
      if ((e as PointerEvent).pointerType !== "mouse" && current.current === el) {
        if (performance.now() - openedAt.current > 400) hide();
      } else show(el);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") hide();
    };
    document.addEventListener("pointerover", over);
    document.addEventListener("pointerout", out);
    document.addEventListener("focusin", focus);
    document.addEventListener("focusout", blur);
    document.addEventListener("click", click);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerover", over);
      document.removeEventListener("pointerout", out);
      document.removeEventListener("focusin", focus);
      document.removeEventListener("focusout", blur);
      document.removeEventListener("click", click);
      document.removeEventListener("keydown", key);
    };
  }, []);

  // The definitions are a separate chunk, fetched the first time a glossary term is opened.
  useEffect(() => {
    if (open?.el.dataset.term && !glossary) void import("../lib/glossary").then((m) => setGlossary(m.GLOSSARY));
  }, [open, glossary]);

  useEffect(() => {
    if (!open) return;
    open.el.setAttribute("aria-describedby", "fig-tip");
    return () => open.el.removeAttribute("aria-describedby");
  }, [open]);

  if (!open) return null;
  const d = open.el.dataset;
  const style = { left: open.left, ...(open.flip ? { bottom: window.innerHeight - open.top + 30 } : { top: open.top }) };

  if (d.term) {
    const t = glossary?.[d.term];
    if (!t) return null;
    return (
      <span id="fig-tip" role="tooltip" className="fig-tip" style={style}>
        <span className="fig-tip-row">{t.plain}</span>
        {t.exact ? <span className="fig-tip-row muted">Exact term: {t.exact}</span> : null}
      </span>
    );
  }

  const [file, path] = split(d.src ?? "");
  const extras: Extra[] = d.extra ? (JSON.parse(d.extra) as Extra[]) : [];
  const label = (d.label ?? "computed from data") as ProvLabel;
  return (
    <span id="fig-tip" role="tooltip" className="fig-tip" style={style}>
      <span className="fig-tip-row">
        <span style={{ color: LABEL_COLOUR[label], fontWeight: 600 }}>{label}</span>
      </span>
      <span className="fig-tip-row">
        {file}.json · <code data-literal="provenance path, an identifier">{path}</code>
      </span>
      {d.note ? <span className="fig-tip-row">{d.note}</span> : null}
      {extras.map((x) => (
        <span className="fig-tip-row" key={x.name + x.src}>
          {x.name}{" "}
          <span data-src={x.src} data-scale={x.scale && x.scale !== 1 ? x.scale : undefined}>
            {value(x)}
          </span>
        </span>
      ))}
    </span>
  );
}
