"use client";

// Easter eggs (spec §7). Lazy, no network. Everything here is classical and labelled as such:
//  - Konami code: Q-Day mode          - type "shor" / "grover": classical simulations in the browser
//  - click |ψ⟩ in the footer: a bit drawn from the measured counts of a real ibm_kingston job
//  - console: an ASCII Bloch sphere and a tiny-RSA capture-the-flag  - hold Shift: shortest vector
// The numbers in this file are the eggs' own (computed in the browser), not project results, so
// each carries data-literal with that reason.
import { useCallback, useEffect, useRef, useState } from "react";
import hero from "../../../public/data/hero.json";
import { pending } from "../../lib/interaction";

const KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a"];
const LIT = "easter egg value, computed in the browser";

type Result =
  | { kind: "shor"; rows: { n: number; a: number; r: number; p: number; q: number }[] }
  | { kind: "grover"; n: number; key: number; steps: number; bound: number; trace: number[]; shown: number }
  | { kind: "coin"; job: string; outcome: string; bit: string }
  | null;

// ---- Shor (classical simulation) ------------------------------------------------------------
function orderOf(a: number, n: number): number {
  let r = 1;
  let x = a % n;
  while (x !== 1) {
    x = (x * a) % n;
    r += 1;
  }
  return r;
}
const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b));
function powmod(b: number, e: number, m: number): number {
  let r = 1;
  let x = b % m;
  let k = e;
  while (k > 0) {
    if (k & 1) r = (r * x) % m;
    x = (x * x) % m;
    k >>= 1;
  }
  return r;
}
function factorWith(n: number, a: number): { a: number; r: number; p: number; q: number } | null {
  const r = orderOf(a, n);
  if (r % 2) return null;
  const h = powmod(a, r / 2, n);
  if (h === n - 1) return null;
  const p = gcd(h - 1, n);
  if (p === 1 || p === n) return null;
  return { a, r, p: Math.min(p, n / p), q: Math.max(p, n / p) };
}
const PRIMES = [101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157, 163, 167, 173, 179, 181, 191, 193, 197, 199];
function randomSemiprime(): { n: number; a: number; r: number; p: number; q: number } {
  for (;;) {
    const p = PRIMES[Math.floor(Math.random() * PRIMES.length)] ?? 101;
    const q = PRIMES[Math.floor(Math.random() * PRIMES.length)] ?? 103;
    if (p === q) continue;
    const n = p * q;
    const a = 2 + Math.floor(Math.random() * (n - 3));
    if (gcd(a, n) !== 1) continue;
    const f = factorWith(n, a);
    if (f) return { n, ...f };
  }
}

// ---- Grover (classical simulation of amplitudes) --------------------------------------------
function groverTrace(size: number, key: number): { steps: number; trace: number[]; found: number } {
  const steps = Math.floor((Math.PI / 4) * Math.sqrt(size));
  let amp = new Array<number>(size).fill(1 / Math.sqrt(size));
  const trace: number[] = [amp[key] ?? 0];
  for (let s = 0; s < steps; s += 1) {
    amp = amp.map((a, i) => (i === key ? -a : a)); // oracle
    const mean = amp.reduce((x, y) => x + y, 0) / size;
    amp = amp.map((a) => 2 * mean - a); // diffusion
    trace.push(amp[key] ?? 0);
  }
  let found = 0;
  amp.forEach((a, i) => {
    if (Math.abs(a) > Math.abs(amp[found] ?? 0)) found = i;
  });
  return { steps, trace, found };
}

// ---- the quantum coin ----------------------------------------------------------------------
function drawFromJob(): { job: string; outcome: string; bit: string } {
  const jobs = hero.hardware.jobs;
  const j = jobs[Math.floor(Math.random() * jobs.length)] ?? jobs[0];
  const counts = (j?.counts ?? {}) as Record<string, number>;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  let pick = Math.random() * total;
  let outcome = Object.keys(counts)[0] ?? "0";
  for (const [k, v] of Object.entries(counts)) {
    pick -= v;
    if (pick < 0) {
      outcome = k;
      break;
    }
  }
  return { job: j?.job_id ?? "", outcome, bit: outcome.slice(-1) };
}

