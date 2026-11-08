// Secret hygiene scan (gate 5, task 5). Scans every file under the given directories for
//   1. the exact values found in a local .env file (read in memory, never printed), and
//   2. well-known secret patterns.
// Exit status 1 on any hit. A hit names the file and the kind of match, never the value.
//
//   node scripts/canary-scan.mjs <dir>... [--env <path-to-.env>]
// Default env file: ../.env (the repository root). A missing .env is fine (nothing to match).

import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

export const PATTERNS = [
  ["private key block", /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ["GitHub token", /\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b/],
  ["AWS access key id", /\bAKIA[0-9A-Z]{16}\b/],
  ["JWT", /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/],
  ["IBM Cloud resource name", /\bcrn:v\d:[a-z0-9-]+:/],
  ["credential assignment", /\b(?:api[_-]?key|secret|token|password)["']?\s*[:=]\s*["'][^"'\s]{12,}["']/i],
  ["Vercel bypass header with a value", /x-vercel-protection-bypass["']?\s*[:=]\s*["'][^"'\s]{8,}["']/i],
  ["local path", /\/Users\/[A-Za-z0-9._-]+\/|\/home\/[a-z_][a-z0-9_-]*\//],
];

/** Values from an .env file worth matching: non-empty, at least 8 characters. */
export function envValues(envPath) {
  if (!envPath || !existsSync(envPath)) return [];
  const out = [];
  for (const raw of readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 0) continue;
    let v = line.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    if (v.length >= 8) out.push(v);
  }
  return out;
}

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else yield p;
  }
}

/** Returns [{file, kind}] (no values). Scans bytes as latin1 so binary files cannot throw. */
export function scan(dirs, envPath) {
  const canaries = envValues(envPath);
  const hits = [];
  let files = 0;
  for (const d of dirs) {
    if (!existsSync(d)) continue;
    for (const file of walk(d)) {
      files += 1;
      const text = readFileSync(file, "latin1");
      for (const c of canaries) {
        if (text.includes(Buffer.from(c, "utf8").toString("latin1"))) {
          hits.push({ file, kind: "value from .env" });
        }
      }
      for (const [kind, re] of PATTERNS) {
        if (re.test(text)) hits.push({ file, kind });
      }
    }
  }
  return { files, canaries: canaries.length, hits };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  let envPath = resolve(here, "..", "..", ".env");
  const dirs = [];
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === "--env") envPath = resolve(args[(i += 1)] ?? "");
    else dirs.push(resolve(args[i]));
  }
  if (dirs.length === 0) dirs.push(resolve(here, "..", "out"), resolve(here, "..", "public", "data"));
  const r = scan(dirs, envPath);
  console.log(`canary scan: ${r.files} files, ${r.canaries} .env values in memory, ${r.hits.length} hits`);
  for (const h of r.hits) console.log(`  HIT ${h.kind}: ${h.file}`);
  process.exit(r.hits.length ? 1 : 0);
}
