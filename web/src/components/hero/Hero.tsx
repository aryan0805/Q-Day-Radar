"use client";

// The Q-Day sequence (spec §5), built from hero.json: the real Shor-15 textbook circuit, the
// ideal and the ibm_kingston counts, the factors continued fractions find in the measured counts,
// and the post-quantum lattice. Scroll-scrubbed with GSAP (loaded only when the hero mounts and
// motion is allowed). Under prefers-reduced-motion the four end states show as a static strip, by
// CSS alone, so there is no layout shift and GSAP is never requested.
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { yieldToMain } from "../../lib/interaction";
import hero from "../../../public/data/herostrip.json";
import { register } from "../../lib/data";
import { Fig } from "../Fig";
import { Traced } from "../Traced";
import { Gloss } from "../Gloss";
import { Tech } from "../Tech";

register("herostrip", hero);

const W = 800;
const H = 330;
const WIRE_X0 = 78;
const LAYER_DX = 58;
const ROW_Y0 = 30;
const ROW_DY = 24;

const gates = hero.circuit.gates;

// One-line explanation of each gate, shown on hover (an SVG <title>).
const GATE_HELP: Record<string, string> = {
  h: "Hadamard: puts a qubit into an equal mix of zero and one.",
  x: "NOT: flips a qubit between zero and one.",
  cx: "Controlled NOT: flips the target qubit only if the control qubit is one.",
  cswap: "Controlled swap: swaps two qubits only if the control qubit is one.",
  qft_dg: "Inverse quantum Fourier transform: turns the hidden repeating pattern into a number we can read.",
  measure: "Measurement: reads a qubit as zero or one.",
};
const nQubits = hero.circuit.n_qubits;
const wireY = (q: number) => ROW_Y0 + q * ROW_DY;
const gateX = (layer: number) => WIRE_X0 + layer * LAYER_DX;
const r2 = (v: number) => Math.round(v * 100) / 100;

function CircuitSvg() {
  const lastX = gateX(Math.max(...gates.map((g) => g.layer))) + 40;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="The Shor circuit for fifteen: eight counting qubits, four work qubits, controlled multiplications, an inverse Fourier transform and measurement" className="hero-svg">
      {Array.from({ length: nQubits }, (_, q) => (
        <line key={q} className="h-wire" x1={WIRE_X0 - 14} x2={lastX} y1={wireY(q)} y2={wireY(q)} stroke="var(--text-2)" strokeWidth="1.2" pathLength={1} />
      ))}
      <text x="6" y={wireY(0) + 4} fill="var(--text-2)" fontSize="13">count</text>
      <text x="6" y={wireY(8) + 4} fill="var(--text-2)" fontSize="13">work</text>
      {gates.map((g, i) => {
        const x = gateX(g.layer);
        const ys = g.qubits.map(wireY);
        const top = Math.min(...ys);
        const bottom = Math.max(...ys);
        if (g.op === "qft_dg") {
          return (
            <g key={i} className="h-gate"><title>{GATE_HELP[g.op] ?? g.op}</title>
              <rect x={r2(x - 20)} y={top - 11} width="40" height={bottom - top + 22} rx="3" fill="var(--bg-2)" stroke="var(--q)" />
              <text x={x} y={r2((top + bottom) / 2 + 4)} textAnchor="middle" fill="var(--q)" fontSize="13">QFT†</text>
            </g>
          );
        }
        if (g.op === "measure") {
          return (
            <g key={i} className="h-gate"><title>{GATE_HELP[g.op] ?? g.op}</title>
              <rect x={r2(x - 10)} y={wireY(g.qubits[0] ?? 0) - 9} width="20" height="18" rx="2" fill="var(--bg-2)" stroke="var(--pqc)" />
              <path d={`M ${r2(x - 6)} ${wireY(g.qubits[0] ?? 0) + 4} A 7 7 0 0 1 ${r2(x + 6)} ${wireY(g.qubits[0] ?? 0) + 4}`} fill="none" stroke="var(--pqc)" />
            </g>
          );
        }
        if (g.op === "h" || g.op === "x") {
          return (
            <g key={i} className="h-gate"><title>{GATE_HELP[g.op] ?? g.op}</title>
              <rect x={r2(x - 10)} y={wireY(g.qubits[0] ?? 0) - 9} width="20" height="18" rx="2" fill="var(--bg-2)" stroke="var(--q)" />
              <text x={x} y={wireY(g.qubits[0] ?? 0) + 4} textAnchor="middle" fill="var(--text-1)" fontSize="12">{g.op.toUpperCase()}</text>
            </g>
          );
        }
        return (
          <g key={i} className="h-gate"><title>{GATE_HELP[g.op] ?? g.op}</title>
            <line x1={x} x2={x} y1={top} y2={bottom} stroke="var(--q)" />
            {g.qubits.map((q, k) =>
              k === 0 ? (
                <circle key={q} cx={x} cy={wireY(q)} r="3.5" fill="var(--q)" />
              ) : g.op === "cx" ? (
                <g key={q}>
                  <circle cx={x} cy={wireY(q)} r="7" fill="var(--bg-0)" stroke="var(--q)" />
                  <path d={`M ${x - 5} ${wireY(q)} H ${x + 5} M ${x} ${wireY(q) - 5} V ${wireY(q) + 5}`} stroke="var(--q)" />
                </g>
              ) : (
                <path key={q} d={`M ${x - 5} ${wireY(q) - 5} L ${x + 5} ${wireY(q) + 5} M ${x + 5} ${wireY(q) - 5} L ${x - 5} ${wireY(q) + 5}`} stroke="var(--q)" strokeWidth="1.6" />
              ),
            )}
          </g>
        );
      })}
    </svg>
  );
}

