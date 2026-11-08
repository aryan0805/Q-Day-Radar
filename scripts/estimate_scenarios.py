"""Physical estimates for RSA-2048, ECC-256 and AES-128 under three scenarios.

Writes results/estimate/scenarios.json. Logical counts come from literature.yaml via
scenarios.yaml; nothing is typed here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantum.estimate import cases, common, physical  # noqa: E402


def _alt(h: dict) -> dict:
    """An earlier logical source (history): its ids and the counts it gives."""
    lit = common.literature()
    return {
        "source": h["source"],
        "literature_ids": [h["logical_qubits_id"], h["ccz_id"]],
        "logical_qubits": int(common.parse_power(lit[h["logical_qubits_id"]]["value"])),
        "toffoli_count": int(common.parse_power(lit[h["ccz_id"]]["value"])),
        "superseded_by": lit[h["ccz_id"]].get("superseded_by"),
    }


def _context(c: dict) -> dict:
    lit = common.literature()
    return {
        "source": c["source"],
        "literature_ids": [c["logical_qubits_id"], c["toffoli_per_run_id"]],
        "logical_qubits": int(common.parse_power(lit[c["logical_qubits_id"]]["value"])),
        "note": "context only: logical level, no hardware assumptions",
    }


def build() -> dict:
    spec = physical.load_spec()
    scen = {n: physical.scenario_params(n, spec) for n in spec["scenarios"]}
    out_scen = {
        n: {
            "qubit_params": {
                "instruction_set": "GateBased",
                "gate_error_rate": s["physical_error_rate"],
                "measurement_error_rate": s["physical_error_rate"],
            },
            "qec_scheme": {"name": s["qec_scheme"], "cycle_time_seconds": s["cycle_time_seconds"]},
            "error_budget": s["error_budget"],
            "physical_error_rate": s["physical_error_rate"],
            "source_ids": s["source_ids"],
        }
        for n, s in scen.items()
    }
    targets = {}
    for tname, t in spec["targets"].items():
        counts, reps = physical.target_logical_counts(tname, spec)
        entry = {
            "logical_source": {
                "label": t["label"],
                "source": t["source"],
                "literature_ids": [v for k, v in t.items() if k.endswith("_id")],
                "logical_counts": counts,
                "bound": t.get("bound"),
                "history": [_alt(h) for h in t.get("history", [])],
                "context": [_context(c) for c in t.get("context", [])],
                "repetitions": reps,
                "measurement_count_assumption": "set equal to CCZ count (not in the source)"
                if counts["cczCount"]
                else "none",
            },
            "by_scenario": {
                n: physical.physical_estimate(counts, s, reps) for n, s in scen.items()
            },
        }
        if tname == "aes128":
            entry["peel_last_sbox"] = bool(t["peel_last_sbox"])
            entry["label"] = t["label"]
        targets[tname] = entry
    return {"scenarios": out_scen, "targets": targets}


def main() -> int:
    res = build()
    cases.write_json(cases.OUT / "scenarios.json", res)
    for tname, t in res["targets"].items():
        for sname, v in t["by_scenario"].items():
            print(
                f"{tname:7s} {sname:12s} logical={v['logical_qubits']} "
                f"physical={v['physical_qubits']:.4g} "
                f"runtime_days={v['runtime_seconds'] / 86400:.4g} d={v['code_distance']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
