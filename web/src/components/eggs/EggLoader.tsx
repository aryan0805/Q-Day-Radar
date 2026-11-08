"use client";

import { useEffect, useState, type ComponentType } from "react";
import { onFirstInteraction, pending } from "../../lib/interaction";

// The easter eggs are one lazy chunk, requested on the visitor's first interaction, so they cost
// the page nothing before that and no egg makes a request when it fires (`html[data-eggs=ready]`
// says the chunk is in). Keys typed and the coin clicked while it loads are kept and replayed.
export function EggLoader() {
  const [Eggs, setEggs] = useState<ComponentType | null>(null);
  useEffect(() => {
    const keep = (e: KeyboardEvent) => {
      pending.keys = [...pending.keys, e.key.length === 1 ? e.key.toLowerCase() : e.key].slice(-12);
    };
    const coin = (e: MouseEvent) => {
      if ((e.target as HTMLElement | null)?.closest('[data-egg="coin"]')) pending.coin = true;
    };
    window.addEventListener("keydown", keep);
    document.addEventListener("click", coin);
    const stop = onFirstInteraction(() => void import("./Eggs").then((m) => setEggs(() => m.Eggs)));
    return () => {
      stop();
      window.removeEventListener("keydown", keep);
      document.removeEventListener("click", coin);
    };
  }, []);
  return Eggs ? <Eggs /> : null;
}
