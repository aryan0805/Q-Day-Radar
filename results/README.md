# results/

Raw outputs of every run. This is the evidence; the site and the READMEs are computed from it.

**Hardware results are immutable: they are added, never edited.** If a run is replaced, the old one
stays and gets a note saying why.

| folder | what is in it |
|---|---|
| `hardware/<batch>/` | one IBM hardware batch: the plan, the human's approval, one file per job (`jobs/`), the circuits as sent, the log of what was sent |
| `noisy/` | one file per circuit from the noisy simulator (seeded) |
| `metrics/` | circuit metrics (depth, gate counts) per circuit |
| `transpile/` | transpilation comparisons |
| `estimate/` | resource estimates: our two estimators (`qdk/`, `qualtran/`), the cross-check between them, the scaling fits and the three scenarios |
| `risk/` | the CRQC timeline fit |
| `analysis/` | analysis of a hardware batch (success against random guessing, drift) |
| `budget.json` | the QPU-seconds ledger that every hardware job is checked against |

One hardware batch is marked `SUPERSEDED.md`: it was planned, replaced before approval, and never
submitted.

## How it relates to the rest

`scripts/build_data.py` reads these files and writes `web/public/data/`. The READMEs get their
numbers from that data through `scripts/build_readme.py`. To check that nothing drifted:

```bash
uv run python scripts/build_data.py --verify
uv run python scripts/build_readme.py --verify
```
