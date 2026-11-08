"use client";

import Link from "next/link";
import { useState } from "react";
import { inventory, scenarios, type Asset, type Scenario } from "../../lib/data";
import { useScenario, withScenario } from "../../lib/scenario";
import { Fig } from "../Fig";
import { Traced } from "../Traced";
import { ScenarioNote } from "../ScenarioNote";

const SIZE = 540;
const C = SIZE / 2;
const r2 = (v: number) => Math.round(v * 100) / 100; // identical on the server and in the browser
const R_IN = 46;
const R_OUT = 190;
const R_NONE = 214; // the band for assets with no finite margin

function colourOf(a: Asset, s: Scenario): { fill: string; word: string } {
  const m = a.by_scenario[s].margin_years;
  if (m !== null) return m < 0 ? { fill: "var(--threat)", word: "exposed" } : { fill: "var(--warn)", word: "time left" };
  if (a.family === "ML-KEM" || a.family === "ML-DSA" || a.family === "SLH-DSA") return { fill: "var(--pqc)", word: "post-quantum" };
  return { fill: "var(--sim-text)", word: "no finite margin" };
}

/** Radar layout: one sector per family, radius from the margin (computed from this scenario's data). */
function layout(s: Scenario) {
  const families = Array.from(new Set(inventory.assets.map((a) => a.family)));
  const finite = inventory.assets.map((a) => a.by_scenario[s].margin_years).filter((m): m is number => m !== null);
  const lo = Math.min(...finite, 0);
  const hi = Math.max(...finite, 0);
  const r = (m: number) => R_IN + ((m - lo) / (hi - lo || 1)) * (R_OUT - R_IN);
  const per: Record<string, number> = {};
  const count: Record<string, number> = {};
  inventory.assets.forEach((a) => (count[a.family] = (count[a.family] ?? 0) + 1));
  const sector = (2 * Math.PI) / families.length;
  const pts = inventory.assets.map((a, index) => {
    const fi = families.indexOf(a.family);
    const k = per[a.family] ?? 0;
    per[a.family] = k + 1;
    const n = count[a.family] ?? 1;
    const ang = -Math.PI / 2 + fi * sector + ((k + 1) / (n + 1)) * sector;
    const m = a.by_scenario[s].margin_years;
    const rad = m === null ? R_NONE : r(m);
    return {
      index,
      asset: a,
      x: Math.round((C + rad * Math.cos(ang)) * 100) / 100,
      y: Math.round((C + rad * Math.sin(ang)) * 100) / 100,
    };
  });
  return { pts, zero: Math.round(r(0) * 100) / 100, families, sector };
}

