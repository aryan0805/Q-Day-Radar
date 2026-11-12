# scripts/

Commands that produce the results, the web data and the READMEs. Run them with `uv run python
scripts/<name>.py`.

| script | what it does |
|---|---|
| `run_noisy.py` | run the circuits on the noisy simulator, write `results/noisy/` |
| `plan_hardware.py` | plan a hardware batch within the QPU budget (a plan, nothing sent) |
| `submit_hardware.py` | submit a planned batch; needs the human's approval and `budget.py`'s consent |
| `analyze_hardware.py` | compare hardware counts with random guessing and the simulator |
| `transpile_compare.py`, `record_metrics.py` | circuit depth and gate-count measurements |
| `estimate_all.py`, `estimate_qdk.py`, `estimate_qualtran.py`, `estimate_compare.py`, `estimate_scenarios.py` | resource estimates and their cross-check |
| `risk_timeline.py` | fit the hardware growth trend and the CRQC years |
| `make_demo_cbom.py` | build the demo inventory the Inventory screen ranks |
| `build_data.py` | write `web/public/data/` from `results/` (`--verify` checks it is byte-exact) |
| `build_readme.py` | fill the generated number blocks in the READMEs (`--verify` checks them) |
| `make_public.py` | build the public copy of the repository (a dry run unless `--push` is given) |
| `gate.py` | the phase gate: recomputes the published numbers and runs every check |

Sending a hardware job is the only script that spends the QPU budget. Everything else is safe to
re-run.
