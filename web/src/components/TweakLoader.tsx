"use client";

import { useEffect, useState, type ComponentType } from "react";

// Development only: `/?tweak` mounts the tweak panel. In a production build
// `process.env.NODE_ENV` is the constant "production", the branch is removed and the panel
// module is never emitted.
export function TweakLoader() {
  const [Panel, setPanel] = useState<ComponentType | null>(null);
  useEffect(() => {
    if (process.env.NODE_ENV === "development" && new URLSearchParams(location.search).has("tweak")) {
      void import("./dev/TweakPanel").then((m) => setPanel(() => m.default));
    }
  }, []);
  return Panel ? <Panel /> : null;
}
