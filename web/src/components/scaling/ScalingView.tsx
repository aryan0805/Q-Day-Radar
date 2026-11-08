"use client";

import lab from "../../../public/data/lab.json";
import scaling from "../../../public/data/scaling.json";
import { register, scenarios } from "../../lib/data";
import { sci } from "../../lib/format";
import { useScenario } from "../../lib/scenario";
import { Fig } from "../Fig";
import { Traced } from "../Traced";
import { Gloss } from "../Gloss";
import { Tech } from "../Tech";
import { ScenarioNote } from "../ScenarioNote";

register("lab", lab);
register("scaling", scaling);

const W = 640;
const H = 340;
const BH = 235;
const M = { l: 62, r: 20, t: 16, b: 38 };

function scale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  // Rounded: Math.log10 can differ in the last digit between the build and the browser, which
  // would be a hydration mismatch.
  return (v: number) =>
    Math.round((r0 + ((Math.log10(v) - Math.log10(d0)) / (Math.log10(d1) - Math.log10(d0))) * (r1 - r0)) * 100) / 100;
}

const COST_SERIES = [
  { estimator: "qdk", colour: "var(--warn)", name: "QDK estimator" },
  { estimator: "qualtran", colour: "var(--q)", name: "Qualtran estimator" },
] as const;

function costFit(estimator: string): number {
  return scaling.fits.findIndex((f) => f.estimator === estimator && f.quantity === "toffoli_equiv" && f.selected);
}

export function ScalingView() {
  const { scenario } = useScenario();
  return (
    <section aria-labelledby="sc-h">
      <h1 id="sc-h" style={{ fontSize: "2rem", marginBlock: "0 0.5rem" }}>
        Scaling
      </h1>
      <p className="muted">
        Breaking real encryption takes a far bigger quantum computer than anything built today. The
        left chart shows how the cost of an attack grows as keys get longer. The right chart compares
        the size needed with real chips.
      </p>
      <ScenarioNote />
      {(["rsa2048", "ecc256"] as const).map((k, n) => {
        const t = scenarios.timeline.scenarios[scenario].targets[k];
        const base = `scenarios:timeline.scenarios.${scenario}.targets.${k}`;
        return (
          <p key={k}>
            Breaking {k === "rsa2048" ? <Gloss term="rsa">RSA-2048</Gloss> : <Gloss term="ecc">ECC-256</Gloss>} would need about{" "}
            <Fig src={`${base}.physical_qubits`} group digits={0} label={t.physical_source === "model" ? "model estimate" : "published estimate"}
              note={`Source: ${t.physical_source}${t.physical_bound ? `, an ${t.physical_bound} bound` : ""}`} />{" "}
            {n === 0 ? <Gloss term="qubit">qubits</Gloss> : "qubits"}. That is about{" "}
            <Fig src={`scenarios:gaps.${scenario}.${k}.over_device`} group digits={0} label="computed from data" /> times more than
            ibm_kingston, the chip we ran on, which has <Fig src="lab:device.n_qubits" group digits={0} label="hardware" />. It is also about{" "}
            <Fig src={`scenarios:gaps.${scenario}.${k}.over_record`} group digits={0} label="computed from data" /> times more than the
            largest chip built so far, which has <Fig src="scenarios:timeline.baseline.qubits" group digits={0} label="published estimate" />. The
            attack would run for about{" "}
            <Fig src={`${base}.runtime_seconds`} scale={1 / 86400} digits={1} unit="days" label="model estimate" />.{" "}
            {t.crqc_year === null ? (
              <>That is longer than the limit we set, so we give no year.</>
            ) : (
              <>
                A chip that big could exist around{" "}
                <Fig src={`${base}.crqc_year`} digits={0} label="trend extrapolation"
                  extra={[{ name: "Trend holdout error (%):", src: "scenarios:timeline.fit.holdout.rel_error", scale: 100, digits: 0 }]} />
                . That is {n === 0 ? <Gloss term="trend">an estimate from a trend line, not a measurement</Gloss> : "an estimate from a trend line, not a measurement"}.
              </>
            )}
          </p>
        );
      })}
      <div className="scale-grid">
        <CostChart />
        <BraceChart scenario={scenario} />
      </div>
    </section>
  );
}

