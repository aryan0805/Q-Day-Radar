"""The reference gate counter, and the two ways QDK's gate fusion moves a count.

Lead (2026-11-08): QDK fuses single-qubit gates. Up: a T-only run between Cliffords becomes one
rotation. Down: a T next to a non-pi/4 rz is absorbed into that rz. Neither direction is
assumed; each is measured against this module's own parser and pinned so a change is noticed.
"""

from __future__ import annotations

from math import pi

import pytest
from qiskit import QuantumCircuit, qasm2

from tests.phase3 import reference as ref


def test_estimate_reference_parser_counts_a_hand_written_circuit():
    qasm = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[3]; creg c[3];
h q[0]; t q[0]; tdg q[1]; rz(pi/4) q[2]; rz(-3*pi/4) q[2]; rz(pi/2) q[0];
rz(0.3) q[1]; rz(pi/8) q[0];
ccx q[0],q[1],q[2]; cswap q[0],q[1],q[2];
cx q[0],q[1]; s q[2];  // a comment with t q[0];
measure q[0] -> c[0];
"""
    got = ref.qasm_counts(qasm)
    # T: t, tdg, rz(pi/4), rz(-3pi/4) = 4; rotations: rz(0.3), rz(pi/8) = 2; rz(pi/2) is Clifford
    assert (got["t"], got["rotations"], got["ccx"], got["measurements"]) == (4, 2, 2, 1)
    assert got["clifford"] == 4  # h, rz(pi/2), cx, s


def test_estimate_reference_parser_refuses_a_gate_outside_the_common_basis():
    for gate in ("cp(0.3) q[0],q[1];", "crz(0.3) q[0],q[1];", "c3x q[0],q[1],q[2],q[3];"):
        with pytest.raises(ValueError, match="common basis"):
            ref.qasm_counts(f'OPENQASM 2.0;include "qelib1.inc";qreg q[4];{gate}')


def test_estimate_reference_angle_evaluator_is_a_whitelist():
    assert ref.eval_angle("-pi/4") == pytest.approx(-pi / 4)
    assert ref.eval_angle("3*pi/8") == pytest.approx(3 * pi / 8)
    with pytest.raises(ValueError):
        ref.eval_angle("__import__('os')")


def test_estimate_reference_counts_agree_with_qiskit_on_a_known_circuit():
    """Cross-check the parser against a circuit whose gates we placed ourselves."""
    qc = QuantumCircuit(2)
    for _ in range(3):
        qc.t(0)
        qc.h(0)
    qc.rz(0.3, 1)
    qc.rz(0.4, 1)
    got = ref.qasm_counts(qasm2.dumps(qc))
    assert (got["t"], got["rotations"], got["ccx"]) == (3, 2, 0)


def _qdk(qc):
    from quantum.estimate import qdk

    return qdk.qdk_logical_counts(qc)


def _qt(qc):
    from quantum.estimate import qualtran_est

    return qualtran_est.qualtran_counts_from_qasm(qasm2.dumps(qc))


def _qdk_default_backend(qc):
    """QDK's own backend, default Qiskit transpilation, called directly (not our wrapper)."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from qsharp.interop.qiskit import ResourceEstimatorBackend

        lc = ResourceEstimatorBackend().run(qc).result()["logicalCounts"]
    return lc["tCount"], lc["rotationCount"]


def _t_run():
    qc = QuantumCircuit(1)
    for _ in range(3):
        qc.t(0)
        qc.h(0)
    return qc


def _rz_t(order):
    qc = QuantumCircuit(1)
    for g in order:
        qc.t(0) if g == "t" else qc.rz(0.3, 0)
    return qc


def test_estimate_qdk_default_transpilation_goes_up_a_t_run_becomes_rotations():
    """Why our wrapper skips QDK's transpilation: T H T H T H comes back as 3 rotations."""
    assert _qdk_default_backend(_t_run()) == (0, 3)


@pytest.mark.parametrize("order", ["rt", "tr"])
def test_estimate_qdk_default_transpilation_goes_down_a_t_next_to_a_generic_rz_vanishes(order):
    assert _qdk_default_backend(_rz_t(order)) == (0, 1)


def test_estimate_qdk_default_transpilation_does_not_fuse_across_a_hadamard():
    qc = QuantumCircuit(1)
    qc.rz(0.3, 0)
    qc.h(0)
    qc.t(0)
    assert _qdk_default_backend(qc) == (1, 1)


@pytest.mark.parametrize(
    ("name", "circuit", "want"),
    [
        ("t_run (up case)", _t_run, (3, 0)),
        ("rz then t (down case)", lambda: _rz_t("rt"), (1, 1)),
        ("t then rz (down case)", lambda: _rz_t("tr"), (1, 1)),
    ],
)
def test_estimate_our_wrappers_match_the_reference_on_both_fusion_cases(name, circuit, want):
    """Reference = this directory's own QASM parser. QDK (skip_transpilation) and Qualtran agree."""
    qc = circuit()
    r = ref.qasm_counts(qasm2.dumps(qc))
    assert (r["t"], r["rotations"]) == want, name
    q = _qdk(qc)
    assert (q["t_count"], q["rotation_count"]) == want, (name, "QDK wrapper", q)
    qt = _qt(qc)
    assert (qt["t"], qt["rotations"]) == want, (name, "Qualtran wrapper", qt)


def test_estimate_our_wrappers_match_the_reference_across_a_hadamard():
    qc = QuantumCircuit(1)
    qc.rz(0.3, 0)
    qc.h(0)
    qc.t(0)
    r = ref.qasm_counts(qasm2.dumps(qc))
    q, qt = _qdk(qc), _qt(qc)
    assert (
        (r["t"], r["rotations"])
        == (q["t_count"], q["rotation_count"])
        == (qt["t"], qt["rotations"])
    )
