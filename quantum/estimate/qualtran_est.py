"""Qualtran costs: same-circuit (QASM -> cirq -> bloq) and bloq-level (ModExp, ECC)."""

from __future__ import annotations

import importlib.metadata as md
import warnings

from quantum.estimate import common

_IMPORT_SAFE = set(common.SHARED_BASIS) | {"cswap", "cz", "y", "id", "barrier"}


def _gate_names(qasm: str) -> set[str]:
    """Gate names used in a QASM2 string: the first token of EVERY ';'-separated statement.

    Custom gate/opaque definitions and conditionals are refused (their bodies would hide gates).
    """
    text = "\n".join(line.split("//")[0] for line in qasm.splitlines())
    decl = {"OPENQASM", "include", "qreg", "creg", "measure", "reset", "barrier"}
    refuse = {"gate", "opaque", "if"}
    names: set[str] = set()
    for stmt in text.split(";"):
        toks = stmt.replace("(", " ").split()
        if not toks:
            continue
        head = toks[0]
        if head in refuse:
            raise ValueError(f"QASM statement {head!r} hides gates from the importer check")
        if head not in decl:
            names.add(head)
    return names


def qualtran_counts_from_cost(cost, logical_qubits: int) -> dict:
    """Map a Qualtran GateCounts (QECGatesCost) to our counts.

    Rule (fixed 2026-11-08, before the numbers were used): toffoli = and_bloq + cswap + raw
    toffoli, so each And and each CSwap is one Toffoli-equivalent. And-dagger is Clifford +
    measurement and adds 0.
    t = t, rotations = rotation (as printed).
    """
    return {
        "logical_qubits": int(logical_qubits),
        "toffoli": int(cost.toffoli + cost.and_bloq + cost.cswap),
        "t": int(cost.t),
        "rotations": int(cost.rotation),
    }


def qualtran_counts_from_qasm(qasm: str) -> dict:
    """Cost a QASM2 circuit: QASM2 -> cirq -> composite bloq -> QECGatesCost."""
    from cirq.contrib.qasm_import import circuit_from_qasm
    from qualtran.cirq_interop import cirq_optree_to_cbloq
    from qualtran.resource_counting import QECGatesCost, get_cost_value

    bad = _gate_names(qasm) - _IMPORT_SAFE
    if bad:
        raise ValueError(
            f"gates {sorted(bad)} are mis-costed by Qualtran's QASM importer "
            "(e.g. cp adds a spurious And, rccx becomes a matrix gate); use common.estimation_form"
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        circuit = circuit_from_qasm(qasm)
        cbloq = cirq_optree_to_cbloq(circuit)
        cost = get_cost_value(cbloq, QECGatesCost())
    return qualtran_counts_from_cost(cost, len(circuit.all_qubits()))


def modexp_bloq(N: int, a: int):
    """ModExp built explicitly (never make_for_shor: its float log2 sizes the register one bit
    short for some N). n = N.bit_length(), exponent register 2n."""
    from qualtran.bloqs.cryptography.rsa import ModExp

    n = N.bit_length()
    return ModExp(base=a, mod=N, exp_bitsize=2 * n, x_bitsize=n)


def qualtran_modexp_counts(N: int, a: int) -> dict:
    from qualtran.resource_counting import QECGatesCost, get_cost_value

    bloq = modexp_bloq(N, a)
    return qualtran_counts_from_cost(
        get_cost_value(bloq, QECGatesCost()), bloq.signature.n_qubits()
    )


def qualtran_case(
    case: str,
    method: str,
    counts: dict,
    *,
    bloq: str,
    N: int | None,
    base_a: int | None,
    extra: dict | None = None,
) -> dict:
    """The per-case file dict (brief's schema)."""
    if method not in ("same_circuit", "bloq"):
        raise ValueError(f"method must be same_circuit or bloq, got {method!r}")
    eps = common.ROTATION_EPS
    return {
        "case": case,
        "method": method,
        "bloq": bloq,
        "N": N,
        "n_bits": N.bit_length() if N else None,
        "base_a": base_a,
        "logical_qubits": counts["logical_qubits"],
        "counts": {k: counts[k] for k in ("toffoli", "t", "rotations")},
        "toffoli_equiv": common.toffoli_equiv(
            toffoli=counts["toffoli"], t=counts["t"], rotations=counts["rotations"], eps=eps
        ),
        "rotation_eps": eps,
        "rotation_t_cost": common.rotation_t_cost(eps),
        "tool": {"name": "qualtran", "version": md.version("qualtran")},
        **(extra or {}),
    }