function CostChart() {
  const idx = COST_SERIES.map((s) => costFit(s.estimator));
  const all = idx.flatMap((i) => {
    const f = scaling.fits[i];
    return f ? f.points.map((p) => p.value) : [];
  });
  const lowest = Math.min(...all) / 3;
  const highest = Math.max(...idx.map((i) => scaling.fits[i]?.extrapolated?.high ?? 0)) * 3;
  const x = scale([3, 3000], [M.l, W - M.r]);
  const y = scale([lowest, highest], [H - M.b, M.t]);
  const yTicks: number[] = [];
  for (let e = Math.ceil(Math.log10(lowest)); e <= Math.floor(Math.log10(highest)); e += 3) yTicks.push(10 ** e);
  const xTicks = [4, 16, 64, 256, 1024];
  return (
    <figure className="card" style={{ margin: 0 }} aria-labelledby="cost-cap">
      <figcaption id="cost-cap" style={{ marginBottom: "0.5rem" }}>
        <strong>What an attack costs as keys get longer</strong>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Log-log chart: measured cost at small sizes and the extrapolation to 2048 bits for two estimators" style={{ width: "100%", height: "auto" }}>
        <g stroke="var(--line)">
          {yTicks.map((t) => (
            <line key={t} x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} />
          ))}
          <line x1={M.l} x2={M.l} y1={M.t} y2={H - M.b} />
          <line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} />
        </g>
        <g data-axis fill="var(--text-2)" fontSize="13" fontFamily="var(--font-mono)">
          {yTicks.map((t) => (
            <text key={t} x={M.l - 6} y={y(t) + 4} textAnchor="end">
              {sci(t, 0).replace("1 × ", "")}
            </text>
          ))}
          {xTicks.map((t) => (
            <text key={t} x={x(t)} y={H - M.b + 16} textAnchor="middle">
              {t}
            </text>
          ))}
        </g>
        <text x={(M.l + W - M.r) / 2} y={H - 4} textAnchor="middle" fill="var(--text-2)" fontSize="13">
          modulus size in bits (log scale)
        </text>
        {COST_SERIES.map((s, si) => {
          const i = idx[si] ?? -1;
          const f = scaling.fits[i];
          if (!f) return null;
          const last = f.points[f.points.length - 1];
          if (!last) return null;
          const ex = f.extrapolated;
          const lo = ex.low ?? ex.value;
          const hi = ex.high ?? ex.value;
          return (
            <g key={s.estimator}>
              {f.points.map((p) => (
                <circle key={p.n_bits} className="pt" style={{ ["--i" as string]: p.n_bits }} cx={x(p.n_bits)} cy={y(p.value)} r="3" fill={s.colour} />
              ))}
              <line x1={x(last.n_bits)} y1={y(last.value)} x2={x(ex.n_bits)} y2={y(ex.value)} stroke={s.colour} strokeDasharray="5 4" />
              <line x1={x(ex.n_bits)} x2={x(ex.n_bits)} y1={y(lo)} y2={y(hi)} stroke={s.colour} strokeWidth="3" />
              <circle cx={x(ex.n_bits)} cy={y(ex.value)} r="4" fill="none" stroke={s.colour} strokeWidth="2" />
            </g>
          );
        })}
      </svg>
      <p className="muted" style={{ fontSize: "0.8125rem", marginTop: 0 }}>
        Dots are measured costs at small key sizes. The dashed line carries the trend up to a real
        key size. It is an estimate, not a measurement. The two tools give different totals, so
        treat the size of the cost as rough.
      </p>
      <Tech>
      <dl className="why">
        {COST_SERIES.map((s, si) => {
          const i = idx[si] ?? -1;
          return (
            <div key={s.estimator} style={{ display: "contents" }}>
              <dt style={{ color: s.colour }}>
                {s.name}, at <Traced src={`scaling:fits[${i}].extrapolated.n_bits`} /> bits
              </dt>
              <dd>
                <Fig src={`scaling:fits[${i}].extrapolated.value`} sci digits={2} label="trend extrapolation"
                  note="Fitted polynomial carried past the measured sizes; see the range for how much the fits disagree."
                  extra={[
                    { name: "Low", src: `scaling:fits[${i}].extrapolated.low`, sci: true, digits: 2 },
                    { name: "High", src: `scaling:fits[${i}].extrapolated.high`, sci: true, digits: 2 },
                    { name: "Fit holdout error (%)", src: `scaling:fits[${i}].holdout.rel_error`, scale: 100, digits: 1 },
                  ]} />
              </dd>
            </div>
          );
        })}
      </dl>
      {COST_SERIES.map((s, si) => {
        const i = idx[si] ?? -1;
        const f = scaling.fits[i];
        return f?.caveat ? (
          <p key={s.estimator} className="muted" style={{ fontSize: "0.8125rem" }}>
            <Traced src={`scaling:fits[${i}].caveat`} />
          </p>
        ) : null;
      })}
      </Tech>
    </figure>
  );
}

