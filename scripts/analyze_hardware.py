"""Analyse a finished hardware batch. No network, no QPU, never touches results/hardware.

    uv run python scripts/analyze_hardware.py results/hardware/<batch_id>

Writes ``results/analysis/phase2/<batch_id>/<index>.json`` for EVERY job in the raw files
(failed jobs get a file with null values; nothing is dropped). Raw results and M3-mitigated
results are kept in separate blocks. Predictions come from plan.json, which was written before
approval; nothing here is tuned after seeing hardware data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from quantum.run.hardware import measured_qubits, readout_matrices  # noqa: E402,F401
from quantum.run.noisy import ideal_distribution  # noqa: E402
from quantum.run.stats import hellinger_fidelity, normalized_score, wilson_interval  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "results" / "analysis" / "phase2"
DEFAULT_METRICS_DIR = ROOT / "results" / "metrics"


def matrices_from_batch(batch_dir: Path, plan: dict[str, Any]) -> dict[int, np.ndarray] | None:
    """Per-qubit readout matrices from the batch's own m3_cal_zeros / m3_cal_ones raw files."""
    raw: dict[str, dict[str, Any]] = {}
    for job in plan["jobs"]:
        path = batch_dir / "jobs" / f"{job['index']}.json"
        if job["config"] == "m3_cal" and path.exists():
            rec = json.loads(path.read_text())
            if rec.get("counts"):
                raw[job["name"]] = {"counts": rec["counts"], "qubits": job["measured_qubits"]}
    if {"m3_cal_zeros", "m3_cal_ones"} <= raw.keys():
        qubits = raw["m3_cal_zeros"]["qubits"]
        return readout_matrices(raw["m3_cal_zeros"]["counts"], raw["m3_cal_ones"]["counts"], qubits)
    return None


def _success(name: str, counts: dict[str, int] | dict[str, float]) -> float:
    from quantum.circuits.registry import SUCCESS_FN

    check = SUCCESS_FN[name]
    total = sum(counts.values())
    return sum(v for b, v in counts.items() if check(b)) / total


def _m3_block(
    name: str,
    counts: dict[str, int],
    isa_qubits: list[int],
    matrices: dict[int, np.ndarray],
    theory: float,
    chance: float,
) -> dict[str, Any] | None:
    """Readout-mitigated values (M3 applied to the measured register), kept apart from raw."""
    import mthree

    if not set(isa_qubits) <= set(matrices):
        return None
    order = sorted(set(isa_qubits))
    mit = mthree.M3Mitigation()
    mit.cals_from_matrices([matrices[q] for q in order])
    positions = [order.index(q) for q in isa_qubits]
    quasi = mit.apply_correction(counts, positions)
    probs = {b: float(max(p, 0.0)) for b, p in quasi.nearest_probability_distribution().items()}
    success = _success(name, probs)
    return {
        "method": "mthree (independent-qubit readout matrices from m3_cal jobs)",
        "success_probability": success,
        "normalized_score": normalized_score(success, theory, chance),
        "hellinger_vs_ideal": hellinger_fidelity(probs, ideal_distribution(name)),
    }


