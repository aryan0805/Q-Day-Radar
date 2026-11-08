# ruff: noqa: E501
"""Observed vs pre-registered prediction for the Phase 2 hardware batch. Read-only on results/.

    uv run python benchmarks/phase2_hardware_report.py

Every number is recomputed from results/hardware/<batch>/jobs/*.json (raw counts) and plan.json
with tests/phase2/reference.py, and sits next to its chance baseline, shots and seeds.
Writes benchmarks/phase2-hardware-vs-prediction.{json,md}. Not a test: tests/phase2/test_real_batch.py
asserts the same facts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantum.circuits.registry import SUCCESS_FN, build_circuit  # noqa: E402
from tests.phase2 import reference as ref  # noqa: E402

BATCH = "batch-20261108T044751Z"
HW = ROOT / "results" / "hardware" / BATCH
SHOTS = 4096
ORDER = ["shor15_beauregard", "shor15_textbook", *[f"grover_present_k{k}" for k in (2, 3, 4, 5)]]


def main() -> None:
    plan = json.loads((HW / "plan.json").read_text())
    raw = {
        j["index"]: json.loads((HW / "jobs" / f"{j['index']}.json").read_text())
        for j in plan["jobs"]
    }
    rows = []
    for name in ORDER:
        meta = build_circuit(name).metadata
        theory, chance = meta["theoretical_success"], meta["chance_baseline"]
        for cfg in ("raw", "dd", "dd_twirl"):
            jobs = [j for j in plan["jobs"] if j["name"] == name and j["config"] == cfg]
            if not jobs:
                continue
            hits = [
                sum(v for b, v in raw[j["index"]]["counts"].items() if SUCCESS_FN[name](b))
                for j in jobs
            ]
            n = SHOTS * len(hits)
            s = sum(hits) / n
            lo, hi = ref.wilson(sum(hits), n)
            pred = jobs[0]["prediction"]["success_probability"]
            rows.append(
                {
                    "circuit": name, "config": cfg, "kind": jobs[0]["kind"], "jobs": [j["index"] for j in jobs],
                    "repeat_success": [h / SHOTS for h in hits], "pooled_success": s, "wilson_95": [lo, hi],
                    "shots_total": n, "chance_baseline": chance, "theoretical_success": theory,
                    "normalized_score": ref.normalized(s, theory, chance), "predicted_success": pred,
                    "observed_minus_predicted": s - pred, "wilson_lo_above_chance": lo > chance,
                }
            )  # fmt: skip
    out = {
        "batch": BATCH, "backend": plan["backend"], "shots_per_job": SHOTS,
        "seed_transpiler": plan["seed_transpiler"], "prediction_seed_simulator": 1234,
        "note": "pooled Wilson understates uncertainty when repeats drift (see AUDIT.md)", "rows": rows,
    }  # fmt: skip
    (ROOT / "benchmarks" / "phase2-hardware-vs-prediction.json").write_text(
        json.dumps(out, indent=2) + "\n"
    )
    lines = [
        f"# Phase 2 hardware vs pre-registered prediction ({BATCH}, {plan['backend']})",
        "",
        f"{SHOTS} shots per job, 2 repeats per static config (1 for shor15_beauregard); transpile seed "
        f"{plan['seed_transpiler']}; predictions are Aer simulations of the same ISA with the live "
        "Kingston calibration (seed 1234). Success next to its chance baseline; normalized = (s-c)/(t-c).",
        "",
        "| circuit | config | repeats | pooled | Wilson 95% | chance | theory | normalized | predicted | obs-pred | lo>chance |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        reps = " / ".join(f"{x:.4f}" for x in r["repeat_success"])
        lines.append(
            f"| {r['circuit']} | {r['config']} | {reps} | {r['pooled_success']:.4f} | "
            f"[{r['wilson_95'][0]:.4f}, {r['wilson_95'][1]:.4f}] | {r['chance_baseline']:.4f} | "
            f"{r['theoretical_success']:.4f} | {r['normalized_score']:+.3f} | {r['predicted_success']:.4f} | "
            f"{r['observed_minus_predicted']:+.4f} | {'yes' if r['wilson_lo_above_chance'] else 'no'} |"
        )
    (ROOT / "benchmarks" / "phase2-hardware-vs-prediction.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
