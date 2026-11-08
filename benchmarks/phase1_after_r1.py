"""Phase 1 OPTIMIZE round 1: AFTER measurement vs saved BEFORE baseline."""

from __future__ import annotations

import datetime as dt
import json
import statistics
import subprocess
import time
from pathlib import Path

import qiskit
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from quantum.backends import get_fake_backend
from quantum.circuits.registry import build_circuit

ROOT = Path(__file__).resolve().parent.parent
BENCH = Path(__file__).resolve().parent
NAMES = [
    "shor15_textbook",
    "shor15_beauregard",
    "shor21_beauregard",
    "grover_present_k2",
    "grover_present_k3",
    "grover_present_k4",
    "grover_present_k5",
]
SEEDS = [1234, 1235, 1236, 1237, 1238]
WHAT = {
    "shor15_textbook": "correctness fix, not an optimization (F1 reversed swap order)",
    "shor15_beauregard": "unchanged (round 2)",
    "shor21_beauregard": "unchanged (round 2)",
    "grover_present_k2": "plan A: plaintexts (1,6)",
    "grover_present_k3": "plan A: plaintexts (1,6)",
    "grover_present_k4": "plan A: plaintexts (1,6)",
    "grover_present_k5": "plan A: plaintexts (1,6,11)",
}


def sh(*cmd: str) -> str:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def main() -> None:
    before = json.loads((BENCH / "phase1-baseline.json").read_text())["circuits"]
    backend = get_fake_backend()
    rows = {}
    for name in NAMES:
        qc = build_circuit(name)
        by_seed, secs, depth = {}, [], None
        for seed in SEEDS:
            pm = generate_preset_pass_manager(
                optimization_level=3, backend=backend, seed_transpiler=seed
            )
            t0 = time.perf_counter()
            out = pm.run(qc)
            secs.append(time.perf_counter() - t0)
            by_seed[seed] = out.num_nonlocal_gates()
            if seed == 1234:
                depth = out.depth()
        vals = list(by_seed.values())
        b = before[name]
        b_vals = list(b["two_qubit_by_seed"].values())
        b_range = max(b_vals) - min(b_vals)
        a_range = max(vals) - min(vals)
        b_med, a_med = b["two_qubit_median"], statistics.median(vals)
        thresh = max(b_range, a_range)
        rows[name] = {
            "logical_qubits": qc.num_qubits,
            "logical_size_before": b["logical_size"],
            "logical_size_after": qc.size(),
            "two_qubit_by_seed": {str(k): v for k, v in by_seed.items()},
            "two_qubit_min": min(vals),
            "two_qubit_median": a_med,
            "two_qubit_max": max(vals),
            "before_two_qubit_median": b_med,
            "before_two_qubit_min": min(b_vals),
            "before_two_qubit_max": max(b_vals),
            "before_seed1234": b["two_qubit_gates_seed1234"],
            "after_seed1234": by_seed[1234],
            "abs_change": a_med - b_med,
            "pct_change": 100.0 * (a_med - b_med) / b_med,
            "noise_threshold": thresh,
            "verdict": "improved" if (b_med - a_med) > thresh else "no significant change",
            "transpiled_depth_seed1234": depth,
            "before_depth_seed1234": b["transpiled_depth_seed1234"],
            "transpile_seconds_median": statistics.median(secs),
            "what_changed": WHAT[name],
        }
    meta = {
        "state": "AFTER_R1",
        "head": sh("git", "rev-parse", "HEAD"),
        "git_status_quantum": sh("git", "status", "--short", "quantum"),
        "qiskit_version": qiskit.__version__,
        "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "optimization_level": 3,
        "backend": "FakeKingston",
        "seeds": SEEDS,
    }
    doc = {"meta": meta, "circuits": rows}
    text = json.dumps(doc, indent=2)
    (BENCH / "phase1-after-r1.json").write_text(text)
    res = BENCH / "results" / f"phase1-after-r1-{dt.date.today().isoformat()}.json"
    res.write_text(text)

    md = [
        "# Phase 1 OPTIMIZE round 1: AFTER vs BEFORE",
        "",
        "- Round: OPTIMIZE round 1, optimization level 3, FakeKingston, 5-seed medians "
        "(seeds 1234..1238)",
        f"- git HEAD: `{meta['head']}`",
        "- `git status --short quantum`:",
        "```",
        meta["git_status_quantum"],
        "```",
        "- Verdict: 'improved' only if AFTER median is lower than BEFORE median by more than "
        "the larger of the two 5-seed ranges (max-min); otherwise 'no significant change'.",
        "",
        "| circuit | BEFORE median 2q | AFTER median 2q | abs change | % change | "
        "BEFORE seed1234 | AFTER seed1234 | AFTER min/max | noise | verdict | what changed |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for n, r in rows.items():
        md.append(
            f"| {n} | {r['before_two_qubit_median']} | {r['two_qubit_median']} | "
            f"{r['abs_change']:+g} | {r['pct_change']:+.1f}% | {r['before_seed1234']} | "
            f"{r['after_seed1234']} | {r['two_qubit_min']}/{r['two_qubit_max']} | "
            f"{r['noise_threshold']} | {r['verdict']} | {r['what_changed']} |"
        )
    md += [
        "",
        "Logical size (qc.size()) BEFORE vs AFTER, Grover k=2..4:",
        "",
        "| circuit | BEFORE | AFTER |",
        "|---|---|---|",
    ]
    for n in ("grover_present_k2", "grover_present_k3", "grover_present_k4"):
        md.append(f"| {n} | {rows[n]['logical_size_before']} | {rows[n]['logical_size_after']} |")
    md += [
        "",
        "Note: round 1 was plan A (`quantum/circuits/registry.py` GROVER_PLAINTEXTS now (1,6) "
        "for k=2,3,4 and (1,6,11) for k=5; a registry/demo-instance change, builder code "
        "untouched). shor15_textbook also changed because the F1 correctness fix reversed its "
        "swap order (181 2q at seed 1234 vs 180); this is a bug fix and NOT an optimization "
        "(correctness fix, not an optimization). shor15_beauregard and shor21_beauregard are "
        "unchanged and belong to round 2.",
        "",
    ]
    (BENCH / "phase1-after-r1.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
