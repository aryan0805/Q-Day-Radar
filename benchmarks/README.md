# benchmarks

Before and after measurements, and the audit tables that sit beside the tests. Every figure in
here is **printed by a script from result files or a real build**. Nothing is typed by hand, so a
number in a `.md` file can be reproduced by running the script next to it.

## What is here

| files | what they measure |
| --- | --- |
| `phase1_*.py`, `phase1-*.json`, `phase1-*.md` | transpiled depth and two-qubit gate counts of the Shor and Grover circuits, before and after an optimisation, and how the cost varies with the base `a` |
| `phase2_*.py`, `phase2-*.json`, `phase2-*.md` | transpile checks for the hardware plan, and the stored hardware batch against the prediction made before it ran |
| `phase3-*.py`, `phase3-*.json` | how far the two resource estimators and the independent gate-count parser disagree, and the effect of the estimator's default transpilation |
| `phase5-*.py`, `phase5-*.json`, `phase5-*.md` | the site: JavaScript a visitor downloads (gzipped), and Lighthouse scores on every screen |
| `phase5-screens/` | screenshots of every screen at three widths, taken by the site tests |
| `results/` | dated raw output of the first two groups |
| `phase3-build-audit.py`, `phase4-build-audit.py`, `phase5-build-audit.py` | render the audit notes in `tests/phaseN/AUDIT.md`: the prose is in the script and every number is computed |

A claim that something got faster or smaller needs a before and an after file here. Where nothing
was worth optimising, no benchmark was written.

## Run one

Scripts print what they measure and write their result next to themselves.

```bash
uv run python benchmarks/phase3-tool-deviation.py
PYTHONPATH=. uv run python benchmarks/phase5-lighthouse.py   # needs the built site, see ../web/README.md
```

Each script's docstring names its inputs and its output files. The audit notes they feed are in
[../tests/README.md](../tests/README.md).

## What these numbers are not

Lighthouse and bundle sizes are **lab measurements on a local server**, not field data. Simulator
results are never quoted as a prediction of what hardware will do (the noisy simulator
overestimated every hardware result).