def analyze_batch(
    batch_dir: Path,
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    metrics_dir: Path = DEFAULT_METRICS_DIR,
    m3_matrices: dict[int, np.ndarray] | None = None,
) -> list[Path]:
    """Write one analysis file per planned job; return the paths."""
    plan_bytes = (batch_dir / "plan.json").read_bytes()
    approval_path = batch_dir / "approval.json"
    if approval_path.exists():  # predictions must be the ones that were approved
        approved = json.loads(approval_path.read_text())["plan_sha256"]
        if approved != hashlib.sha256(plan_bytes).hexdigest():
            raise ValueError("plan.json changed after approval: refusing to analyse")
    plan = json.loads(plan_bytes)
    if m3_matrices is None:
        m3_matrices = matrices_from_batch(batch_dir, plan)
    # validate every job BEFORE writing anything: each raw file must exist and be the circuit
    # that was planned (and predicted); nothing is dropped and nothing is compared to the wrong one
    for job in plan["jobs"]:
        raw_path = batch_dir / "jobs" / f"{job['index']}.json"
        if not raw_path.exists():
            raise FileNotFoundError(f"job {job['index']} has no raw file: not dropping it silently")
        if json.loads(raw_path.read_text())["isa_sha256"] != job["isa_sha256"]:
            raise ValueError(
                f"job {job['index']}: raw isa_sha256 differs from the planned circuit's"
            )
    target = out_dir / plan["batch_id"]
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for job in plan["jobs"]:
        raw_path = batch_dir / "jobs" / f"{job['index']}.json"
        if not raw_path.exists():
            raise FileNotFoundError(f"job {job['index']} has no raw file: not dropping it silently")
        raw = json.loads(raw_path.read_text())
        name = job["name"]
        out: dict[str, Any] = {
            "index": job["index"],
            "job_id": raw["job_id"],
            "name": name,
            "config": job["config"],
            "status": raw["status"],
            "shots": raw["shots"],
            "isa_sha256": raw["isa_sha256"],
            "success_probability": None,
            "wilson_95": None,
            "normalized_score": None,
            "hellinger_vs_ideal": None,
            "hellinger_vs_prediction": None,
        }
        counts = raw.get("counts")
        pred_counts = job["prediction"]["counts"]
        if counts:
            shots = sum(counts.values())
            if job["kind"] == "calibration":
                target_bit = "1" if name.endswith("ones") else "0"
                hits = sum(v for b, v in counts.items() if set(b) <= {target_bit})
                success = hits / shots
                out.update(
                    success_probability=success,
                    wilson_95=list(wilson_interval(hits, shots)),
                    hellinger_vs_prediction=hellinger_fidelity(counts, pred_counts),
                )
            else:
                metrics = json.loads((metrics_dir / f"{name}.json").read_text())
                theory, chance = metrics["theoretical_success"], metrics["chance_baseline"]
                success = _success(name, counts)
                hits = round(success * shots)
                out.update(
                    success_probability=success,
                    wilson_95=list(wilson_interval(hits, shots)),
                    normalized_score=normalized_score(success, theory, chance),
                    hellinger_vs_ideal=hellinger_fidelity(counts, ideal_distribution(name)),
                    hellinger_vs_prediction=hellinger_fidelity(counts, pred_counts),
                    theoretical_success=theory,
                    chance_baseline=chance,
                    predicted_success=job["prediction"]["success_probability"],
                )
                pred_n = sum(pred_counts.values())
                pred_lo, pred_hi = wilson_interval(
                    round(job["prediction"]["success_probability"] * pred_n), pred_n
                )
                out["prediction_wilson_95"] = [pred_lo, pred_hi]
                out["predicted_vs_chance"] = "at chance" if pred_lo <= chance else "signal"
                if m3_matrices and job["config"] in ("raw", "dd", "dd_twirl"):
                    block = _m3_block(
                        name, counts, job["measured_qubits"], m3_matrices, theory, chance
                    )
                    out["m3"] = block  # None when any measured qubit is uncalibrated
                    if block is None:
                        out["m3_reason"] = "measured qubits not calibrated"
        path = target / f"{job['index']}.json"
        path.write_text(json.dumps(out, indent=2) + "\n")
        written.append(path)
    return written


