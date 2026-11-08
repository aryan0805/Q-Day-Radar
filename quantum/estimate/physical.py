"""Physical resource estimate from logical counts, via qdk.estimator.LogicalCounts.

Surface code (QDK's built-in scheme, its default threshold and prefactor) with a literature
physical error rate and surface-code cycle time. Gate times are 1 ns placeholders; the logical
cycle time is overridden to `cycle_time_ns * codeDistance`, so the cycle time is the only
timing input. Measurement count is set to the number of CCZ states (assumption, in the output).
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path

import yaml

from quantum.estimate import common
from quantum.estimate.common import parse_power

MAX_CODE_DISTANCE = 500  # QDK default is 50; AES needs a tiny per-block error budget
SCENARIOS_PATH = Path(__file__).with_name("scenarios.yaml")


def load_spec() -> dict:
    return yaml.safe_load(SCENARIOS_PATH.read_text())


def scenario_params(name: str, spec: dict | None = None) -> dict:
    """Resolve a scenario's literature ids to numbers."""
    spec = spec or load_spec()
    sc = spec["scenarios"][name]
    lit = common.literature()
    return {
        "physical_error_rate": float(lit[sc["error_rate_id"]]["value"]),
        "cycle_time_seconds": float(lit[sc["cycle_time_id"]]["value"]),
        "qec_scheme": sc["qec_scheme"],
        "error_budget": float(spec["error_budget"]),
        "source_ids": [sc["error_rate_id"], sc["cycle_time_id"]],
    }


def physical_estimate(logical_counts: dict, scenario: dict, repetitions: int = 1) -> dict:
    """{logical_qubits, physical_qubits, runtime_seconds, code_distance}.

    `logical_counts` uses QDK keys (numQubits, tCount, rotationCount, cczCount, ...);
    `scenario` is a scenario_params() dict. `repetitions` > 1 means `logical_counts` is ONE of
    `repetitions` identical sequential blocks (QDK counts are u64, too small for a full AES
    Grover search): the error budget is divided by `repetitions`, the code distance follows from
    that, and runtime is multiplied by `repetitions`. Qubits are unchanged.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from qdk.estimator import (
            EstimatorParams,
            EstimatorQecScheme,
            EstimatorQubitParams,
            LogicalCounts,
        )

        err = scenario["physical_error_rate"]
        p = EstimatorParams()
        p.qubit_params = EstimatorQubitParams(
            instruction_set="GateBased",
            one_qubit_gate_time="1 ns",
            two_qubit_gate_time="1 ns",
            one_qubit_measurement_time="1 ns",
            t_gate_time="1 ns",
            one_qubit_gate_error_rate=err,
            two_qubit_gate_error_rate=err,
            one_qubit_measurement_error_rate=err,
            t_gate_error_rate=err,
        )
        cycle_ns = scenario["cycle_time_seconds"] * 1e9
        p.qec_scheme = EstimatorQecScheme(
            name=scenario["qec_scheme"],
            logical_cycle_time=f"{cycle_ns:.12g} * codeDistance",
            max_code_distance=MAX_CODE_DISTANCE,
        )
        p.error_budget = scenario["error_budget"] / repetitions
        res = LogicalCounts(logical_counts).estimate(p)
    pc = res["physicalCounts"]
    return {
        "logical_qubits": int(pc["breakdown"]["algorithmicLogicalQubits"]),
        "physical_qubits": int(pc["physicalQubits"]),
        "runtime_seconds": float(pc["runtime"]) / 1e9 * repetitions,
        "repetitions": repetitions,
        "code_distance": int(res["logicalQubit"]["codeDistance"]),
    }


def target_logical_counts(target: str, spec: dict | None = None) -> tuple[dict, int]:
    """(QDK-style counts of ONE block, number of sequential blocks) from literature ids."""
    spec = spec or load_spec()
    t = spec["targets"][target]
    lit = common.literature()
    counts = {
        "numQubits": int(lit[t["logical_qubits_id"]]["value"]),
        "tCount": 0,
        "rotationCount": 0,
        "rotationDepth": 0,
        "cczCount": 0,
        "ccixCount": 0,
        "measurementCount": 0,
    }
    reps = 1
    if "grover_key_bits" in t:
        reps = math.floor(math.pi / 4 * 2 ** (t["grover_key_bits"] // 2))
    if "ccz_id" in t:
        counts["cczCount"] = int(parse_power(lit[t["ccz_id"]]["value"]))
        counts["measurementCount"] = counts["cczCount"]
    if "t_id" in t:
        counts["tCount"] = round(parse_power(lit[t["t_id"]]["value"]) / reps)
    return counts, reps


def physical_estimate_v2(logical_qubits: float, physical_error_rate: float) -> dict:
    """Physical model v2: Gidney 2025's own layout components (pre-registered, not tuned).

    physical = L * (c * cold + (1 - c) * hot) + compute_patches * hot, with hot = 2 (d + 1)^2
    physical qubits per hot patch, cold = yoked-storage qubits per logical qubit, and
    c = m / max_logical the cold fraction of Gidney's own n = 2048 run. Runtime is NOT modelled
    here (the Phase 3 model's runtime stays in use). The distance is the paper's at its own
    physical error rate; other rates use the labelled suppression-law extension.
    """
    spec = load_spec()["physical_v2"]
    lit = common.literature()
    d_ref = int(lit[spec["hot_distance_id"]]["value"])
    p_ref = float(lit[spec["reference_error_rate_id"]]["value"])
    cold = float(lit[spec["cold_per_logical_id"]]["value"])
    c = float(lit[spec["cold_logical_id"]]["value"]) / float(lit[spec["max_logical_id"]]["value"])
    patches = float(lit[spec["compute_patches_id"]]["value"])
    p_th = float(spec["p_threshold"])
    if _close(physical_error_rate, p_ref):
        d = d_ref
    else:
        exact = (d_ref + 1) * math.log(p_ref / p_th) / math.log(physical_error_rate / p_th) - 1
        d = math.ceil(exact)
        d += 1 - d % 2  # next odd distance (stays if already odd)
    hot = 2 * (d + 1) ** 2
    physical = logical_qubits * (c * cold + (1 - c) * hot) + patches * hot
    return {
        "physical_qubits": physical,
        "code_distance": d,
        "cold_fraction": c,
        "hot_patch_qubits": hot,
        "compute_region_qubits": patches * hot,
        "distance_extension": not _close(physical_error_rate, p_ref),
    }


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(abs(a), abs(b))
