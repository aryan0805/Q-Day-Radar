"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { inventory, type Asset, type Scenario } from "../../lib/data";
import { useScenario } from "../../lib/scenario";
import { useUrlParam } from "../../lib/urlparam";
import { Fig } from "../Fig";
import { Traced } from "../Traced";
import { Gloss } from "../Gloss";
import { Tech } from "../Tech";
import { ScenarioNote } from "../ScenarioNote";

type SortKey = "rank" | "margin" | "name";
const FAMILIES = ["all", ...Array.from(new Set(inventory.assets.map((a) => a.family)))] as const;
const EXPOSURES = ["all", "internet", "partner", "internal"] as const;

interface Row {
  asset: Asset;
  index: number;
}

function sc(a: Asset, s: Scenario) {
  return a.by_scenario[s];
}

export function InventoryView() {
  const { scenario } = useScenario();
  const [family, setFamily] = useState<(typeof FAMILIES)[number]>("all");
  const [exposure, setExposure] = useState<(typeof EXPOSURES)[number]>("all");
  const [atRisk, setAtRisk] = useState(false);
  const [sort, setSort] = useState<SortKey>("rank");
  const [assetParam, setAssetParam] = useUrlParam("asset");

  const rows = useMemo(() => {
    const all: Row[] = inventory.assets.map((asset, index) => ({ asset, index }));
    const kept = all.filter(
      ({ asset }) =>
        (family === "all" || asset.family === family) &&
        (exposure === "all" || asset.exposure === exposure) &&
        (!atRisk || (sc(asset, scenario).margin_years ?? Infinity) < 0),
    );
    const key = (r: Row): number | string => {
      const s = sc(r.asset, scenario);
      if (sort === "rank") return s.rank;
      if (sort === "margin") return s.margin_years ?? Infinity;
      return r.asset.name;
    };
    return kept.sort((p, q) => {
      const a = key(p);
      const b = key(q);
      if (typeof a === "number" && typeof b === "number") return a - b || p.index - q.index;
      return String(a).localeCompare(String(b));
    });
  }, [family, exposure, atRisk, sort, scenario]);

  const drawerRef = useRef<HTMLDivElement>(null);
  const tbody = useRef<HTMLTableSectionElement>(null);
  const tops = useRef<Map<string, number>>(new Map());
  const order = rows.map((r) => r.asset.id).join("|");
  const maxMargin = Math.max(1e-9, ...inventory.assets.map((a) => Math.abs(sc(a, scenario).margin_years ?? 0)));

  // FLIP: when the order changes (a new scenario or sort), each row slides from where it was to
  // where it is now. Off under reduced motion; the duration follows --motion-scale.
  useLayoutEffect(() => {
    const body = tbody.current;
    if (!body) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const scale = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--motion-scale")) || 1;
    const next = new Map<string, number>();
    body.querySelectorAll<HTMLElement>("tr[data-asset-id]").forEach((tr) => {
      const id = tr.dataset.assetId ?? "";
      const top = tr.getBoundingClientRect().top;
      next.set(id, top);
      const before = tops.current.get(id);
      if (!reduce && before !== undefined && Math.abs(before - top) > 1 && tr.animate) {
        tr.animate([{ transform: `translateY(${before - top}px)` }, { transform: "none" }], {
          duration: 450 * scale,
          easing: "cubic-bezier(0.16, 1, 0.3, 1)",
        });
      }
    });
    tops.current = next;
  }, [order]);
  const open = assetParam ? inventory.assets.findIndex((a) => a.id === assetParam) : -1;
  const noFinite = inventory.assets.every((a) => sc(a, scenario).margin_years === null);

  return (
    <section aria-labelledby="inv-h">
      <h1 id="inv-h" style={{ fontSize: "2rem", marginBlock: "0 0.5rem" }}>
        Inventory
      </h1>
      <p className="muted">
        This table lists every piece of cryptography in a made-up company, from web certificates to
        disk encryption. The first row is the most urgent.
      </p>
      <p className="muted">
        Each row has a <Gloss term="crqc">break year</Gloss>: when a quantum computer could break
        it. The <Gloss term="mosca">margin</Gloss> is the years to spare. A negative margin means
        the asset is exposed.
      </p>
      <p>
        Every break year is an <Gloss term="trend">estimate from a trend line, not a measurement</Gloss>.
        The trend missed a known year by{" "}
        <Fig src="scenarios:timeline.fit.holdout.rel_error" scale={100} digits={0} unit="%" label="trend extrapolation"
          note="The fit was made without the latest point and asked to predict it." />
        , so treat the years as rough.
      </p>
      <ScenarioNote />
      {noFinite ? (
        <p role="note" className="card" style={{ borderColor: "var(--warn)" }}>
          In this scenario every attack would run for longer than{" "}
          <Fig src="scenarios:timeline.runtime_cap_years" digits={0} unit="year" label="design choice" />, which is the limit we set. So no asset has a margin here. That
          is a limit we chose, not proof that nothing is at risk.
        </p>
      ) : null}
      <Tech>
        <p style={{ margin: "0 0 0.5rem" }}>
          Rank orders assets by exposure weight times years of shortfall, then by margin, then by
          id. A CRQC year is a <Traced src="inventory:crqc_label" />: a log-linear fit of the
          largest gate-model qubit count per year, carried to the physical qubits the costed attack
          needs.
        </p>
        <p style={{ margin: 0 }}>
          <Traced src={`scenarios:scenario_notes.${scenario}`} />
        </p>
      </Tech>

      <div className="controls" role="group" aria-label="Filter and sort">
        <label>
          Family
          <select value={family} onChange={(e) => setFamily(e.target.value as typeof family)}>
            {FAMILIES.map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </label>
        <label>
          Exposure
          <select value={exposure} onChange={(e) => setExposure(e.target.value as typeof exposure)}>
            {EXPOSURES.map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </label>
        <label>
          Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            <option value="rank">Rank (most urgent first)</option>
            <option value="margin">Mosca margin</option>
            <option value="name">Name</option>
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={atRisk} onChange={(e) => setAtRisk(e.target.checked)} />
          Only assets with a negative margin
        </label>
      </div>

      <div className="tbl-wrap" role="region" aria-label="Inventory table" tabIndex={0}>
        <table className="tbl">
          <caption className="sr-only">Assets ranked for the selected scenario</caption>
          <thead>
            <tr>
              <th scope="col">Rank</th>
              <th scope="col">Asset</th>
              <th scope="col">Exposure</th>
              <th scope="col">CRQC year</th>
              <th scope="col">Margin</th>
              <th scope="col">Replace with</th>
            </tr>
          </thead>
          <tbody ref={tbody}>
            {rows.map(({ asset, index }, n) => {
              const p = `assets[${index}]`;
              const s = sc(asset, scenario);
              const margin = s.margin_years;
              return (
                <tr key={asset.id} data-asset-id={asset.id} style={{ ["--i" as string]: Math.min(n, 20) }}>
                  <td>
                    <Fig src={`inventory:${p}.by_scenario.${scenario}.rank`} label="computed from data" />
                  </td>
                  <td>
                    <button type="button" className="linkish" onClick={() => setAssetParam(asset.id)}>
                      <Traced src={`inventory:${p}.name`} />
                    </button>
                    <div className="muted" style={{ fontSize: "0.8125rem" }}>
                      <Traced src={`inventory:${p}.algorithm`} />
                    </div>
                  </td>
                  <td>
                    <Traced src={`inventory:${p}.exposure`} />
                  </td>
                  <td>
                    <CrqcYear index={index} asset={asset} scenario={scenario} />
                  </td>
                  <td style={{ color: margin === null ? "var(--text-2)" : margin < 0 ? "var(--threat)" : "var(--text-1)" }}>
                    <span
                      className="mbar"
                      aria-hidden="true"
                      style={{
                        width: `${margin === null ? 0 : (Math.abs(margin) / maxMargin) * 100}%`,
                        background: margin !== null && margin < 0 ? "var(--threat)" : "var(--warn)",
                      }}
                    />
                    <Fig
                      src={`inventory:${p}.by_scenario.${scenario}.margin_years`}
                      digits={1}
                      sign
                      unit="years"
                      nullText="none"
                      label="computed from data"
                      note="Margin = years until a quantum computer can break it, minus shelf life minus migration time. Negative means exposed."
                    />
                  </td>
                  <td>
                    <Traced src={`inventory:${p}.replacement.algorithm`} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length === 0 ? <p className="muted">No asset matches these filters.</p> : null}

      <Dialog.Root open={open >= 0} onOpenChange={(o) => (o ? undefined : setAssetParam(null))}>
        <Dialog.Portal>
          <Dialog.Overlay className="overlay" />
          <Dialog.Content
            ref={drawerRef}
            className="drawer"
            aria-describedby={undefined}
            onOpenAutoFocus={(e) => {
              e.preventDefault(); // land on the dialog, not on the first figure (that opens its tooltip)
              drawerRef.current?.focus();
            }}
          >
            {open >= 0 ? <Why index={open} scenario={scenario} /> : null}
            <Dialog.Close className="btn" style={{ marginTop: "1.25rem" }}>
              Close
            </Dialog.Close>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}

function CrqcYear({ index, asset, scenario }: { index: number; asset: Asset; scenario: Scenario }) {
  const p = `assets[${index}].by_scenario.${scenario}`;
  const s = asset.by_scenario[scenario];
  const target = asset.attack_target;
  const deprecated = asset.classically_deprecated;
  const extra = [
    ...(target && !deprecated
      ? [
          {
            name: "Cost model alone:",
            src: `scenarios:model_only.${scenario}.targets.${target}.crqc_year`,
            digits: 1,
          },
        ]
      : []),
    { name: "Trend holdout error (%):", src: "scenarios:timeline.fit.holdout.rel_error", scale: 100, digits: 0 },
  ];
  return (
    <>
      <Fig
        src={`inventory:${p}.crqc_year`}
        digits={1}
        nullText="none"
        label={deprecated ? "published standard" : "trend extrapolation"}
        note={s.crqc_basis ?? "No finite CRQC year in this scenario."}
        extra={extra}
      />
      <div className="muted" style={{ fontSize: "0.8125rem" }}>
        {s.crqc_basis === null ? "no finite year" : deprecated ? "weak without quantum" : "trend-line estimate"}
      </div>
    </>
  );
}

function Why({ index, scenario }: { index: number; scenario: Scenario }) {
  const a = inventory.assets[index] as Asset;
  const p = `assets[${index}]`;
  const s = a.by_scenario[scenario];
  const target = a.attack_target;
  return (
    <>
      <Dialog.Title style={{ fontSize: "1.5rem", marginBlock: "0 0.25rem" }}>
        <Traced src={`inventory:${p}.name`} />
      </Dialog.Title>
      <p className="muted" style={{ marginTop: 0 }}>
        <Traced src={`inventory:${p}.algorithm`} />, <Traced src={`inventory:${p}.usage`} />,{" "}
        <Traced src={`inventory:${p}.exposure`} /> exposure
      </p>
      <h3 style={{ fontSize: "1rem" }}>Why this score</h3>
      <dl className="why">
        <dt>Time until a quantum computer can break it</dt>
        <dd>
          <Fig src={`inventory:${p}.by_scenario.${scenario}.crqc_year`} digits={1} nullText="none" label="trend extrapolation" />
          {s.crqc_basis ? <span className="muted"> ({s.crqc_basis})</span> : null}
        </dd>
        <dt>How long it must stay secure (shelf life)</dt>
        <dd>
          <Fig src={`inventory:${p}.shelf_life_years`} digits={1} unit="years" label="fictional demo input" />
        </dd>
        <dt>How long migration takes</dt>
        <dd>
          <Fig src={`inventory:${p}.migration_years`} digits={1} unit="years" label="fictional demo input" />
        </dd>
        <dt>Mosca margin</dt>
        <dd>
          <Fig src={`inventory:${p}.by_scenario.${scenario}.margin_years`} digits={1} sign unit="years" nullText="none" label="computed from data" />
        </dd>
        <dt>Exposure weight</dt>
        <dd>
          <Fig src={`inventory:${p}.exposure_weight`} digits={1} label="design choice" />
        </dd>
        <dt>Shortfall (weight × years of exposure)</dt>
        <dd>
          <Fig src={`inventory:${p}.by_scenario.${scenario}.shortfall`} digits={1} label="computed from data" />
        </dd>
        {target ? (
          <>
            <dt>Same year from the cost model alone</dt>
            <dd>
              <Fig src={`scenarios:model_only.${scenario}.targets.${target}.crqc_year`} digits={1} nullText="none" label="model estimate" />
            </dd>
          </>
        ) : null}
      </dl>
      <p>
        <Traced src={`inventory:${p}.mapping_note`} />
      </p>
      <h3 style={{ fontSize: "1rem" }}>Replacement</h3>
      <p>
        <Traced src={`inventory:${p}.replacement.algorithm`} /> (<Traced src={`inventory:${p}.replacement.standard_id`} />)
      </p>
      <h3 style={{ fontSize: "1rem" }}>Deadlines to compare</h3>
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
      <p className="muted" style={{ fontSize: "0.8125rem" }}>
        Physical-qubit source behind this scenario&apos;s CRQC year:{" "}
        <Traced src={`scenarios:timeline.scenarios.${scenario}.targets.${target ?? "rsa2048"}.physical_source`} />
      </p>
    </>
  );
}