function HistogramSvg() {
  const total = Object.values(hero.hardware.pooled_raw_counts).reduce((a, b) => a + b, 0);
  const bins = 256;
  const x0 = 54;
  const x1 = W - 12;
  const base = H - 46;
  const top = 24;
  const bw = (x1 - x0) / bins;
  const peak = 0.25; // y axis top, probability
  const yOf = (p: number) => r2(base - Math.min(p / peak, 1) * (base - top));
  const hw = hero.hardware.pooled_raw_counts as Record<string, number>;
  const ideal = hero.ideal.probabilities as Record<string, number>;
  const res = hero.resolution;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Histogram of measurement outcomes: the ideal peaks in grey and the counts measured on ibm_kingston in cyan" className="hero-svg">
      <line x1={x0} x2={x1} y1={base} y2={base} stroke="var(--line)" />
      <line x1={x0} x2={x0} y1={top} y2={base} stroke="var(--line)" />
      <g data-axis fill="var(--text-2)" fontSize="12" fontFamily="var(--font-mono)">
        <text x={x0 - 6} y={base + 4} textAnchor="end">0</text>
        <text x={x0 - 6} y={r2((base + top) / 2) + 4} textAnchor="end">0.125</text>
        <text x={x0 - 6} y={top + 4} textAnchor="end">0.25</text>
        <text x={x0} y={base + 18}>00000000</text>
        <text x={x1} y={base + 18} textAnchor="end">11111111</text>
      </g>
      <text x={(x0 + x1) / 2} y={H - 6} textAnchor="middle" fill="var(--text-2)" fontSize="13">
        measured outcome (the phase register, as a bitstring)
      </text>
      <g className="h-bars-hw">
        {Array.from({ length: bins }, (_, v) => {
          const key = v.toString(2).padStart(8, "0");
          const c = hw[key] ?? 0;
          if (c === 0) return null;
          const y = yOf(c / total);
          return <rect key={key} x={r2(x0 + v * bw)} y={y} width={r2(Math.max(bw - 0.4, 0.8))} height={r2(base - y)} fill="var(--q)" opacity={res && key === res.bitstring ? 1 : 0.8} />;
        })}
      </g>
      <g className="h-bars-ideal">
        {Object.entries(ideal).map(([key, p]) => {
          const v = Number.parseInt(key, 2);
          const y = yOf(p);
          return <rect key={key} x={r2(x0 + v * bw - 1)} y={y} width={r2(bw + 2)} height={r2(base - y)} fill="var(--sim)" opacity="0.9" />;
        })}
      </g>
    </svg>
  );
}