function BraceChart({ scenario }: { scenario: "optimistic" | "median" | "pessimistic" }) {
  const t = scenarios.timeline.scenarios[scenario].targets;
  const device = lab.device.n_qubits;
  const record = scenarios.timeline.baseline.qubits;
  const rsa = t.rsa2048.physical_qubits;
  const ecc = t.ecc256.physical_qubits;
  const x = scale([100, 1e7], [M.l, W - M.r]);
  const base = 150;
  const marks = [
    { name: "ibm_kingston", v: device, colour: "var(--q)", row: 0 },
    { name: "largest chip built", v: record, colour: "var(--q)", row: 1 },
    { name: "RSA-2048 attack", v: rsa, colour: "var(--threat)", row: 0 },
    { name: "ECC-256 attack", v: ecc, colour: "var(--threat)", row: 1 },
  ];
  const ticks = [1e2, 1e3, 1e4, 1e5, 1e6, 1e7];
  return (
    <figure className="card" style={{ margin: 0 }} aria-labelledby="brace-cap">
      <figcaption id="brace-cap" style={{ marginBottom: "0.5rem" }}>
        <strong>Qubits needed, against the chips that exist</strong>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${BH}`} role="img" aria-label="Log axis of qubit counts with a brace from the chip we ran on to the qubits the attack needs" style={{ width: "100%", height: "auto" }}>
        <line x1={M.l} x2={W - M.r} y1={base} y2={base} stroke="var(--line)" />
        <g data-axis fill="var(--text-2)" fontSize="13" fontFamily="var(--font-mono)">
          {ticks.map((v) => (
            <text key={v} x={x(v)} y={base + 18} textAnchor="middle">
              {sci(v, 0).replace("1 × ", "")}
            </text>
          ))}
        </g>
        {ticks.map((v) => (
          <line key={v} x1={x(v)} x2={x(v)} y1={base - 4} y2={base + 4} stroke="var(--text-2)" />
        ))}
        <path
          d={`M ${x(device)} ${base - 70} C ${x(device)} ${base - 100}, ${x(rsa)} ${base - 100}, ${x(rsa)} ${base - 70}`}
          fill="none"
          stroke="var(--warn)"
          strokeWidth="2"
        />
        <text x={(x(device) + x(rsa)) / 2} y={base - 108} textAnchor="middle" fill="var(--warn)" fontSize="13">
          the gap
        </text>
        {marks.map((m) => (
          <g key={m.name}>
            <line x1={x(m.v)} x2={x(m.v)} y1={base} y2={base - 64 + m.row * 22} stroke={m.colour} strokeWidth="2" />
            <circle cx={x(m.v)} cy={base} r="4" fill={m.colour} />
            <text x={x(m.v)} y={base - 68 + m.row * 22} textAnchor={m.v < 1e4 ? "start" : "end"} dx={m.v < 1e4 ? 6 : -6} fill="var(--text-1)" fontSize="13">
              {m.name}
            </text>
          </g>
        ))}
        <text x={(M.l + W - M.r) / 2} y={BH - 4} textAnchor="middle" fill="var(--text-2)" fontSize="13">
          physical qubits (log scale)
        </text>
      </svg>
      <Tech>
      <dl className="why">
        <dt>ibm_kingston, the chip we ran on</dt>
        <dd>
          <Fig src="lab:device.n_qubits" label="hardware" note={lab.device.source} unit="qubits" />
        </dd>
        <dt>Largest chip built (record)</dt>
        <dd>
          <Fig src="scenarios:timeline.baseline.qubits" label="published estimate" unit="qubits"
            note="The largest gate-model device on the literature timeline." />
        </dd>
        {(["rsa2048", "ecc256"] as const).map((k) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k === "rsa2048" ? "RSA-2048" : "ECC-256"} attack needs</dt>
            <dd>
              <Fig src={`scenarios:timeline.scenarios.${scenario}.targets.${k}.physical_qubits`} sci digits={2} unit="qubits"
                label={t[k].physical_source === "model" ? "model estimate" : "published estimate"}
                note={`Source: ${t[k].physical_source}${t[k].physical_bound ? `, an ${t[k].physical_bound} bound` : ""}`} />
            </dd>
            <dt className="muted">… times the qubits of ibm_kingston</dt>
            <dd>
              <Fig src={`scenarios:gaps.${scenario}.${k}.over_device`} sci digits={2} label="computed from data" />
            </dd>
            <dt className="muted">… times the record chip</dt>
            <dd>
              <Fig src={`scenarios:gaps.${scenario}.${k}.over_record`} sci digits={2} label="computed from data" />
            </dd>
            <dt className="muted">Runtime of the attack</dt>
            <dd>
              <Fig src={`scenarios:timeline.scenarios.${scenario}.targets.${k}.runtime_seconds`} scale={1 / 86400} digits={1} unit="days" label="model estimate" />
            </dd>
            <dt className="muted">Year the record chip would reach that size</dt>
            <dd>
              <Fig src={`scenarios:timeline.scenarios.${scenario}.targets.${k}.crqc_year`} digits={1} nullText="none" label="trend extrapolation"
                extra={[{ name: "Trend holdout error (%):", src: "scenarios:timeline.fit.holdout.rel_error", scale: 100, digits: 0 }]} />
            </dd>
          </div>
        ))}
      </dl>
      <p className="muted" style={{ fontSize: "0.8125rem" }}>
        <Traced src={`scenarios:scenario_notes.${scenario}`} />
      </p>
      <p className="muted" style={{ fontSize: "0.8125rem" }}>
        <Traced src={`scenarios:order_notes.${scenario}`} />
      </p>
      </Tech>
    </figure>
  );
}
