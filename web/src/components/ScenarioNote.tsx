"use client";

// Says how the chosen scenario differs from the median, computed from the data (never typed):
// the 'pessimistic' caveat (it differs from the median only in cycle time and growth rate) is
// whatever the comparison finds.
import { Fragment } from "react";
import { resolve, type Scenario } from "../lib/data";
import { useScenario } from "../lib/scenario";
import { Fig } from "./Fig";

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
  if (scenario === "median") {
    return (
      <p className="muted" style={{ fontSize: "0.875rem" }}>
        Median is the reference scenario: the base cost model with the fitted hardware growth rate.
      </p>
    );
  }
  const differs = FIELDS.filter(
    (f) => resolve("scenarios", f.path(scenario)) !== resolve("scenarios", f.path("median")),
  );
  return (
    <p className="muted" style={{ fontSize: "0.875rem" }}>
      {scenario === "optimistic" ? "Optimistic" : "Pessimistic"} differs from median in{" "}
      {differs.length === 0 ? "nothing in these inputs" : differs.map((f, i) => (
        <Fragment key={f.name}>
          {i > 0 ? ", " : ""}
          {f.name}{" "}
          <Fig src={`scenarios:${f.path(scenario)}`} label="design choice" digits={f.digits} sci={f.sci} unit={f.unit} />{" "}
          (median{" "}
          <Fig src={`scenarios:${f.path("median")}`} label="design choice" digits={f.digits} sci={f.sci} unit={f.unit} />)
        </Fragment>
      ))}
      .
    </p>
  );
}
