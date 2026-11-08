"""QDK (qsharp) logical counts through ResourceEstimatorBackend."""

from __future__ import annotations

import importlib.metadata as md
import warnings

from qiskit import QuantumCircuit

from quantum.estimate import common

KINDS = ("generic", "compiled")


def qdk_logical_counts(qc: QuantumCircuit) -> dict:
    """Raw logical counts for `qc` as QDK reports them (no transpilation by QDK).

    Do not pass dynamic circuits (if_else): QDK follows one branch from a made-up outcome
    sequence. Use common.estimation_form first. A circuit with no T, rotation, CCZ or
    measurement raises (QDK: AlgorithmHasNoResources); that is a BaseException in QDK.
    """
    if any(i.operation.name == "if_else" for i in qc.data):
        raise ValueError("dynamic circuit: build common.estimation_form(qc) first")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from qsharp.interop.qiskit import ResourceEstimatorBackend

        try:
            estimator = ResourceEstimatorBackend(skip_transpilation=True)  # local, no QPU
            res = estimator.run(qc).result()
        except BaseException as exc:  # noqa: BLE001 - QDK raises a BaseException subclass
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            raise RuntimeError(f"QDK could not cost {qc.name!r}: {exc!r}") from exc
    lc = res["logicalCounts"] if "logicalCounts" in res else res
    return {
        "num_qubits": int(lc["numQubits"]),
        "t_count": int(lc["tCount"]),
        "rotation_count": int(lc["rotationCount"]),
        "ccz_count": int(lc["cczCount"]),
        "ccix_count": int(lc["ccixCount"]),
        "measurement_count": int(lc["measurementCount"]),
    }


def qdk_case(
    case: str,
    qc: QuantumCircuit,
    *,
    kind: str,
    N: int | None,
    base_a: int | None,
    extra: dict | None = None,
) -> dict:
    """The per-case file dict (brief's schema). `qc` is costed as given."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    counts = qdk_logical_counts(qc)
    eps = common.ROTATION_EPS
    return {
        "case": case,
        "kind": kind,
        "N": N,
        "n_bits": N.bit_length() if N else None,
        "base_a": base_a,
        "logical_counts": counts,
        "toffoli_equiv": common.toffoli_equiv(
            ccz=counts["ccz_count"],
            ccix=counts["ccix_count"],
            t=counts["t_count"],
            rotations=counts["rotation_count"],
            eps=eps,
        ),
        "rotation_eps": eps,
        "rotation_t_cost": common.rotation_t_cost(eps),
        "tool": {"name": "qsharp", "version": md.version("qsharp")},
        **(extra or {}),
    }
