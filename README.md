# Q-Day Radar

Q-Day Radar asks a plain question: **how far are today's quantum computers from breaking the
cryptography the internet runs on, and which of your keys should you replace first?**

It runs real Shor and Grover circuits (on a simulator and on IBM quantum hardware), scales what
they cost into resource estimates for RSA-2048, ECC-256 and AES-128, and ranks the assets in a
crypto inventory (a CBOM) by how soon a quantum attacker could reach them.

A personal project, started at Qiskit Fall Fest 2026. <!-- literal: the year the project started -->

**Live site: <https://q-day-web-q-day.vercel.app>**: four screens (an overview radar, the circuit
lab, the scaling chart, the inventory) where every figure on screen can be traced to the data file
it came from.

## What it found

The headline: today's machines are far too small and too noisy. Every number below is written by
`scripts/build_readme.py` from the result files, never typed.

### The circuits we ran

<!-- gen:device -->
Hardware runs used **ibm_kingston** (156 qubits). 6 circuits ran on it: 3 came out above random guessing, 3 were no better than random guessing.
<!-- /gen:device -->

<!-- gen:lab-table -->
| circuit | kind | ideal simulator | noisy simulator | hardware (raw run) | random guessing | hardware vs random guessing |
|---|---|---|---|---|---|---|
| `grover_present_k2` | generic | 100.0% | 69.1% | 50.5% | 25.0% | above random guessing |
| `grover_present_k3` | generic | 94.5% | 40.0% | 14.7% | 12.5% | above random guessing |
| `grover_present_k4` | generic | 96.2% | 22.2% | 5.4% | 6.2% | no better than random guessing |
| `grover_present_k5` | generic | 99.9% | 7.3% | 2.8% | 3.1% | no better than random guessing |
| `shor15_beauregard` | generic | 50.6% | 18.3% | 17.5% | 17.2% | no better than random guessing |
| `shor15_textbook` | compiled | 50.8% | 43.9% | 35.8% | 17.2% | above random guessing |
| `shor21_beauregard` | generic | 32.7% | 7.7% | not run | 7.8% | not run on hardware |
<!-- /gen:lab-table -->

"Ideal simulator" is a perfect machine. "Noisy simulator" copies the noise of the real chip.
"Random guessing" is what a coin-flipping machine would score on the same circuit. A hardware
result only counts as a signal when it clears that line by more than its statistical error.

### How big a machine would have to be

<!-- gen:gap -->
| target | physical qubits needed (published estimate) | times ibm_kingston (156 qubits) | times the record chip (1,121 qubits, 2023) |
|---|---|---|---|
| ECC-256 | 500,000 | 3,205× | 446× |
| RSA-2048 | 897,864 | 5,756× | 801× |
<!-- /gen:gap -->

These qubit counts are published estimates, not our own. The multiples compare them with the chip
we ran on and with the largest chip ever built.

### When could it happen?

<!-- gen:crqc -->
Doubling time of the largest machine built each year: 1.27 years. Held-out check: the fit predicted 2,299 qubits for 2025, the real figure was 1,121 (error 105.1%).

| scenario | ECC-256 reachable (year) | RSA-2048 reachable (year) |
|---|---|---|
| optimistic | 2034.7 | 2035.5 |
| median | 2037.2 | 2038.2 |
| pessimistic | 2041.6 | none inside the runtime cap |
<!-- /gen:crqc -->

A year in this table is a trend extrapolation: we fit how fast the largest machine has grown and
ask when the trend reaches the size an attack needs. The held-out check above shows how well the
method predicted a year it had not seen, and that miss is large. Read the years as a rough
ordering, not a forecast.

### Which keys first?

<!-- gen:inventory -->
The demo inventory has 42 assets. In the median scenario 13 are already exposed (their Mosca margin is negative) and 2 are classically deprecated. Soonest break: 2037.2.

| rank | asset | algorithm | Mosca margin (years) |
|---|---|---|---|
| 1 | device secure-boot root | ECDSA | -21.8 |
| 2 | long-lived signed contracts | RSA-2048 | -22.8 |
| 3 | firmware and app release signing | RSA-3072 | -13.8 |
| 4 | archive key wrapping | RSA-4096 | -22.8 |
| 5 | settlement ledger keys | ECDSA | -9.8 |
<!-- /gen:inventory -->

Ranks use the scenario shown (median). The inventory is a small demo CBOM, and the exposure
weights that turn a margin into a rank are a design choice, not a measurement.

For comparison, NIST's own deadlines for moving off quantum-vulnerable algorithms:

<!-- gen:nist -->
- 2030: federal high value assets and high impact systems
- 2031: federal high value assets and high impact systems
- 2030: NIST: quantum-vulnerable algorithms deprecated after this year
- 2035: NIST: quantum-vulnerable algorithms disallowed after this year
<!-- /gen:nist -->

