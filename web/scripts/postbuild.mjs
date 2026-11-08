// Runs after `next build` (static export in out/). It is the only place that reads the build
// environment: web/src and next.config.ts read NODE_ENV only (gate 5).
//
//  1. out/build.json            {"commit": <sha>}  (VERCEL_GIT_COMMIT_SHA, else git rev-parse HEAD)
//  2. out/.well-known/security.txt (RFC 9116, Expires computed now), out/humans.txt, font licence
//  3. hash-based CSP from every inline <script> in out/**/*.html
//  4. .vercel/output/{config.json,static}: Build Output API v3 with the headers on every route,
//     written from the same build whose HTML the hashes were computed from
//  5. canary scan of out/ and public/data (fails the build on any hit)

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { scan } from "./canary-scan.mjs";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(web, "out");
const repoRoot = resolve(web, "..");
if (!existsSync(out)) throw new Error("out/ is missing: run `next build` first");

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else yield p;
  }
}

// ---- 1. build.json -------------------------------------------------------------------------
function commit() {
  const fromVercel = process.env.VERCEL_GIT_COMMIT_SHA;
  if (fromVercel) return fromVercel;
  return execFileSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8" }).trim();
}
writeFileSync(join(out, "build.json"), JSON.stringify({ commit: commit() }) + "\n");

// ---- 2. security.txt, humans.txt, licence ----------------------------------------------------
const expires = new Date(Date.now() + 180 * 24 * 3600 * 1000).toISOString().replace(/\.\d+Z$/, "Z");
mkdirSync(join(out, ".well-known"), { recursive: true });
writeFileSync(
  join(out, ".well-known", "security.txt"),
  [
    "Contact: mailto:aryan.shiva0805@gmail.com",
    `Expires: ${expires}`,
    "Preferred-Languages: en",
    "",
  ].join("\n"),
);
writeFileSync(
  join(out, "humans.txt"),
  [
    "/* TEAM */",
    "Project: Q-Day Radar, Qiskit Fall Fest 2026, Advanced Track",
    "Human: Aryan",
    "Sessions: three Claude Code sessions (lead, builder, reviewer) worked in parallel",
    "",
    "/* SITE */",
    "Standards: static export, no server, no analytics, no third-party requests",
    "Fonts: IBM Plex (SIL Open Font License 1.1, see /licenses/IBM-Plex-OFL.txt)",
    "",
  ].join("\n"),
);
const licenceSrc = join(web, "node_modules", "@fontsource", "ibm-plex-sans", "LICENSE");
mkdirSync(join(out, "licenses"), { recursive: true });
writeFileSync(join(out, "licenses", "IBM-Plex-OFL.txt"), readFileSync(licenceSrc));

// ---- 3. hash-based CSP ------------------------------------------------------------------------
const SCRIPT_RE = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
const hashes = new Set();
for (const file of walk(out)) {
  if (!file.endsWith(".html")) continue;
  const html = readFileSync(file, "utf8");
  for (const m of html.matchAll(SCRIPT_RE)) {
    const attrs = m[1] ?? "";
    const body = m[2] ?? "";
    if (/\bsrc\s*=/.test(attrs)) continue; // external: covered by 'self'
    const type = /\btype\s*=\s*["']?([^"'\s>]+)/i.exec(attrs)?.[1]?.toLowerCase();
    if (type && !["text/javascript", "application/javascript", "module"].includes(type)) continue;
    if (body.trim() === "") continue;
    hashes.add(`'sha256-${createHash("sha256").update(body, "utf8").digest("base64")}'`);
  }
}
const scriptSrc = ["'self'", ...[...hashes].sort()].join(" ");
const csp = [
  "default-src 'self'",
  `script-src ${scriptSrc}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'none'",
  "upgrade-insecure-requests",
].join("; ");

const headers = {
  "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
  "Content-Security-Policy": csp,
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Cross-Origin-Opener-Policy": "same-origin",
};

// ---- 4. Build Output API v3 --------------------------------------------------------------------
const vercelOut = join(web, ".vercel", "output");
rmSync(vercelOut, { recursive: true, force: true });
mkdirSync(vercelOut, { recursive: true });
cpSync(out, join(vercelOut, "static"), { recursive: true });
writeFileSync(
  join(vercelOut, "config.json"),
  JSON.stringify(
    {
      version: 3,
      routes: [
        { src: "/(.*)", headers, continue: true },
        { handle: "filesystem" },
        { src: "/(.*)", dest: "/404.html", status: 404 },
      ],
    },
    null,
    2,
  ) + "\n",
);

// ---- 5. canary scan ----------------------------------------------------------------------------
const result = scan([out, join(web, "public", "data")], join(repoRoot, ".env"));
console.log(
  `postbuild: ${hashes.size} inline-script hashes, headers written to .vercel/output/config.json; ` +
    `canary scan ${result.files} files, ${result.canaries} .env values, ${result.hits.length} hits`,
);
if (result.missing.length || result.files === 0) {
  console.error(`canary scan looked at nothing (missing: ${result.missing.join(", ") || "none"})`);
  process.exit(2);
}
if (result.hits.length) {
  for (const h of result.hits) console.error(`  HIT ${h.kind}: ${h.file}`);
  process.exit(1);
}
