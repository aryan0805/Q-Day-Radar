"use client";

import { useRef } from "react";
import { SCENARIOS, type Scenario } from "../lib/data";
import { useScenario } from "../lib/scenario";

const NAMES: Record<Scenario, string> = {
  optimistic: "Optimistic",
  median: "Median",
  pessimistic: "Pessimistic",
};

export function ScenarioSwitch() {
  const { scenario, setScenario } = useScenario();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const move = (to: number) => {
    const next = SCENARIOS[(to + SCENARIOS.length) % SCENARIOS.length] as Scenario;
    setScenario(next);
    refs.current[next]?.focus();
  };
  return (
    <div role="radiogroup" aria-label="Scenario" className="seg">
      {SCENARIOS.map((s, i) => (
        <button
          key={s}
          ref={(el) => {
            refs.current[s] = el;
          }}
          type="button"
          role="radio"
          aria-checked={scenario === s}
          tabIndex={scenario === s ? 0 : -1}
          data-scenario={s}
          onClick={() => setScenario(s)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight" || e.key === "ArrowDown") {
              e.preventDefault();
              move(i + 1);
            } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
              e.preventDefault();
              move(i - 1);
            }
          }}
        >
          {NAMES[s]}
        </button>
      ))}
    </div>
  );
}