function PadlockSvg() {
  return (
    <svg viewBox="0 0 140 170" role="img" aria-label="An RSA padlock fracturing along a crack line" className="hero-lock">
      <g className="lock-left">
        <path d="M 30 70 H 66 L 74 84 L 62 100 L 72 118 L 66 148 H 30 Z" fill="var(--bg-2)" stroke="var(--threat)" strokeWidth="2" />
        <path d="M 40 70 V 48 A 30 30 0 0 1 70 18" fill="none" stroke="var(--threat)" strokeWidth="6" strokeLinecap="round" />
      </g>
      <g className="lock-right">
        <path d="M 66 70 H 110 V 148 H 66 L 72 118 L 62 100 L 74 84 Z" fill="var(--bg-2)" stroke="var(--threat)" strokeWidth="2" />
        <path d="M 70 18 A 30 30 0 0 1 100 48 V 70" fill="none" stroke="var(--threat)" strokeWidth="6" strokeLinecap="round" />
      </g>
      <path className="lock-crack" d="M 66 70 L 74 84 L 62 100 L 72 118 L 66 148" fill="none" stroke="var(--warn)" strokeWidth="2" pathLength={1} />
    </svg>
  );
}

function LatticeSvg() {
  const cols = 9;
  const rows = 5;
  const gx = 62;
  const gy = 50;
  const ox = (W - (cols - 1) * gx) / 2;
  const oy = 46;
  const pts: { x: number; y: number; i: number }[] = [];
  for (let r = 0; r < rows; r += 1) for (let c = 0; c < cols; c += 1) pts.push({ x: ox + c * gx + (r % 2) * 0, y: oy + r * gy, i: r * cols + c });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Fragments re-forming into a lattice grid that locks shut, tinted for post-quantum safety" className="hero-svg">
      <g stroke="var(--pqc)" strokeWidth="1" opacity="0.7" className="lat-lines">
        {pts.map((p) => (p.i % cols < cols - 1 ? <line key={`h${p.i}`} x1={p.x} y1={p.y} x2={p.x + gx} y2={p.y} /> : null))}
        {pts.map((p) => (p.i < cols * (rows - 1) ? <line key={`v${p.i}`} x1={p.x} y1={p.y} x2={p.x} y2={p.y + gy} /> : null))}
      </g>
      {pts.map((p) => (
        <circle key={p.i} className="lat-dot" data-i={p.i} cx={r2(p.x)} cy={r2(p.y)} r="5" fill="var(--pqc)" />
      ))}
    </svg>
  );
}