def _intervals_overlap(a: list[float], b: list[float]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


# Wording approved by lead (DECISION 2026-11-08) for the first hardware batch. The rule itself is
# unchanged. It is used only when the data resolves exactly the comparisons it describes; any
# other data gets the generic, computed sentence below instead, so the text can never contradict
# the numbers.
_APPROVED_STATEMENT = (
    "No mitigation gain resolved for the circuits with signal (shor15_textbook, grover k2, k3). "
    "At the chance floor, dd \u2212 raw is resolved for k4 (+0.023) and k5 (+0.008), and "
    "dd_twirl \u2212 raw for k4 (+0.013). With dd, k4 and k5 move from at or below chance (raw) "
    "to just above it (k4 dd Wilson lo 0.071 vs 0.0625; k5 dd lo 0.032 vs 0.0312). "
    "k4 dd_twirl stays at chance (lo 0.062). Exploratory: the rule was set after the data "
    "arrived, 10 comparisons, 2 repeats per config, no multiple-comparison correction. "
    "Raw repeats drifted beyond shot noise for k2 and shor15_textbook."
)
_APPROVED_RESOLVED = {
    "grover_present_k4: dd - raw",
    "grover_present_k4: dd_twirl - raw",
    "grover_present_k5: dd - raw",
}
_APPROVED_DRIFT = {"grover_present_k2/raw", "shor15_textbook/raw"}


def _mitigation_statement(entries: dict[str, Any], comparisons: dict[str, Any]) -> str:
    resolved = {k for k, c in comparisons.items() if c["gain_resolved"]}
    drifting = {k for k, e in entries.items() if e["drift_beyond_shot_noise"]}
    if resolved == _APPROVED_RESOLVED and drifting == _APPROVED_DRIFT and len(comparisons) == 10:
        return _APPROVED_STATEMENT
    gains = ", ".join(sorted(resolved)) if resolved else "none"
    return (
        f"Mitigation gains resolved by the rule (difference above both Wilson half-widths and "
        f"the larger repeat spread): {gains}. Exploratory: {len(comparisons)} comparisons, no "
        f"multiple-comparison correction. Repeats drifted beyond shot noise for: "
        f"{', '.join(sorted(drifting)) or 'none'}."
    )


def summarize_batch(analysis_dir: Path) -> dict[str, Any]:
    """Per-circuit, per-config summary with per-repeat results and a drift flag.

    Derived from the per-job analysis files only (never from jobs/). ``drift_beyond_shot_noise``
    is true when the repeats' Wilson intervals do not all overlap. A mitigation gain (dd or
    dd_twirl over raw) is resolved only if it exceeds both pooled Wilson half-widths AND the larger
    repeat spread of the two configs.
    """
    files = sorted(analysis_dir.glob("[0-9]*.json"), key=lambda p: int(p.stem))
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    batch_id = analysis_dir.name
    for f in files:
        rec = json.loads(f.read_text())
        if rec["success_probability"] is None:
            continue
        groups.setdefault((rec["name"], rec["config"]), []).append(rec)
    entries: dict[str, dict[str, Any]] = {}
    for (name, cfg), recs in groups.items():
        repeats = [
            {"index": r["index"], "success": r["success_probability"], "wilson_95": r["wilson_95"]}
            for r in recs
        ]
        shots = sum(r["shots"] for r in recs)
        hits = sum(round(r["success_probability"] * r["shots"]) for r in recs)
        lo, hi = wilson_interval(hits, shots)
        successes = [r["success_probability"] for r in recs]
        drift = any(
            not _intervals_overlap(a["wilson_95"], b["wilson_95"])
            for i, a in enumerate(repeats)
            for b in repeats[i + 1 :]
        )
        entry: dict[str, Any] = {
            "name": name,
            "config": cfg,
            "shots_pooled": shots,
            "success_probability": hits / shots,
            "wilson_95": [lo, hi],
            "repeats": repeats,
            "repeat_spread": max(successes) - min(successes),
            "drift_beyond_shot_noise": drift,
        }
        if "chance_baseline" in recs[0]:
            theory, chance = recs[0]["theoretical_success"], recs[0]["chance_baseline"]
            entry.update(
                theoretical_success=theory,
                chance_baseline=chance,
                predicted_success=recs[0]["predicted_success"],
                predicted_vs_chance=recs[0]["predicted_vs_chance"],
                normalized_score=normalized_score(hits / shots, theory, chance),
                hellinger_vs_ideal_mean=sum(r["hellinger_vs_ideal"] for r in recs) / len(recs),
                hellinger_vs_prediction_mean=sum(r["hellinger_vs_prediction"] for r in recs)
                / len(recs),
            )
            m3 = [r["m3"]["success_probability"] for r in recs if r.get("m3")]
            entry["m3_success_probability_mean"] = sum(m3) / len(m3) if m3 else None
        entries[f"{name}/{cfg}"] = entry

    comparisons: dict[str, Any] = {}
    for raw in entries.values():
        if raw["config"] != "raw" or "chance_baseline" not in raw:
            continue
        for cfg in ("dd", "dd_twirl"):
            other = entries.get(f"{raw['name']}/{cfg}")
            if other is None:
                continue
            diff = other["success_probability"] - raw["success_probability"]
            half = max(
                (raw["wilson_95"][1] - raw["wilson_95"][0]) / 2,
                (other["wilson_95"][1] - other["wilson_95"][0]) / 2,
            )
            spread = max(raw["repeat_spread"], other["repeat_spread"])
            comparisons[f"{raw['name']}: {cfg} - raw"] = {
                "difference": diff,
                "wilson_half_width_max": half,
                "repeat_spread_max": spread,
                "gain_resolved": diff > half and diff > spread,
                "raw_wilson_lo_above_chance": raw["wilson_95"][0] > raw["chance_baseline"],
                "mitigated_wilson_lo_above_chance": other["wilson_95"][0] > raw["chance_baseline"],
            }
    statement = _mitigation_statement(entries, comparisons)
    return {
        "batch_id": batch_id,
        "rule": "a gain needs difference > both pooled Wilson half-widths and > the larger "
        "repeat spread of the two configs",
        "mitigation_statement": statement,
        "entries": entries,
        "comparisons": comparisons,
        "comparisons_exploratory": True,
        "n_comparisons": len(comparisons),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("batch_dir", type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args(argv)
    paths = analyze_batch(args.batch_dir, args.out)
    if paths:
        summary = summarize_batch(paths[0].parent)
        summary_path = args.out / f"summary-{summary['batch_id']}.json"
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"summary: {summary_path}\n{summary['mitigation_statement']}")
    print(f"wrote {len(paths)} analysis files to {paths[0].parent if paths else args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
