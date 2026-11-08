// Typed access to web/public/data. Everything on screen is read through these, so a figure can
// carry the "<file>:<path>" it came from (data-src) and the gate can recompute it.
import inventory from "../../public/data/inventory.json";
import scenarios from "../../public/data/scenarios.json";

export const SCENARIOS = ["optimistic", "median", "pessimistic"] as const;
export type Scenario = (typeof SCENARIOS)[number];
export type Inventory = typeof inventory;
export type Asset = Inventory["assets"][number];

export { inventory, scenarios };

// inventory and scenarios are on every screen. lab, scaling and hero are large, so the screen that
// needs one registers it when its module loads and the other routes never ship it.
const registry: Record<string, unknown> = { inventory, scenarios };
export function register(name: string, data: unknown): void {
  registry[name] = data;
}

/** Resolve "assets[3].by_scenario.median.margin_years" inside a data file. */
export function resolve(file: string, path: string): unknown {
  let x: unknown = registry[file];
  for (const m of path.matchAll(/\[(\d+)\]|([^.[\]]+)/g)) {
    if (x === null || x === undefined) return undefined;
    const idx = m[1];
    const key = m[2];
    x = idx !== undefined ? (x as unknown[])[Number(idx)] : (x as Record<string, unknown>)[key ?? ""];
  }
  return x;
}

export function srcRef(file: string, path: string): string {
  return `${file}:${path}`;
}