export function Hero() {
  const stage = useRef<HTMLDivElement>(null);
  // This component only renders in the browser. With motion, hidden layers are inert (no focus,
  // not read out) until the timeline reveals them; the reduced-motion strip is all visible.
  const after = document.getElementById("hero-after"); // the second caption and the technical layer sit at the end of the sequence
  const motion = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const replay = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let killed = false;
    let revert: (() => void) | undefined;
    void (async () => {
      const [{ default: gsap }, { ScrollTrigger }] = await Promise.all([import("gsap"), import("gsap/ScrollTrigger")]);
      const wrapEl = document.querySelector<HTMLElement>(".hero-runway");
      if (killed || !wrapEl || !stage.current) return;
      gsap.registerPlugin(ScrollTrigger);
      // The set-up is split into steps with a yield between them, so no single task runs long
      // (the budget is 50 ms per task at a 4x throttle). ctx.add keeps every step in one context,
      // so one revert cleans up all of it.
      const ctx = gsap.context(() => undefined, stage);
      revert = () => ctx.revert();
      const q = gsap.utils.selector(stage.current);
      const layers = ["circuit", "counts", "factors", "lattice"].map((k) => q(`[data-layer="${k}"]`)[0]);
      const scale = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--motion-scale")) || 1;
      const tl = gsap.timeline({ paused: true, defaults: { ease: "expo.out" } });

      await yieldToMain();
      if (killed) return;
      ctx.add(() => {
        gsap.set(layers, { opacity: 0 });
        gsap.set(q(".h-wire"), { strokeDasharray: 1, strokeDashoffset: 1 });
        gsap.set(q(".h-gate"), { opacity: 0 });
        gsap.set(q(".fact-line"), { opacity: 0, y: 8 });
        gsap.set(q(".lock-crack"), { strokeDasharray: 1, strokeDashoffset: 1 });
        gsap.set(q(".lat-lines"), { opacity: 0 });
        gsap.set(q(".lat-caption"), { opacity: 0 });
      });
      await yieldToMain();
      if (killed) return;
      ctx.add(() => {
        gsap.set(q(".h-bars-hw rect, .h-bars-ideal rect"), { scaleY: 0, transformOrigin: "50% 100%" });
        gsap.set(q(".lat-dot"), { opacity: 0, scale: 0, transformOrigin: "50% 50%" });
      });
      await yieldToMain();
      if (killed) return;
      ctx.add(() => {
        // 1. the circuit draws itself, wire by wire; gates light up as a pulse passes
        tl.to(layers[0] ?? [], { opacity: 1, duration: 0.3 }, 0)
          .to(q(".h-wire"), { strokeDashoffset: 0, duration: 1.1, stagger: 0.04, ease: "power1.out" }, 0.1)
          .to(q(".h-gate"), { opacity: 1, duration: 0.3, stagger: 0.045 }, 0.5)
          .to(layers[0] ?? [], { opacity: 0, duration: 0.3 }, 2.3)
          // 2. measurement: the bars rise to the real counts beside the ideal ones
          .to(layers[1] ?? [], { opacity: 1, duration: 0.3 }, 2.4)
          .to(q(".h-bars-ideal rect"), { scaleY: 1, duration: 0.8 }, 2.6);
      });
      await yieldToMain();
      if (killed) return;
      ctx.add(() => {
        tl.to(q(".h-bars-hw rect"), { scaleY: 1, duration: 0.9, stagger: { each: 0.002, from: "random" } }, 3.0)
          .to(layers[1] ?? [], { opacity: 0, duration: 0.3 }, 4.5);
      });
      await yieldToMain();
      if (killed) return;
      ctx.add(() => {
        // 3. the classical step: continued fractions find r, the factors appear, the padlock cracks
        tl.to(layers[2] ?? [], { opacity: 1, duration: 0.3 }, 4.6)
          .to(q(".fact-line"), { opacity: 1, y: 0, duration: 0.5, stagger: 0.35 }, 4.8)
          .to(q(".lock-crack"), { strokeDashoffset: 0, duration: 0.5 }, 5.9)
          .to(q(".lock-left"), { x: -14, rotation: -6, transformOrigin: "100% 100%", duration: 0.6 }, 6.2)
          .to(q(".lock-right"), { x: 14, rotation: 6, transformOrigin: "0% 100%", duration: 0.6 }, 6.2)
          .to(layers[2] ?? [], { opacity: 0, duration: 0.3 }, 6.9)
          // 4. the pieces re-tile into a lattice that locks shut
          .to(layers[3] ?? [], { opacity: 1, duration: 0.3 }, 7.0);
      });
      await yieldToMain();
      if (killed) return;
      ctx.add(() => {
        tl.to(q(".lat-dot"), { opacity: 1, scale: 1, duration: 0.5, stagger: { each: 0.02, from: "center" } }, 7.1)
          .to(q(".lat-lines"), { opacity: 1, duration: 0.6 }, 7.8)
          .to(q(".lat-caption"), { opacity: 1, duration: 0.5 }, 8.3);
        // One global motion scale (--motion-scale): a larger value is slower.
        tl.timeScale(1 / scale);
        tl.progress(0);
      });
      await yieldToMain();
      if (killed) return;
      ctx.add(() => {
        // a layer takes focus only while it is on screen (times are the timeline's own, in seconds)
        const shows = [[0, 2.6], [2.4, 4.8], [4.6, 7.2], [7.0, Number.POSITIVE_INFINITY]] as const;
        const syncInert = () => {
          const t = tl.time();
          layers.forEach((el, i) => {
            const [from, to] = shows[i] ?? [0, 0];
            if (el) (el as HTMLElement).inert = !(t >= from && t < to);
          });
        };
        syncInert();
        let replaying = false;
        ScrollTrigger.create({
          trigger: wrapEl,
          start: "top top",
          // the sequence ends when the pinned stage's bottom meets the runway's bottom, so the
          // captions that follow come straight after it
          end: () => `bottom top+=${stage.current?.parentElement?.offsetHeight ?? 0}`,
          invalidateOnRefresh: true,
          onUpdate: (self) => {
            if (!replaying) tl.progress(self.progress);
            syncInert();
          },
        });
        replay.current = () => {
          replaying = true;
          gsap.fromTo(tl, { progress: 0 }, { progress: 1, duration: tl.duration() * scale, ease: "none", onUpdate: syncInert, onComplete: () => (replaying = false) });
        };
      });
    })();
    return () => {
      killed = true;
      revert?.();
      replay.current = null;
    };
  }, []);

  const res = hero.resolution;
  return (
    <div ref={stage} className="hero-body">
        <div className="hero-layers">
          <div data-layer="circuit" className="hero-layer">
            <p className="hero-step">First, the circuit</p>
            <CircuitSvg />
          </div>
          <div data-layer="counts" className="hero-layer" inert={motion}>
            <p className="hero-step">
              Measured on <Traced src="herostrip:hardware.backend" />, on{" "}
              <Traced src="herostrip:hardware.jobs[0].finished_date" />, next to the ideal outcome
            </p>
            <HistogramSvg />
          </div>
          <div data-layer="factors" className="hero-layer" inert={motion}>
            <p className="hero-step">Then a classical step</p>
            <div className="hero-factors">
              <PadlockSvg />
              {res ? (
                <ol className="fact-list">
                  <li className="fact-line">
                    Outcome <Traced src="herostrip:resolution.bitstring" /> is{" "}
                    <Fig src="herostrip:resolution.measured" label="hardware" note="Read as a binary number." /> out of{" "}
                    <Fig src="herostrip:resolution.denominator" label="computed from data" />
                  </li>
                  <li className="fact-line">
                    <Gloss term="continued">Continued fractions</Gloss> give{" "}
                    <Fig src="herostrip:resolution.convergents[2][0]" label="computed from data" />/
                    <Fig src="herostrip:resolution.convergents[2][1]" label="computed from data" />
                  </li>
                  <li className="fact-line">
                    The order is <Fig src="herostrip:resolution.order" label="computed from data" />
                  </li>
                  <li className="fact-line">
                    <Fig src="herostrip:resolution.n" label="computed from data" /> ={" "}
                    <Fig src="herostrip:resolution.factors[0]" label="computed from data" /> ×{" "}
                    <Fig src="herostrip:resolution.factors[1]" label="computed from data" />
                  </li>
                </ol>
              ) : null}
            </div>
          </div>
          <div data-layer="lattice" className="hero-layer" inert={motion}>
            <p className="hero-step">The pieces re-form into a lattice that holds</p>
            <LatticeSvg />
            <p className="lat-caption hero-caption"><Gloss term="mlkem">ML-KEM</Gloss>: what to migrate to.</p>
          </div>
        </div>
        <div className="hero-caption-row">
          <div className="hero-notes">
          <p>
            This is a <Gloss term="compiled">simplified demo version</Gloss> of Shor&apos;s algorithm, the quantum attack on{" "}
            <Gloss term="rsa">RSA</Gloss> encryption. To fit on today&apos;s small quantum computers, part of the answer was built in. So
            it shows how the attack works, not a real attack.
          </p>
          </div>
          <button type="button" className="btn hero-replay" onClick={() => replay.current?.()}>
            Replay the sequence
          </button>
        </div>
        {after
          ? createPortal(
              <>
                <div className="hero-notes">
          <p>
            We ran it on IBM&apos;s real quantum computer, <Traced src="herostrip:hardware.backend" />, in a{" "}
            <Gloss term="transpiled">transpiled</Gloss> form made for that chip. A run counts as a success when it finds the repeating
            pattern: here a period of <Traced src="herostrip:resolution.order" /> for a = <Traced src="herostrip:resolution.a" />. That period splits{" "}
            <Traced src="herostrip:resolution.n" /> into <Traced src="herostrip:resolution.factors[0]" /> × <Traced src="herostrip:resolution.factors[1]" />.
          </p>
                </div>
        <Tech>
          <p style={{ margin: "0 0 0.5rem" }}>
            Registry label: <Traced src="herostrip:circuit.kind" />. <Traced src="herostrip:notes.compiled" />
          </p>
          <p style={{ margin: 0 }}>
            <Traced src="herostrip:notes.hardware" /> <Traced src="herostrip:notes.success" />
          </p>
        </Tech>
              </>,
              after,
            )
          : null}
    </div>
  );
}