// ---- console: Bloch sphere and a tiny-RSA CTF -----------------------------------------------
function consoleEgg(): void {
  const bloch = [
    "         |0>",
    "          .  z",
    "       .  |  .",
    "     .    |    .",
    "  -x ----(  )---- +x",
    "     .    |    .",
    "       .  |  .",
    "          .",
    "         |1>",
  ].join("\n");
  const p = 61;
  const q = 53;
  const n = p * q;
  const e = 17;
  const m = 1234;
  const c = powmod(m, e, n);
  const flag = "QDAY{shor_would_have_been_faster}";
  console.info(`%cQ-Day Radar%c\nA qubit on the Bloch sphere:\n${bloch}\n`, "font-weight:700", "");
  console.info(
    `Capture the flag. A message was encrypted with a deliberately tiny RSA key.\n  n = ${n}\n  e = ${e}\n  c = ${c}\nFactor n, find the private exponent, decrypt c, then call qday.flag(m).`,
  );
  (window as Window & { qday?: unknown }).qday = { flag: (x: number) => (x === m ? flag : "not the message") };
}

function useKeys(onCode: (code: "konami" | "shor" | "grover") => void) {
  const buf = useRef<string[]>([]);
  useEffect(() => {
    const push = (key: string) => {
      buf.current = [...buf.current, key].slice(-KONAMI.length);
      const seq = buf.current;
      if (seq.length === KONAMI.length && seq.every((k, i) => k === KONAMI[i])) onCode("konami");
      const text = seq.filter((k) => k.length === 1).join("");
      if (text.endsWith("shor")) onCode("shor");
      if (text.endsWith("grover")) onCode("grover");
    };
    // keys typed while this chunk was loading
    pending.keys.forEach(push);
    pending.keys = [];
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      push(e.key.length === 1 ? e.key.toLowerCase() : e.key);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCode]);
}