## Read this before quoting a number (honesty notes)

- **Shor "success" means the order was found, not that N was factored.** Turning an order into
  factors is one more classical step that works for some bases and fails for others, so each Shor
  number says which of the two it means.
- **The textbook Shor circuit for N=15 is `compiled`**: <!-- literal: the number being factored --> it has the answer's structure built in, so
  it is not evidence about Shor in general. The `generic` Beauregard circuits are the fair test, and
  on hardware they are a null check. They came out at the level of random guessing, as predicted.
  They are not a demonstration.
- **The noisy simulator over-estimated every hardware result.** We never quote it as what hardware
  will do.
- **Grover on the toy cipher is not an AES projection.** At full AES size we quote only the
  selected resource estimate with its bracket, never a free extrapolation of the small-case costs.
- **Break years are trend extrapolations**, shown with the held-out error. The pessimistic scenario
  differs from the median only in assumed cycle time. The ECC-first order rests on upper bounds in
  Google's 2026 estimate <!-- literal: year of the cited paper -->. Other 2026 designs (ions, neutral atoms, cat qubits, qLDPC codes) claim
  far fewer qubits, so a surface-code timeline may be late. <!-- literal: the year of the cited paper -->
- **NIST IR 8547** <!-- literal: NIST document number --> sets earlier deadlines for high-value federal systems than the final disallow
  year (see the list above).
- **Not measured:** screen-reader use, performance in the field, and any browser other than
  Chromium. The site's SSL Labs grade is A, not A+: SSL Labs' scanner is blocked by the host's
  bot protection, so it cannot see the HSTS header that the project's own check reads directly.

## Run it yourself

Python (3.11 or newer, [uv](https://docs.astral.sh/uv/)): <!-- literal: Python version -->

```bash
uv sync
uv run pytest -m "not hardware"                  # the test suite (simulators only)
uv run python scripts/build_data.py --verify     # the web data matches the result files
uv run python scripts/build_readme.py --verify   # the numbers above match the data
```

Web (Node 24): <!-- literal: Node version -->

```bash
cd web
npm ci
npm run build      # static export into web/out/
npm run start      # serve it locally
```

Hardware runs need an IBM Quantum account and a token in `.env`. They are never run by the tests,
and the code refuses to send a job unless a local budget ledger allows it.

## How it is organised

| folder | what is in it |
|---|---|
| [`quantum/`](quantum/README.md) | circuits, simulators, resource estimators, the risk model |
| [`web/`](web/README.md) | the static site |
| [`results/`](results/README.md) | raw outputs of every run (hardware results are never edited) |
| [`scripts/`](scripts/README.md) | commands that produce the results, the web data and these READMEs |
| [`tests/`](tests/README.md) | tests that try to catch a wrong answer, not just a crash |
| [`benchmarks/`](benchmarks/README.md) | before-and-after measurements behind every optimisation claim |

## Security posture

- The site is static: no server code, no API routes, no analytics, no third-party scripts, fonts or
  requests.
- Content-Security-Policy with a hash for every inline script, computed from the deployed build,
  plus HSTS (with preload), `nosniff`, a strict referrer policy and a locked-down permissions
  policy on every route.
- Mozilla Observatory grade A+. SSL Labs grade A (see the notes above for why not A+).
- A build-time scan looks for secret-shaped strings and the real values of local secrets in the
  output. A secret scanner (gitleaks) runs as a commit hook and on every push.
- Report a problem through this repository's GitHub security advisories.

## How this was built

The project was built in phases, and every phase ran the same loop: **plan, build, test, improve,
gate**.

- Three Claude Code sessions worked side by side, each with one role: a **lead** that wrote each
  phase's plan and made the accept/reject calls, a **builder** that wrote the code, and a
  **reviewer** that wrote tests meant to catch a wrong answer and proposed improvements. Each
  session owned its own files and asked the owner for changes elsewhere.
- A **gate** ended every phase. It is a script that recomputes every published number from the
  data, runs the whole test suite, checks the security headers, and fails the phase if any check
  fails. Nothing moved on with a red gate.
- **The human approved every hardware run.** The free IBM plan allows only a few QPU minutes per
  period, so every circuit was proved on the noisy simulator first and a budget ledger gates the
  job-sending code.
- No factor, order or key is hard-coded into a circuit that is meant to find it. Each circuit is
  labelled `generic` or `compiled` in its metadata.

## Credits and licence

Built with [Qiskit](https://qiskit.org/), IBM Quantum hardware, Microsoft's Azure Quantum Resource
Estimator, [Qualtran](https://qualtran.readthedocs.io/), [Next.js](https://nextjs.org/) and the
IBM Plex typefaces (SIL Open Font License). Resource figures come from published papers listed in
`quantum/estimate/literature.yaml`.

Licensed under the [MIT licence](LICENSE).