export function OverviewView() {
  const { scenario } = useScenario();
  const [active, setActive] = useState<number | null>(null);
  const { pts, zero, families, sector } = layout(scenario);
  const shown = active === null ? null : inventory.assets[active];
  const sum = `summary.${scenario}`;
  return (
    <>
      <section aria-labelledby="ov-h">
        <h1 id="ov-h" style={{ fontSize: "2.25rem", marginBlock: "0 0.5rem" }}>
          When does quantum computing break what you use?
        </h1>
        <p className="muted">
          Q-Day Radar runs real Shor and Grover circuits, scales their cost up to real key sizes, and
          ranks a fictional company&apos;s cryptography by how soon it is exposed. Each dot below is
          one asset. The closer to the centre, the less time is left.
        </p>
        <ScenarioNote />
        <div className="ov-grid">
          <figure className="card" style={{ margin: 0 }} aria-labelledby="radar-cap">
            <figcaption id="radar-cap" style={{ marginBottom: "0.5rem" }}>
              <strong>Radar of the inventory</strong>
            </figcaption>
            <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="group" aria-label="Radar: each dot is an asset" style={{ width: "100%", height: "auto" }}>
              <circle cx={C} cy={C} r={R_OUT} fill="none" stroke="var(--line)" />
              <circle cx={C} cy={C} r={zero} fill="none" stroke="var(--threat)" strokeDasharray="4 4" opacity="0.7" />
              <circle cx={C} cy={C} r={R_NONE} fill="none" stroke="var(--line)" strokeDasharray="2 5" />
              {families.map((f, i) => {
                const a = -Math.PI / 2 + i * sector;
                return (
                  <line key={f} x1={C} y1={C} x2={r2(C + (R_NONE + 12) * Math.cos(a))} y2={r2(C + (R_NONE + 12) * Math.sin(a))} stroke="var(--line)" />
                );
              })}
              {families.map((f, i) => {
                const a = -Math.PI / 2 + (i + 0.5) * sector;
                return (
                  <text key={f} x={r2(C + (R_NONE + 26) * Math.cos(a))} y={r2(C + (R_NONE + 26) * Math.sin(a))} fontSize="12" fill="var(--text-2)" textAnchor="middle" dominantBaseline="middle">
                    {f}
                  </text>
                );
              })}
              {pts.map((p) => {
                const col = colourOf(p.asset, scenario);
                return (
                  <a
                    key={p.asset.id}
                    href={withScenario(`/inventory/?asset=${p.asset.id}`, scenario)}
                    aria-label={`${p.asset.name}: ${col.word}`}
                    onMouseEnter={() => setActive(p.index)}
                    onFocus={() => setActive(p.index)}
                    onMouseLeave={() => setActive(null)}
                    onBlur={() => setActive(null)}
                  >
                    <circle cx={p.x} cy={p.y} r="12" fill="transparent" />
                    <circle cx={p.x} cy={p.y} r="5.5" fill={col.fill} stroke="var(--bg-0)" strokeWidth="1.5" />
                  </a>
                );
              })}
            </svg>
            <div className="legend" aria-hidden="true">
              <span><i style={{ background: "var(--threat)" }} /> exposed</span>
              <span><i style={{ background: "var(--warn)" }} /> time left</span>
              <span><i style={{ background: "var(--pqc)" }} /> post-quantum</span>
              <span><i style={{ background: "var(--sim-text)" }} /> no finite margin</span>
            </div>
            <div className="radar-card" aria-live="polite">
              {shown ? (
                <>
                  <strong><Traced src={`inventory:assets[${active}].name`} /></strong>
                  <span className="muted"> · <Traced src={`inventory:assets[${active}].algorithm`} /> · rank </span>
                  <Fig src={`inventory:assets[${active}].by_scenario.${scenario}.rank`} label="computed from data" />
                  <span className="muted"> · margin </span>
                  <Fig src={`inventory:assets[${active}].by_scenario.${scenario}.margin_years`} digits={1} sign unit="years" nullText="none" label="computed from data" />
                </>
              ) : (
                <span className="muted">Hover or focus a dot to see the asset. Activate it to open it in the Inventory.</span>
              )}
            </div>
            <p className="muted" style={{ fontSize: "0.8125rem", marginBottom: 0 }}>
              The dashed red ring is a margin of zero: dots inside it are exposed. The dotted outer
              ring holds assets with no finite margin in this scenario.
            </p>
          </figure>

          <div style={{ display: "grid", gap: "1rem", alignContent: "start" }}>
            <section className="card" aria-labelledby="now-h">
              <h2 id="now-h" style={{ fontSize: "1.125rem", marginBlock: "0 0.75rem" }}>
                In this scenario
              </h2>
              <dl className="why">
                <dt>Assets exposed</dt>
                <dd>
                  <Fig src={`inventory:${sum}.exposed`} label="computed from data" /> of{" "}
                  <Fig src={`inventory:${sum}.assets_total`} label="computed from data" />
                </dd>
                <dt>Assets already weak without quantum</dt>
                <dd>
                  <Fig src={`inventory:${sum}.classically_deprecated`} label="computed from data" />
                </dd>
                <dt>Earliest quantum break</dt>
                <dd>
                  <Fig src={`inventory:${sum}.soonest_crqc_year`} digits={1} nullText="none" label="trend extrapolation"
                    note="A straight-line trend of hardware qubit counts; it failed its own holdout."
                    extra={[{ name: "Trend holdout error (%):", src: "scenarios:timeline.fit.holdout.rel_error", scale: 100, digits: 0 }]} />
                </dd>
              </dl>
              <p className="muted" style={{ fontSize: "0.8125rem", marginBottom: 0 }}>
                Years are a <Traced src="inventory:crqc_label" />: the trend&apos;s own holdout error was{" "}
                <Fig src="scenarios:timeline.fit.holdout.rel_error" scale={100} digits={0} unit="%" label="trend extrapolation" />.
              </p>
            </section>

            <section className="card" aria-labelledby="order-h">
              <h2 id="order-h" style={{ fontSize: "1.125rem", marginBlock: "0 0.75rem" }}>
                Whose attack arrives first
              </h2>
              <OrderRow label="Computed order" scenario={scenario} list={inventory.family_order[scenario]} base={`inventory:family_order.${scenario}`} />
              <OrderRow label="Cost model alone" scenario={scenario} list={scenarios.model_only[scenario].family_order} base={`scenarios:model_only.${scenario}.family_order`} />
              <p className="muted" style={{ fontSize: "0.8125rem" }}>
                <Traced src={`scenarios:order_notes.${scenario}`} />
              </p>
              <p className="muted" style={{ fontSize: "0.8125rem", marginBottom: 0 }}>
                <Traced src={`scenarios:scenario_notes.${scenario}`} />
              </p>
            </section>

            <section className="card" aria-labelledby="dl-h">
              <h2 id="dl-h" style={{ fontSize: "1.125rem", marginBlock: "0 0.75rem" }}>
                Deadlines to compare
              </h2>
              <ul className="deadlines">
                {inventory.deadlines.map((d, i) => (
                  <li key={d.key}>
                    <Fig src={`inventory:deadlines[${i}].year`} label="published standard" note={d.scope} />{" "}
                    <span className="muted">
                      <Traced src={`inventory:deadlines[${i}].scope`} />
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </div>
      </section>
      <p style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", marginTop: "1.5rem" }}>
        <Link className="btn" href={withScenario("/lab/", scenario)}>Open the Lab</Link>
        <Link className="btn" href={withScenario("/scaling/", scenario)}>Open Scaling</Link>
        <Link className="btn btn-safe" href={withScenario("/inventory/", scenario)}>Open the Inventory</Link>
      </p>
    </>
  );
}

function OrderRow({ label, scenario, list, base }: { label: string; scenario: Scenario; list: string[]; base: string }) {
  // Only families with a quantum-attack year in this scenario carry an order; the rest are tied.
  const dated = new Set(
    inventory.assets
      .filter((a) => a.by_scenario[scenario].crqc_basis === inventory.crqc_label)
      .map((a) => a.family),
  );
  return (
    <p style={{ margin: "0 0 0.4rem", display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
      <span className="muted" style={{ minWidth: "9rem" }}>{label}</span>
      {list.map((f, i) =>
        dated.has(f) ? (
          <span key={f} className="pill">
            <Traced src={`${base}[${i}]`} />
          </span>
        ) : null,
      )}
    </p>
  );
}