export function Eggs() {
  const [result, setResult] = useState<Result>(() => {
    if (!pending.coin) return null; // the coin was clicked while this chunk loaded: replay it
    pending.coin = false;
    return { kind: "coin", ...drawFromJob() };
  });
  const [qday, setQday] = useState(false);
  const [shift, setShift] = useState<{ x: number; y: number } | null>(null);
  const shiftDown = useRef(false);
  const pointer = useRef({ x: 0, y: 0 });

  useEffect(() => {
    document.documentElement.dataset.eggs = "ready";
    consoleEgg();
    return () => {
      delete document.documentElement.dataset.eggs;
    };
  }, []);

  useEffect(() => {
    if (qday) document.documentElement.dataset.qday = "on";
    else delete document.documentElement.dataset.qday;
  }, [qday]);

  const onCode = useCallback((code: "konami" | "shor" | "grover") => {
    if (code === "konami") setQday((v) => !v);
    if (code === "shor") {
      const textbook = factorWith(15, 7);
      const rows = [{ n: 15, ...(textbook ?? { a: 7, r: 4, p: 3, q: 5 }) }, randomSemiprime()];
      setResult({ kind: "shor", rows });
    }
    if (code === "grover") {
      const size = 256;
      const key = Math.floor(Math.random() * size);
      const g = groverTrace(size, key);
      // reduced motion: no stepping, the answer is there at once
      const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      setResult({ kind: "grover", n: size, key: g.found, steps: g.steps, bound: Math.ceil((Math.PI / 4) * Math.sqrt(size)), trace: g.trace, shown: still ? g.trace.length - 1 : 0 });
    }
  }, []);
  useKeys(onCode);

  // the coin in the footer (a click that arrived while this chunk loaded is replayed)
  useEffect(() => {

    const onClick = (e: MouseEvent) => {
      if ((e.target as HTMLElement | null)?.closest('[data-egg="coin"]')) setResult({ kind: "coin", ...drawFromJob() });
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);

  // Escape closes the card
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setResult(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Shift over the background: the shortest lattice vector at the pointer
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "Shift") {
        shiftDown.current = true;
        setShift({ ...pointer.current });
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.key === "Shift") {
        shiftDown.current = false;
        setShift(null);
      }
    };
    const move = (e: PointerEvent) => {
      pointer.current = { x: e.clientX, y: e.clientY };
      if (shiftDown.current) setShift({ x: e.clientX, y: e.clientY });
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("pointermove", move, { passive: true });
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("pointermove", move);
    };
  }, []);

  // Grover: step through the amplitudes
  const grover = result?.kind === "grover" ? result : null;
  useEffect(() => {
    if (!grover || grover.shown >= grover.trace.length - 1) return;
    const t = window.setTimeout(() => setResult({ ...grover, shown: grover.shown + 1 }), 160);
    return () => window.clearTimeout(t);
  }, [grover]);

  return (
    <>
      {qday ? (
        <div className="egg-banner" role="status">
          harvest-now-decrypt-later: engaged
        </div>
      ) : null}
      {shift ? (
        <div className="egg-vector" style={{ left: shift.x, top: shift.y }} aria-hidden="true">
          <svg width="140" height="48" viewBox="0 0 140 48">
            <line x1="6" y1="24" x2="46" y2="24" stroke="var(--warn)" strokeWidth="2.5" />
            <path d="M 46 24 l -7 -5 v 10 z" fill="var(--warn)" />
            <circle cx="6" cy="24" r="3.5" fill="var(--warn)" />
          </svg>
          <span>Easy in 2D. Try <span data-literal="easter egg text: the dimension of a typical lattice scheme">768</span> dimensions.</span>
        </div>
      ) : null}
      {result ? (
        <aside className="egg-card card" role="status" aria-label="Easter egg" data-egg-result={result.kind}
          {...(result.kind === "coin" ? { "data-job": result.job, "data-outcome": result.outcome, "data-bit": result.bit } : {})}
          {...(result.kind === "grover" ? { "data-n": result.n, "data-key": result.key, "data-steps": result.steps, "data-bound": result.bound } : {})}
        >
          <button type="button" className="egg-close" onClick={() => setResult(null)} aria-label="Close">
            Close
          </button>
          {result.kind === "shor" ? (
            <>
              <p className="muted" style={{ margin: 0 }}>Classical simulation in your browser: the period is found by trial, not by a quantum computer.</p>
              {result.rows.map((r) => (
                <p key={r.n} style={{ margin: "0.4rem 0 0" }} data-egg-row="shor" data-n={r.n} data-a={r.a} data-r={r.r} data-p={r.p} data-q={r.q}>
                  <span data-literal={LIT}>{r.n}</span> = <span data-literal={LIT}>{r.p}</span> × <span data-literal={LIT}>{r.q}</span>
                  {" "}(base <span data-literal={LIT}>{r.a}</span>, period <span data-literal={LIT}>{r.r}</span>)
                </p>
              ))}
            </>
          ) : null}
          {result.kind === "grover" ? (
            <>
              <p className="muted" style={{ margin: 0 }}>Classical simulation in your browser: Grover&apos;s amplitudes over a hidden key, found in about the square root of the key space.</p>
              <div className="grover-grid" aria-hidden="true">
                {Array.from({ length: result.n }, (_, i) => (
                  <i key={i} className={i === result.key && result.shown >= result.trace.length - 1 ? "hit" : ""}
                    style={{ opacity: i === result.key ? 0.15 + 0.85 * Math.abs(result.trace[result.shown] ?? 0) : 0.15 }} />
                ))}
              </div>
              <p style={{ margin: 0 }}>
                {result.shown >= result.trace.length - 1 ? (
                  <>Key <span data-literal={LIT}>{result.key}</span> found in <span data-literal={LIT}>{result.steps}</span> steps (at most <span data-literal={LIT}>{result.bound}</span> for <span data-literal={LIT}>{result.n}</span> keys).</>
                ) : (
                  <>Amplifying…</>
                )}
              </p>
            </>
          ) : null}
          {result.kind === "coin" ? (
            <p style={{ margin: 0 }}>
              Bit <span data-literal={LIT}>{result.bit}</span>: a bit drawn from the measured counts of job{" "}
              <code>{result.job}</code> on ibm_kingston (outcome <span data-literal={LIT}>{result.outcome}</span>). Replayed from stored counts, not a live measurement.
            </p>
          ) : null}
        </aside>
      ) : null}
    </>
  );
}
