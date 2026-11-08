"use client";

import { useState } from "react";
import lab from "../../../public/data/lab.json";
import { register, resolve } from "../../lib/data";
import { Fig, type ProvLabel } from "../Fig";
import { Traced } from "../Traced";
import { Gloss } from "../Gloss";
import { Tech } from "../Tech";

register("lab", lab);

type Mode = "all" | "ideal" | "noisy" | "hardware";
const MODES: { id: Mode; name: string }[] = [
  { id: "all", name: "All three" },
  { id: "ideal", name: "Ideal simulator" },
  { id: "noisy", name: "Noisy simulator" },
  { id: "hardware", name: "Hardware" },
];

interface Bar {
  key: string;
  title: string;
  tag: string;
  colour: string;
  label: ProvLabel;
  value: string; // data path for the success probability
  lo?: string;
  hi?: string;
  extras: { name: string; src: string; digits?: number }[];
  note: string;
}

function bars(ci: number, mode: Mode): Bar[] {
  const c = lab.circuits[ci];
  if (!c) return [];
  const p = `circuits[${ci}]`;
  const out: Bar[] = [];
  if (mode === "all" || mode === "ideal") {
    out.push({
      key: "ideal",
      title: "Ideal simulator",
      tag: "simulated",
      colour: "var(--sim)",
      label: "simulated",
      value: `${p}.ideal.success_probability`,
      extras: [
        { name: "Shots", src: `lab:${p}.ideal.shots` },
        { name: "Seed", src: `lab:${p}.ideal.seed_simulator` },
      ],
      note: "A noiseless simulator: what the circuit does on a perfect machine.",
    });
  }
  if (mode === "all" || mode === "noisy") {
    out.push({
      key: "noisy",
      title: "Noisy simulator",
      tag: "simulated",
      colour: "var(--sim)",
      label: "simulated",
      value: `${p}.noisy.success_probability`,
      lo: `${p}.noisy.wilson_95[0]`,
      hi: `${p}.noisy.wilson_95[1]`,
      extras: [
        { name: "Shots", src: `lab:${p}.noisy.shots` },
        { name: "Seed", src: `lab:${p}.noisy.seed_simulator` },
      ],
      note: "A simulator carrying the noise model of a snapshot of ibm_kingston. Not a hardware result.",
    });
  }
  if (mode === "all" || mode === "hardware") {
    c.hardware.forEach((h, hi) => {
      const q = `${p}.hardware[${hi}]`;
      out.push({
        key: `hw-${h.config}`,
        title: `Hardware, ${h.config}`,
        tag: "hardware",
        colour: "var(--q)",
        label: "hardware",
        value: `${q}.success_probability`,
        lo: `${q}.wilson_95[0]`,
        hi: `${q}.wilson_95[1]`,
        extras: [
          { name: "Shots pooled", src: `lab:${q}.shots_pooled` },
          { name: "Predicted by the noisy simulator", src: `lab:${q}.predicted_success`, digits: 3 },
        ],
        note: "Measured on ibm_kingston. The line shows the 95% Wilson interval for the shot noise.",
      });
    });
  }
  return out;
}

