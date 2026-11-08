import type { NextConfig } from "next";

// Static export: no server, no API routes, no runtime secrets. Headers are written by
// scripts/postbuild.mjs (next.config `headers()` does not run under output: "export").
const config: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  productionBrowserSourceMaps: false,
  poweredByHeader: false,
  reactStrictMode: true,
  agentRules: false, // do not let `next dev` write AGENTS.md into the repository
};

export default config;
