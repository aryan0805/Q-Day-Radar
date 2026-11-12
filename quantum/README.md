# quantum/

The Python package behind every result: the circuits, the ways of running them, the resource
estimators and the risk model.

In plain terms: this folder builds Shor and Grover circuits, runs them (on a simulator or, with
approval, on IBM hardware), counts what a full-size attack would cost, and turns that into a ranking
of an inventory's keys.

| folder / file | what it does |
|---|---|
| `circuits/` | the circuits. `shor_textbook.py` (compiled for one N), `beauregard.py` (generic modular exponentiation), `grover_present.py` (Grover over a toy cipher), `registry.py` (the list the rest of the code reads) |
| `classical/` | classical helpers: post-processing of measurement counts, the toy cipher, theory values |
| `run/` | `noisy.py` (noisy simulator), `hardware.py` (IBM hardware), `budget.py` (QPU-seconds ledger), `stats.py` |
| `estimate/` | resource estimators and the literature file `literature.yaml`; scaling fits; scenarios |
| `risk/` | Mosca margin, the CRQC timeline, the inventory model and the code that builds the web data |
| `backends.py`, `metrics.py` | the fake backend of the chip we ran on; circuit metrics |

## Rules the code follows

- **Qiskit 2.x only** <!-- literal: Qiskit major version --> (`SamplerV2`, `EstimatorV2`,
  `generate_preset_pass_manager`; no `execute`, no `BackendV1`).
- **Every circuit function returns the circuit plus metadata**: `name`, `kind` (`generic` or
  `compiled`), `n_qubits`, `params`.
- **Nothing hard-codes the answer** (a factor, an order or a key) into a circuit meant to find it.
  `compiled` marks the one circuit where the structure of the answer is built in.
- **No hardware job is sent unless `run/budget.py` approves it.** The free plan allows a few
  QPU minutes per period; the ledger lives in `results/budget.json`.

## Try one

```bash
uv run python -c "from quantum.circuits import registry; print(registry)"
uv run pytest tests -m "not hardware"
```