export function LabView() {
  const [mode, setMode] = useState<Mode>("all");
  const firstCompiled = lab.circuits.findIndex((c) => c.kind === "compiled");
  return (
    <section aria-labelledby="lab-h">
      <h1 id="lab-h" style={{ fontSize: "2rem", marginBlock: "0 0.5rem" }}>
        Lab
      </h1>
      <p className="muted">
        We ran small quantum attacks three ways: on a perfect <Gloss term="simulator">simulator</Gloss>,
        on a simulator that copies the noise of a real chip, and on IBM&apos;s real quantum
        computer, ibm_kingston.
      </p>
      <p className="muted">
        The attacks are <Gloss term="shor">Shor&apos;s method</Gloss>, which breaks{" "}
        <Gloss term="rsa">RSA</Gloss>, and <Gloss term="grover">Grover&apos;s method</Gloss>, which
        searches for a secret key. Each bar shows how often an attack found the right answer. The
        dashed line is the <Gloss term="chance">score from random guessing</Gloss>.
      </p>
      <p>
        <Fig src="lab:hardware_summary.ran" label="hardware" /> circuits ran on the real machine.{" "}
        <Fig src="lab:hardware_summary.above" label="hardware" /> scored above random guessing.{" "}
        <Fig src="lab:hardware_summary.no_better" label="hardware" /> did no better than random guessing.
      </p>
      <Tech>
        <p style={{ margin: "0 0 0.5rem" }}>
          A circuit is <em>compiled</em> when its multiplications are built for one fixed problem, so
          the answer is built in; it is <em>generic</em> when it works for any input. Hardware runs
          use three settings: raw, dd (dynamical decoupling) and dd_twirl (decoupling with Pauli
          twirling). The thin line on a bar is the Wilson confidence interval for shot noise.
        </p>
        <p style={{ margin: 0 }}>
          Hardware batch <Traced src="lab:hardware_batch" />, run once with the human&apos;s approval.
          The noisy simulator carries the noise model of a snapshot of ibm_kingston.
        </p>
      </Tech>
      <div role="group" aria-label="Which runs to show" className="seg" style={{ marginBlock: "1rem" }}>
        {MODES.map((m) => (
          <button key={m.id} type="button" aria-pressed={mode === m.id} onClick={() => setMode(m.id)}>
            {m.name}
          </button>
        ))}
      </div>
      <div className="lab-grid">
        {lab.circuits.map((c, ci) => {
          const p = `circuits[${ci}]`;
          return (
            <article key={c.name} className="card" aria-labelledby={`c-${ci}`}>
              <h2 id={`c-${ci}`} style={{ fontSize: "1.125rem", marginBlock: "0 0.25rem" }}>
                <Traced src={`lab:${p}.name`} />
              </h2>
              <p className="muted" style={{ margin: "0 0 0.75rem", fontSize: "0.875rem" }}>
                {c.kind === "compiled" ? (
                  ci === firstCompiled ? <Gloss term="compiled">A simplified demo version.</Gloss> : "A simplified demo version."
                ) : (
                  "A general-purpose version."
                )}{" "}
                {c.hardware_best ? (
                  <>
                    On the real machine its best run scored{" "}
                    <Fig src={`lab:${p}.hardware_best.success_probability`} scale={100} digits={1} unit="%" label="hardware"
                      note="The share of shots that found the right answer." />
                    . Random guessing scores{" "}
                    <Fig src={`lab:${p}.hardware_best.chance_baseline`} scale={100} digits={1} unit="%" label="computed from data" />
                    , so it was <Traced src={`lab:${p}.hardware_best.verdict`} />. It closed{" "}
                    <Fig src={`lab:${p}.hardware_best.normalized_score`} scale={100} digits={1} unit="%" label="hardware"
                      note="The share of the gap between random guessing and a perfect score." />{" "}
                    of the gap to a perfect score.
                  </>
                ) : (
                  "It was not run on the real machine."
                )}
              </p>
              {bars(ci, mode).length === 0 ? (
                <p className="muted">No hardware run for this circuit.</p>
              ) : null}
              <div className="bars">
                {bars(ci, mode).map((b) => (
                  <div className="barrow" key={b.key}>
                    <div className="barlabel">
                      {b.title}
                      <span className="chip" style={{ color: b.tag === "hardware" ? "var(--q)" : "var(--sim-text)" }}>
                        {b.tag}
                      </span>
                    </div>
                    <div className="track">
                      <BarGeometry ci={ci} bar={b} chance={`${p}.ideal.chance_baseline`} />
                    </div>
                    <div className="barval">
                      <Fig src={`lab:${b.value}`} digits={3} label={b.label} note={b.note} extra={b.extras} />
                    </div>
                  </div>
                ))}
              </div>
              <div className="axis" aria-hidden="true">
                <span data-axis>0</span>
                <span data-axis>0.5</span>
                <span data-axis>1</span>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}


/** Sets the bar width, the interval whisker and the chance line from the data (as percentages). */
function BarGeometry({ bar, chance }: { ci: number; bar: Bar; chance: string }) {
  const v = Number(resolve("lab", bar.value));
  const lo = bar.lo ? Number(resolve("lab", bar.lo)) : null;
  const hi = bar.hi ? Number(resolve("lab", bar.hi)) : null;
  const ch = Number(resolve("lab", chance));
  return (
    <>
      <div className="fill" style={{ width: `${v * 100}%`, background: bar.colour }} />
      {lo !== null && hi !== null ? (
        <div className="whisker" style={{ left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }} />
      ) : null}
      <div className="chance" style={{ left: `${ch * 100}%` }} />
    </>
  );
}
