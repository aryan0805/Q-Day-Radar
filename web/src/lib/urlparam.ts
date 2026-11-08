"use client";

import { useSyncExternalStore } from "react";

// A query parameter as external state: the server snapshot is null, the URL applies on hydration.
const listeners = new Set<() => void>();
function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  window.addEventListener("popstate", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("popstate", cb);
  };
}

export function useUrlParam(name: string): [string | null, (v: string | null) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => new URLSearchParams(window.location.search).get(name),
    () => null,
  );
  const set = (v: string | null) => {
    const url = new URL(window.location.href);
    if (v === null) url.searchParams.delete(name);
    else url.searchParams.set(name, v);
    window.history.replaceState(null, "", url);
    listeners.forEach((l) => l());
  };
  return [value, set];
}
