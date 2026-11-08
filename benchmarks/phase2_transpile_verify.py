"""Independent re-computation of the phase-2 transpile numbers (opt level 3, FakeKingston)."""

import json
import statistics
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from qiskit import __version__ as qiskit_version
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from quantum.backends import get_fake_backend
from quantum.circuits.registry import build_circuit

ROOT = Path(__file__).resolve().parent.parent
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


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main():
    rec = json.loads((ROOT / "results/transpile/phase2-compare.json").read_text())
    after = json.loads((ROOT / "benchmarks/phase1-after-r1.json").read_text())["circuits"]
    base = json.loads((ROOT / "benchmarks/phase1-baseline.json").read_text())["circuits"]
    backend = get_fake_backend()
    out = {}
    for name in NAMES:
        qc = build_circuit(name)
        per, depth = {}, {}
        for s in SEEDS:
            pm = generate_preset_pass_manager(
                optimization_level=3, backend=backend, seed_transpiler=s
            )
            t = pm.run(qc)
            per[str(s)] = t.num_nonlocal_gates()
            depth[str(s)] = t.depth()
        vals = list(per.values())
        r = rec["circuits"][name]["opt3"]
        rec_per = {k: v["two_qubit_gates"] for k, v in r["per_seed"].items()}
        med = statistics.median(vals)
        a, b = after.get(name), base.get(name)
        out[name] = {
            "recomputed": {
                "per_seed": per,
                "median": med,
                "min": min(vals),
                "max": max(vals),
                "depth_seed1234": depth["1234"],
                "depth_median": statistics.median(depth.values()),
            },
            "recorded": {
                "per_seed": rec_per,
                "median": r["two_qubit_gates_median"],
                "min": r["two_qubit_gates_min"],
                "max": r["two_qubit_gates_max"],
                "depth_seed1234": r["per_seed"]["1234"]["depth"],
                "depth_median": r["depth_median"],
            },
            "match": rec_per == per
            and r["two_qubit_gates_median"] == med
            and r["two_qubit_gates_min"] == min(vals)
            and r["two_qubit_gates_max"] == max(vals)
            and r["per_seed"]["1234"]["depth"] == depth["1234"]
            and r["depth_median"] == statistics.median(depth.values()),
            "phase1_after_r1_median": a["two_qubit_median"] if a else None,
            "phase1_after_r1_per_seed": a["two_qubit_by_seed"] if a else None,
            "phase1_baseline_median": b["two_qubit_median"] if b else None,
            "equals_after_r1": bool(a) and a["two_qubit_median"] == med,
            "equals_baseline": bool(b) and b["two_qubit_median"] == med,
            "chosen_recorded": rec["circuits"][name]["chosen"],
        }
    result = {
        "optimization_level": 3,
        "backend": "FakeKingston",
        "seeds": SEEDS,
        "qiskit_version": qiskit_version,
        "recorded_qiskit_version": rec["qiskit_version"],
        "git_head": git("rev-parse", "HEAD"),
        "git_status_quantum_scripts": git("status", "--short", "quantum", "scripts"),
        "timestamp": datetime.now(UTC).isoformat(),
        "ai_pass_recorded": rec["ai_pass"],
        "ai_pass_run_by_reviewer": False,
        "circuits": out,
    }
    (ROOT / "benchmarks/phase2-transpile.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# Phase 2 transpile verification",
        "",
        f"Optimization level 3, FakeKingston, 5-seed medians, seeds {SEEDS[0]}..{SEEDS[-1]}, "
        f"qiskit {qiskit_version}. Metric: `num_nonlocal_gates()` after transpile.",
        "",
        "| circuit | median 2q | min..max | recorded median | match | depth (seed 1234) |",
        "|---|---|---|---|---|---|",
    ]
    for n, c in out.items():
        x = c["recomputed"]
        lines.append(
            f"| {n} | {x['median']} | {x['min']}..{x['max']} | {c['recorded']['median']} | "
            f"{'yes' if c['match'] else 'NO'} | {x['depth_seed1234']} |"
        )
    lines += ["", "## Cross-check with phase 1", ""]
    for n, c in out.items():
        lines.append(
            f"- {n}: after-r1 median {c['phase1_after_r1_median']} "
            f"({'equal' if c['equals_after_r1'] else 'DIFFERENT'}); baseline median "
            f"{c['phase1_baseline_median']} ({'equal' if c['equals_baseline'] else 'different'})"
        )
    ai = rec["ai_pass"]
    lines += [
        "",
        "## AI transpiler pass",
        "",
        "The AI transpiler pass was NOT run by the reviewer, so there are no AI numbers here.",
        "",
        f"- mode: {ai['mode']}",
        f"- reason: {ai['reason']}",
        "",
        "This reason is as recorded by builder and was not reproduced by the reviewer "
        "(no install was attempted).",
        "",
        "Opt level 3 is therefore kept for every circuit (`chosen`: opt3).",
        "",
        f"Git HEAD {result['git_head']}; timestamp {result['timestamp']}.",
        "",
    ]
    (ROOT / "benchmarks/phase2-transpile.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
