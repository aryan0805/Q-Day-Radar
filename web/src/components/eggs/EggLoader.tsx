"use client";

import { useEffect, useState, type ComponentType } from "react";

// The easter eggs are one lazy chunk, requested after the page has loaded and gone idle, so they
// cost the home bundle nothing and no egg makes a request when it fires. `html[data-eggs=ready]`
// says the chunk is in.
export function EggLoader() {
  const [Eggs, setEggs] = useState<ComponentType | null>(null);
  useEffect(() => {
    const load = () => void import("./Eggs").then((m) => setEggs(() => m.Eggs));
    const idle = (window as Window & { requestIdleCallback?: (cb: () => void) => number }).requestIdleCallback;
    const id = idle ? idle(load) : window.setTimeout(load, 1500);
    return () => {
      if (!idle) window.clearTimeout(id);
    };
  }, []);
  return Eggs ? <Eggs /> : null;
}
