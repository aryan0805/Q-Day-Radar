"use client";

// The scenario is global state kept in the URL (?s=optimistic|median|pessimistic, default median).
// The server-rendered HTML is always the default; the URL is applied right after mount.
import { createContext, useContext, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { SCENARIOS, type Scenario } from "./data";

const DEFAULT: Scenario = "median";

interface Ctx {
  scenario: Scenario;
  setScenario: (s: Scenario) => void;
}
const ScenarioContext = createContext<Ctx>({ scenario: DEFAULT, setScenario: () => undefined });

function fromUrl(): Scenario {
  const s = new URLSearchParams(window.location.search).get("s");
  return (SCENARIOS as readonly string[]).includes(s ?? "") ? (s as Scenario) : DEFAULT;
}

// The URL is the store. The server snapshot is the default, so the static HTML is median and the
// URL is applied as soon as the page hydrates.
const listeners = new Set<() => void>();
function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  window.addEventListener("popstate", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("popstate", cb);
  };
}
function setScenario(s: Scenario): void {
  const url = new URL(window.location.href);
  if (s === DEFAULT) url.searchParams.delete("s");
  else url.searchParams.set("s", s);
  window.history.replaceState(null, "", url);
  listeners.forEach((l) => l());
}

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const scenario = useSyncExternalStore(subscribe, fromUrl, () => DEFAULT);
  const value = useMemo(() => ({ scenario, setScenario }), [scenario]);
  return <ScenarioContext.Provider value={value}>{children}</ScenarioContext.Provider>;
}

export function useScenario(): Ctx {
  return useContext(ScenarioContext);
}

/** Link to another screen that keeps the chosen scenario. */
export function withScenario(href: string, s: Scenario): string {
  return s === DEFAULT ? href : `${href}${href.includes("?") ? "&" : "?"}s=${s}`;
}
