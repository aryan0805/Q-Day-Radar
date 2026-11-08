# ruff: noqa: E501
"""Phase 1 OPTIMIZE: BEFORE baseline (opt level 3, FakeKingston). Deterministic counts."""

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
from quantum.circuits.beauregard import build_shor
from quantum.circuits.registry import build_circuit

ROOT = Path(__file__).resolve().parent.parent
BENCH = Path(__file__).resolve().parent
NAMES = [
    "shor15_textbook",
    "shor21_beauregard",
    "grover_present_k2",
    "grover_present_k3",
    "grover_present_k4",
    "grover_present_k5",
    "shor15_beauregard",
]
SKIP_ROW = "shor15_beauregard_skip_identity"  # compiled variant, NOT a registry circuit
RUN_SUFFIX = "-b"
SEEDS = [1234, 1235, 1236, 1237, 1238]
TIMING_REPEATS = 3  # seed 1234 transpile is repeated; counts must not change


def sh(*cmd: str) -> str:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def transpile(qc, backend, seed):
    pm = generate_preset_pass_manager(
        optimization_level=3, backend=backend, seed_transpiler=seed
    )
    t0 = time.perf_counter()
    out = pm.run(qc)
    return out, time.perf_counter() - t0


def main() -> None:
    backend = get_fake_backend()
    rows = {}
    for name in [*NAMES, SKIP_ROW]:
        qc = build_shor(15, 7, skip_identity=True) if name == SKIP_ROW else build_circuit(name)
        per_seed, secs, depth = {}, [], None
        for seed in SEEDS:
            reps = TIMING_REPEATS if seed == 1234 else 1
            for _ in range(reps):
                out, s = transpile(qc, backend, seed)
                if seed == 1234:
                    secs.append(s)
                    if depth is not None:
                        assert (depth, per_seed[seed]) == (out.depth(), out.num_nonlocal_gates())
                    depth = out.depth()
                per_seed[seed] = out.num_nonlocal_gates()
        counts = list(per_seed.values())
        rows[name] = {
            "logical_qubits": qc.num_qubits,
            "logical_size": qc.size(),
            "two_qubit_gates_seed1234": per_seed[1234],
            "transpiled_depth_seed1234": depth,
            "transpile_seconds": secs,
            "transpile_seconds_median": statistics.median(secs),
            "two_qubit_by_seed": {str(k): v for k, v in per_seed.items()},
            "two_qubit_min": min(counts),
            "two_qubit_median": statistics.median(counts),
            "two_qubit_max": max(counts),
        }
        if name == SKIP_ROW:
            rows[name]["kind"] = "compiled (skip_identity=True), not a registry circuit"
            rows[name]["metrics_json"] = {"match": None}
            print(f"done {name}", flush=True)
            continue
        m = json.loads((ROOT / "results/metrics" / f"{name}.json").read_text())
        rows[name]["metrics_json"] = {
            "two_qubit_gates": m["two_qubit_gates"],
            "transpile_depth": m["transpile"]["depth"],
            "match": m["two_qubit_gates"] == per_seed[1234]
            and m["transpile"]["depth"] == depth,
        }
        print(f"done {name}", flush=True)

    now = dt.datetime.now(dt.UTC)
    meta = {
        "head": sh("git", "rev-parse", "HEAD"),
        "git_status_quantum": sh("git", "status", "--short", "quantum"),
        "qiskit_version": qiskit.__version__,
        "timestamp": now.isoformat(),
        "optimization_level": 3,
        "backend": "FakeKingston",
        "seeds": SEEDS,
        "state": "BEFORE",
    }
    data = {"meta": meta, "circuits": rows}
    payload = json.dumps(data, indent=2) + "\n"
    (BENCH / "phase1-baseline.json").write_text(payload)
    (BENCH / "results").mkdir(exist_ok=True)
    (BENCH / "results" / f"phase1-baseline-{now.date()}{RUN_SUFFIX}.json").write_text(payload)

    lines = [
        "| circuit | logical qubits | logical size | 2q (seed 1234) | 2q min / median / max (5 seeds) "
        "| depth (seed 1234) | transpile s (median of 3) | matches results/metrics |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for n, r in rows.items():
        lines.append(
            f"| {n} | {r['logical_qubits']} | {r['logical_size']} | {r['two_qubit_gates_seed1234']} "
            f"| {r['two_qubit_min']} / {r['two_qubit_median']:g} / {r['two_qubit_max']} "
            f"| {r['transpiled_depth_seed1234']} | {r['transpile_seconds_median']:.2f} "
            f"| {'n/a (compiled)' if r['metrics_json']['match'] is None else 'yes' if r['metrics_json']['match'] else 'NO'} |"
        )
    table = "\n".join(lines)
    allmatch = all(r["metrics_json"]["match"] is not False for r in rows.values())
    verdict = (
        "All seed-1234 two-qubit counts and transpiled depths match results/metrics/*.json."
        if allmatch
        else "MISMATCH vs results/metrics/*.json: "
        + "; ".join(
            f"{n} (here {r['two_qubit_gates_seed1234']}/{r['transpiled_depth_seed1234']}, "
            f"metrics {r['metrics_json']['two_qubit_gates']}/{r['metrics_json']['transpile_depth']})"
            for n, r in rows.items()
            if r["metrics_json"]["match"] is False
        )
    )
    slow = [n for n, r in rows.items() if max(r["transpile_seconds"]) > 180]
    slow_note = f" Circuits over 3 minutes per transpile: {', '.join(slow)}." if slow else (
        " No circuit took more than 3 minutes to transpile."
    )
    header = (
        "# Phase 1 baseline (BEFORE)\n\n"
        "This is the BEFORE state for the Phase 1 OPTIMIZE step: each registry circuit transpiled at "
        "optimization level 3 for FakeKingston with seed_transpiler 1234 (counts and depth), plus the "
        "2-qubit gate count for seeds 1234 to 1238 reported as min / median / max. Wall-clock is the "
        f"median of {TIMING_REPEATS} seed-1234 transpiles. shor15_beauregard is the honest circuit (build_shor(15, 7) applies all 28 controlled swaps, "
        "identity multipliers included). shor15_beauregard_skip_identity is the compiled variant "
        "(build_shor(15, 7, skip_identity=True), the old 1068-gate number); it is not a registry circuit and "
        "is shown only so the cost of honesty is visible. "
        f"Qiskit {qiskit.__version__}, HEAD {meta['head'][:10]}, {meta['timestamp']}. "
        f"{verdict}{slow_note}\n\n"
    )
    hb, sk = rows["shor15_beauregard"], rows[SKIP_ROW]
    mj = hb["metrics_json"]
    cmp_note = (
        "\n\n## shor15_beauregard vs results/metrics/shor15_beauregard.json\n\n"
        f"Seed 1234: here two_qubit_gates {hb['two_qubit_gates_seed1234']}, depth {hb['transpiled_depth_seed1234']}; "
        f"metrics file two_qubit_gates {mj['two_qubit_gates']}, transpile.depth {mj['transpile_depth']}. "
        f"{'They match.' if mj['match'] else 'They do NOT match.'}\n\n"
        "## Cost of honesty\n\n"
        f"Honest (all multipliers) {hb['two_qubit_gates_seed1234']} vs skip_identity {sk['two_qubit_gates_seed1234']} "
        f"two-qubit gates at seed 1234 ({hb['two_qubit_gates_seed1234'] / sk['two_qubit_gates_seed1234']:.2f}x); "
        f"5-seed medians {hb['two_qubit_median']:g} vs {sk['two_qubit_median']:g}.\n\n"
        "## How to compare AFTER\n\n"
        "Rerun with the same backend (FakeKingston), optimization level 3 and seeds 1234 to 1238, and compare "
        "the 5-seed median two-qubit count (not a single seed) against the BEFORE median. Compare "
        "shor15_beauregard against the honest row, never against shor15_beauregard_skip_identity.\n"
    )
    (BENCH / "phase1-baseline.md").write_text(header + table + "\n" + cmp_note)
    print(table)
    print(verdict + slow_note)


if __name__ == "__main__":
    main()
