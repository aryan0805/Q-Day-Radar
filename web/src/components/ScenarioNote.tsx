"use client";

// Says what the chosen scenario means in plain words, then how it differs from the median as a
// technical detail computed from the data (never typed): the 'pessimistic' caveat is whatever the
// comparison finds.
import { Fragment } from "react";
import { resolve, type Scenario } from "../lib/data";
import { useScenario } from "../lib/scenario";
import { Fig } from "./Fig";
import { Tech } from "./Tech";
import { Traced } from "./Traced";

interface Field {
  name: string;
  path: (s: Scenario) => string;
  digits: number;
  unit?: string;
  sci?: boolean;
}

const FIELDS: Field[] = [
  { name: "cycle time", path: (s: Scenario) => `scenarios.${s}.qec_scheme.cycle_time_seconds`, unit: "s", sci: true, digits: 2 },
  { name: "physical error rate", path: (s: Scenario) => `scenarios.${s}.physical_error_rate`, sci: true, digits: 1 },
  { name: "error budget", path: (s: Scenario) => `scenarios.${s}.error_budget`, digits: 3 },
  { name: "hardware doubling time", path: (s: Scenario) => `timeline.scenarios.${s}.doubling_years`, unit: "years", digits: 2 },
];

export function ScenarioNote() {
  const { scenario } = useScenario();
  const differs =
    scenario === "median"
      ? []
      : FIELDS.filter((f) => resolve("scenarios", f.path(scenario)) !== resolve("scenarios", f.path("median")));
  return (
    <>
      <p className="muted" style={{ fontSize: "0.9375rem" }}>
        <Traced src={`scenarios:scenario_plain.${scenario}`} /> A scenario is a guess about how fast quantum computers will improve. Use the buttons at the top to switch.
      </p>
      {scenario === "median" ? null : (
        <Tech>
          <p style={{ margin: 0 }}>
            {scenario === "optimistic" ? "Optimistic" : "Pessimistic"} differs from median in{" "}
            {differs.length === 0
              ? "nothing in these inputs"
              : differs.map((f, i) => (
                  <Fragment key={f.name}>
                    {i > 0 ? ", " : ""}
                    {f.name}{" "}
                    <Fig src={`scenarios:${f.path(scenario)}`} label="design choice" digits={f.digits} sci={f.sci} unit={f.unit} /> (median{" "}
                    <Fig src={`scenarios:${f.path("median")}`} label="design choice" digits={f.digits} sci={f.sci} unit={f.unit} />)
                  </Fragment>
                ))}
            .
          </p>
        </Tech>
      )}
    </>
  );
}
