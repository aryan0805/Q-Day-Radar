# tests

These tests exist to catch a **wrong answer**, not only a crash. Each phase has its own folder,
written by a different session from the one that wrote the code under test, against known values
and independent reference code that imports nothing from `quantum/`.

## Run them

```bash
uv sync
uv run pytest -m "not hardware"          # everything that never touches IBM hardware
uv run pytest tests/phase3 -k crosscheck  # one folder or keyword
```

The site tests in `phase5/` drive a real Chromium through Playwright, so build the site and fetch
the browser first:

```bash
npm --prefix web ci && npm --prefix web run build
uv run playwright install chromium
```

Anything that would submit a job to IBM hardware carries `@pytest.mark.hardware` and is skipped by
`-m "not hardware"`. The project's checks never run those. A hardware run needs the human's
approval in the terminal and spends a small monthly budget (see [results](../results/README.md)).

## What each folder checks

| folder | what it proves |
| --- | --- |
| `phase0/` | the environment, the simulator backends, and the QPU budget guard |
| `phase1/` | Shor and Grover circuits give the known answers on the ideal simulator; no circuit leaks the answer it is meant to find. Audit: [phase1/AUDIT.md](phase1/AUDIT.md) |
| `phase2/` | noisy simulation and the hardware pipeline: statistics recomputed from raw counts, the approval and budget rules, and the stored hardware batch against its pre-registered prediction. Audit: [phase2/AUDIT.md](phase2/AUDIT.md) |
| `phase3/` | resource estimates: gate counts against an independent parser, the two estimators against each other, scaling fits, the literature numbers against their sources. Audit: [phase3/AUDIT.md](phase3/AUDIT.md) |
| `phase4/` | the risk model: Mosca margins against hand-computed cases, the timeline fit, the demo inventory. Audit: [phase4/AUDIT.md](phase4/AUDIT.md) |
| `phase5/` | the site: every figure on screen traced to a data file, scenario switching, keyboard access, security headers, reduced motion, speed and bundle size. Audit: [phase5/AUDIT.md](phase5/AUDIT.md) |
| `phase6/` | the public repository: README figures and links, banned wording, no dead pointers, and the publish script on a scratch repository |

## How the tests are built

- **Deterministic.** Seeds are fixed (`seed_simulator`, `seed_transpiler`), so a failure is a real
  failure.
- **Planted defects.** Where a test guards a rule, a companion test plants one defect in a temporary
  copy (a wrong figure, a leaked path, a missing tag) and requires the check to fail. A check that
  cannot fail proves nothing.
- **Missing inputs fail, they do not skip.** Loaders fail loudly when a promised file is missing.
- **Reference code is independent.** Each `reference.py` is written from the specification and
  textbook formulas, never copied from the code it checks.
- **`data/`** holds a few facts that were copied once from the development notes (the order in which
  one set of parameters was fixed, and which cross-check cases have a written explanation). The
  script `data/copy_private_facts.py` prints every source line it uses. Tests read the copy and
  never the notes, because the notes are not part of this repository.

Every phase folder with an `AUDIT.md` explains what was checked, what was not, and why.
