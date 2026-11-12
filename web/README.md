# web/

The Q-Day Radar site: a static Next.js export, deployed to <https://q-day-web-q-day.vercel.app>.

In plain terms: four screens that show the project's real results. Every figure on screen sits in
an element that names the data file and path it came from, and hovering or focusing it shows the
file, the seeds and shots where they exist, and one label: hardware, simulated, trend
extrapolation, published estimate or design choice.

| screen | route | shows |
|---|---|---|
| Overview | `/` | the radar: how soon each key family is reachable, with a scroll-driven hero |
| Lab | `/lab/` | the circuits: ideal, noisy simulator and hardware, each next to random guessing |
| Scaling | `/scaling/` | the cost of attacks as the problem grows, from our chip's size to what an attack needs |
| Inventory | `/inventory/` | a demo CBOM ranked by Mosca margin, with a drawer that explains each rank |

The scenario (optimistic, median, pessimistic) lives in the URL: `?s=optimistic`.

## Where things are

- `src/app/` pages, `src/components/` screens and parts, `src/styles/tokens.css` the design tokens.
- `public/data/` the JSON every figure comes from. **Generated** by `scripts/build_data.py` from
  `results/`; never edit by hand. `public/data/schema/` holds the schemas.
- `scripts/postbuild.mjs` runs after the build: writes `build.json` (the commit), `security.txt`,
  the Content-Security-Policy hashes and the headers, then scans the output for secrets.

## Build and check

```bash
npm ci
npm run lint         # eslint, zero warnings allowed
npm run typecheck
npm run build        # static export into out/
npm run start        # serve out/ locally
```

Node 24. <!-- literal: Node version in package.json engines -->

## Design rules

- Static export only. No server code, no API routes, no analytics, no third-party scripts, fonts or
  requests; fonts are self-hosted IBM Plex.
- The build reads only `NODE_ENV`; there are no `NEXT_PUBLIC_` variables and no `.env` file here.
- Motion respects the reduced-motion setting: no running animations, the hero shows a static strip.
- A dev-only tweak panel exists for design work and is not part of the production build.
- Not measured: screen-reader use, field performance, browsers other than Chromium.
