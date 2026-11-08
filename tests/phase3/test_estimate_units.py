"""Unit tests for quantum/estimate/*: hand-countable circuits and known-answer fits.

Every expected number is derived by hand or by tests/phase3/reference.py, never read back from
the code under test. The two tools are asked about circuits whose gate counts can be done on
paper, so a wrong count fails here instead of surviving as a plausible-looking estimate.
"""

from __future__ import annotations

import hashlib
import math
from math import pi

import pytest
from qiskit import QuantumCircuit, qasm2

from tests.phase3 import reference as ref


# ---- circuits you can count on paper ----------------------------------------------------
def qft(n: int) -> QuantumCircuit:
    """n-qubit QFT without swaps: n H gates and n(n-1)/2 controlled phases."""
    qc = QuantumCircuit(n)
    for j in range(n - 1, -1, -1):
        qc.h(j)
        for k in range(j - 1, -1, -1):
            qc.cp(pi / 2 ** (j - k), k, j)
    return qc


def t_chain(m: int) -> QuantumCircuit:
    """m T gates separated by H so no optimizer may merge them: T-count is m by hand."""
    qc = QuantumCircuit(1)
    for _ in range(m):
        qc.t(0)
        qc.h(0)
    return qc


def ccx_circuit(m: int) -> QuantumCircuit:
    qc = QuantumCircuit(m + 2)
    for i in range(m):
        qc.ccx(i, i + 1, i + 2)
    return qc


def cswap_circuit() -> QuantumCircuit:
    qc = QuantumCircuit(3)
    qc.cswap(0, 1, 2)
    return qc


# ======================================================================================
# common.py
# ======================================================================================
def test_estimate_common_toffoli_equiv_hand_values():
    from quantum.estimate import common

    eps = common.ROTATION_EPS
    k = common.rotation_t_cost(eps)
    f = common.toffoli_equiv
    assert f(eps=eps) == 0
    assert f(toffoli=1, eps=eps) == pytest.approx(1)
    assert f(ccz=1, eps=eps) == pytest.approx(1)
    assert f(ccix=1, eps=eps) == pytest.approx(1)
    assert f(t=4, eps=eps) == pytest.approx(1)
    assert f(t=1, eps=eps) == pytest.approx(0.25)
    assert f(rotations=1, eps=eps) == pytest.approx(k / 4)
    mix = f(toffoli=3, ccz=2, ccix=1, t=8, rotations=5, eps=eps)
    assert mix == pytest.approx(3 + 2 + 1 + 8 / 4 + 5 * k / 4)
    # additive: cost of a sum of parts is the sum of the costs
    assert f(toffoli=3, t=8, eps=eps) == pytest.approx(f(toffoli=3, eps=eps) + f(t=8, eps=eps))


def test_estimate_common_rotation_t_cost_is_log_linear_in_one_over_eps():
    from quantum.estimate import common

    c = common.rotation_t_cost
    assert 0 < common.ROTATION_EPS < 1
    costs = [c(10.0**-d) for d in (3, 6, 9, 12, 15)]
    assert costs == sorted(costs) and len(set(costs)) == 5, "smaller eps must cost more T gates"
    steps = [b - a for a, b in zip(costs, costs[1:], strict=False)]
    assert max(steps) - min(steps) < 0.02 * max(steps), f"not linear in log(1/eps): {steps}"


def test_estimate_common_circuit_sha256_known_vectors():
    from quantum.estimate import common

    assert common.circuit_sha256("") == hashlib.sha256(b"").hexdigest()
    assert common.circuit_sha256("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert common.circuit_sha256("abc") != common.circuit_sha256("abd")


def test_estimate_common_estimation_form_is_non_dynamic_and_keeps_every_branch():
    """Caveat B: no if_else survives, the classically controlled rotation counts as executed."""
    from quantum.estimate import common

    qc = QuantumCircuit(2, 1)
    qc.h(0)
    qc.measure(0, 0)
    with qc.if_test((qc.clbits[0], 1)):
        qc.rz(0.3, 1)
    qc.rz(0.7, 1)
    before = [i.operation.name for i in qc.data]
    form = common.estimation_form(qc)
    names = [i.operation.name for i in form.data]
    assert "if_else" not in names, names
    assert names.count("rz") >= 2, f"controlled rz dropped: {names}"
    assert [i.operation.name for i in qc.data] == before, "estimation_form mutated its input"
    assert form.metadata and "estimation" in str(form.metadata).lower(), "form must be labelled"


def test_estimate_common_estimation_form_leaves_a_plain_circuit_alone():
    from quantum.estimate import common

    qc = ccx_circuit(2)
    qc.h(0)
    form = common.estimation_form(qc)
    names = lambda c: sorted(i.operation.name for i in c.data)  # noqa: E731
    assert names(form) == names(qc)


# ======================================================================================
# qdk.py
# ======================================================================================
def _equiv_qdk(counts: dict) -> float:
    from quantum.estimate import common

    return common.toffoli_equiv(
        ccz=counts["ccz_count"],
        ccix=counts["ccix_count"],
        t=counts["t_count"],
        rotations=counts["rotation_count"],
        eps=common.ROTATION_EPS,
    )


def test_estimate_qdk_one_toffoli_costs_exactly_one():
    from quantum.estimate import qdk

    c = qdk.qdk_logical_counts(ccx_circuit(1))
    assert c["num_qubits"] == 3
    assert c["ccz_count"] + c["ccix_count"] == 1
    assert (c["t_count"], c["rotation_count"], c["measurement_count"]) == (0, 0, 0)
    assert _equiv_qdk(c) == pytest.approx(1)


@pytest.mark.parametrize("m", [2, 3, 5])
def test_estimate_qdk_m_toffolis_cost_m(m):
    from quantum.estimate import qdk

    c = qdk.qdk_logical_counts(ccx_circuit(m))
    assert c["ccz_count"] + c["ccix_count"] == m and c["t_count"] == 0
    assert c["num_qubits"] == m + 2


def test_estimate_qdk_one_cswap_costs_one_toffoli():
    from quantum.estimate import qdk

    assert _equiv_qdk(qdk.qdk_logical_counts(cswap_circuit())) == pytest.approx(1)


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 8])
def test_estimate_qdk_qft_counts_by_hand(n):
    """cp(pi/2) = controlled-S: 3 T gates. cp(pi/2^k), k >= 2: 3 rotations. n(n-1)/2 cps total."""
    from quantum.estimate import qdk

    c = qdk.qdk_logical_counts(qft(n))
    assert c["num_qubits"] == n
    assert c["t_count"] == 3 * (n - 1), c
    assert c["rotation_count"] == 3 * (n - 1) * (n - 2) // 2, c
    assert c["ccz_count"] == c["ccix_count"] == 0
    assert ref.qft_rotations(n) == (n - 1) + (n - 1) * (n - 2) // 2  # the n(n-1)/2 split


def test_estimate_qdk_single_generic_controlled_phase_is_three_rotations():
    from quantum.estimate import qdk

    qc = QuantumCircuit(2)
    qc.cp(0.3, 0, 1)
    c = qdk.qdk_logical_counts(qc)
    assert (c["rotation_count"], c["t_count"]) == (3, 0), c


def test_estimate_qdk_clifford_circuit_with_measurements_counts_only_measurements():
    from quantum.estimate import qdk

    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    c = qdk.qdk_logical_counts(qc)
    assert c["measurement_count"] == 2
    assert _equiv_qdk(c) == 0


def test_estimate_qdk_hand_t_count_is_priced_as_t_gates_not_rotations():
    """T H T H T H has a hand T-count of 3, so toffoli_equiv is 3/4.

    Our wrapper calls QDK with skip_transpilation=True, so nothing fuses the T gates (the
    default QDK backend does; see test_estimate_reference_counts.py for that pinned contrast).
    """
    from quantum.estimate import qdk

    c = qdk.qdk_logical_counts(t_chain(3))
    assert (c["t_count"], c["rotation_count"]) == (3, 0), c
    assert _equiv_qdk(c) == pytest.approx(0.75)


def test_estimate_qdk_case_dict_has_the_schema_and_a_consistent_toffoli_equiv():
    from quantum.estimate import common, qdk

    case = qdk.qdk_case("hand_qft4", qft(4), kind="generic", N=None, base_a=None)
    assert {
        "case",
        "kind",
        "logical_counts",
        "toffoli_equiv",
        "rotation_eps",
        "rotation_t_cost",
        "tool",
    } <= set(case)
    assert case["rotation_eps"] == common.ROTATION_EPS
    assert case["toffoli_equiv"] == pytest.approx(ref.toffoli_equiv_qdk(case))
    assert case["kind"] == "generic" and case["tool"]["name"] == "qsharp"
    with pytest.raises((ValueError, AssertionError)):
        qdk.qdk_case("bad", qft(2), kind="whatever", N=None, base_a=None)


# ======================================================================================
# qualtran_est.py
# ======================================================================================
def _equiv_qt(counts: dict) -> float:
    from quantum.estimate import common

    return common.toffoli_equiv(
        toffoli=counts["toffoli"],
        t=counts["t"],
        rotations=counts["rotations"],
        eps=common.ROTATION_EPS,
    )


def test_estimate_qualtran_one_toffoli_costs_exactly_one():
    from quantum.estimate import qualtran_est

    c = qualtran_est.qualtran_counts_from_qasm(qasm2.dumps(ccx_circuit(1)))
    assert c["logical_qubits"] == 3
    assert (c["toffoli"], c["t"], c["rotations"]) == (1, 0, 0)


def test_estimate_qualtran_one_cswap_costs_one_toffoli():
    from quantum.estimate import qualtran_est

    c = qualtran_est.qualtran_counts_from_qasm(qasm2.dumps(cswap_circuit()))
    assert _equiv_qt(c) == pytest.approx(1) and c["rotations"] == 0


@pytest.mark.parametrize("m", [1, 3, 5])
def test_estimate_qualtran_hand_t_count(m):
    from quantum.estimate import qualtran_est

    c = qualtran_est.qualtran_counts_from_qasm(qasm2.dumps(t_chain(m)))
    assert c["t"] == m and c["rotations"] == 0 and c["toffoli"] == 0, c
    assert _equiv_qt(c) == pytest.approx(m / 4)


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6])
def test_estimate_qualtran_qft_in_the_common_basis_matches_the_hand_count(n):
    """n(n-1)/2 cps, each 3 non-Clifford rz: (n-1) of them controlled-S (3 T), the rest 3 rotations.
    A QFT has no Toffoli, so a spurious And would show as toffoli > 0."""
    from quantum.estimate import common, qualtran_est

    qasm = qasm2.dumps(common.estimation_form(qft(n)))
    c = qualtran_est.qualtran_counts_from_qasm(qasm)
    assert c["logical_qubits"] == n
    assert c["toffoli"] == 0, f"n={n}: toffoli {c['toffoli']} in a circuit with none"
    assert c["t"] == 3 * (n - 1), c
    assert c["rotations"] == 3 * (n - 1) * (n - 2) // 2, c
    assert ref.qft_rotations(n) * 3 == c["t"] + c["rotations"]  # 3 rz per cp, n(n-1)/2 cps
    want = ref.qasm_counts(qasm)  # the reference parser agrees with the hand formula too
    assert (want["t"], want["rotations"]) == (c["t"], c["rotations"])


HEADER = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\n'


@pytest.mark.parametrize("gate", ["cp(0.3) q[0],q[1];", "cp(pi/8) q[0],q[1];"])
def test_estimate_qualtran_refuses_gates_its_qasm_importer_mis_costs(gate):
    """Raw cp makes the importer add a spurious And, so a wrong number must not be returned."""
    from quantum.estimate import qualtran_est

    with pytest.raises(ValueError, match="common.estimation_form"):
        qualtran_est.qualtran_counts_from_qasm(HEADER + gate + "\n")


@pytest.mark.parametrize(
    "qasm",
    [
        'OPENQASM 2.0;include "qelib1.inc";qreg q[2];cp(0.3) q[0],q[1];',
        HEADER + "h q[0]; cp(0.3) q[0],q[1];\n",
        HEADER + "h q[0];\tcp(0.3) q[0],q[1];\n",
    ],
    ids=["whole file on one line", "second statement on a line", "after a tab"],
)
def test_estimate_qualtran_guard_checks_every_statement_not_just_the_first_on_a_line(qasm):
    """The guard must not depend on how the QASM is formatted (it splits on ';', not newlines)."""
    from quantum.estimate import qualtran_est

    with pytest.raises(ValueError, match="common.estimation_form"):
        qualtran_est.qualtran_counts_from_qasm(qasm)


def test_estimate_both_tools_agree_on_a_qft_once_given_the_same_estimation_form():
    """Same circuit, same gate set: the tools must land within 1.5x (reviewer threshold)."""
    from quantum.estimate import common, qdk, qualtran_est

    for n in (4, 6, 8):
        form = common.estimation_form(qft(n))
        a = _equiv_qdk(qdk.qdk_logical_counts(form))
        b = _equiv_qt(qualtran_est.qualtran_counts_from_qasm(qasm2.dumps(form)))
        assert ref.ratio(a, b) < 1.5, f"qft{n}: QDK {a:.4g} vs Qualtran {b:.4g}"


def _raw_modexp(n_mod: int, base: int):
    from qualtran.bloqs.cryptography.rsa import ModExp
    from qualtran.resource_counting import QECGatesCost, get_cost_value

    n = n_mod.bit_length()
    bloq = ModExp(base=base, mod=n_mod, exp_bitsize=2 * n, x_bitsize=n)
    return bloq, get_cost_value(bloq, QECGatesCost())


@pytest.mark.parametrize(("n_mod", "base"), [(15, 7), (21, 2), (35, 2)])
def test_estimate_qualtran_modexp_counts_match_an_independent_construction(n_mod, base):
    from quantum.estimate import qualtran_est

    bloq, raw = _raw_modexp(n_mod, base)
    got = qualtran_est.qualtran_modexp_counts(n_mod, base)
    assert got["logical_qubits"] == bloq.signature.n_qubits() == 3 * n_mod.bit_length()
    # each And and each CSwap is one Toffoli-equivalent (reviewer's proposed rule)
    assert got["toffoli"] == raw.toffoli + raw.and_bloq + raw.cswap, (got, raw)
    assert got["t"] == raw.t and got["rotations"] == raw.rotation


def test_estimate_qualtran_modexp_at_61_bits_uses_a_register_that_holds_N():
    """Caveat C at a size where make_for_shor is one bit short and cannot even be costed."""
    from quantum.estimate import qualtran_est

    n_mod = 2**60 + 33
    got = qualtran_est.qualtran_modexp_counts(n_mod, 2)
    assert got["logical_qubits"] == 3 * n_mod.bit_length() == 183
    bloq, _ = _raw_modexp(n_mod, 2)
    from tests.phase3.test_estimate_files import assert_modexp_sizes

    assert_modexp_sizes(bloq, n_mod)


def test_estimate_qualtran_modexp_cost_grows_with_the_modulus():
    from quantum.estimate import qualtran_est

    small = _equiv_qt(qualtran_est.qualtran_modexp_counts(15, 7))
    big = _equiv_qt(qualtran_est.qualtran_modexp_counts(2**20 + 7, 2))
    assert big > 100 * small


def test_estimate_qualtran_case_dict_has_the_schema_and_a_consistent_toffoli_equiv():
    from quantum.estimate import common, qualtran_est

    counts = qualtran_est.qualtran_modexp_counts(15, 7)
    case = qualtran_est.qualtran_case(
        "modexp_N15_a7", "bloq", counts, bloq="ModExp", N=15, base_a=7
    )
    assert case["rotation_eps"] == common.ROTATION_EPS
    assert case["toffoli_equiv"] == pytest.approx(ref.toffoli_equiv_qualtran(case))
    assert case["method"] == "bloq" and case["tool"]["name"] == "qualtran"
    assert case["n_bits"] == (15).bit_length()


# ======================================================================================
# scaling.py
# ======================================================================================
XS = [4, 6, 8, 12, 16, 24]


def test_estimate_scaling_power_law_recovers_a_known_exponent_exactly():
    from quantum.estimate import scaling

    f = scaling.fit_power_law(XS, [7 * x**2.5 for x in XS])
    assert f["exponent"] == pytest.approx(2.5, abs=1e-9)
    assert f["params"]["exponent"] == pytest.approx(2.5, abs=1e-9)
    assert f["params"]["c"] == pytest.approx(7.0, rel=1e-9)
    assert f["r2"] == pytest.approx(1.0, abs=1e-12)
    assert all(abs(r["rel"]) < 1e-9 for r in f["residuals"])
    assert [r["x"] for r in f["residuals"]] == XS


def test_estimate_scaling_power_law_on_noisy_data_matches_the_reference_fit():
    from quantum.estimate import scaling

    noise = [1.05, 0.97, 1.02, 0.94, 1.04, 1.01]
    ys = [3 * x**2 * m for x, m in zip(XS, noise, strict=True)]
    f = scaling.fit_power_law(XS, ys)
    k, c = ref.power_law(XS, ys)
    assert f["exponent"] == pytest.approx(k, rel=1e-9) and f["params"]["c"] == pytest.approx(c)
    for r, x, y in zip(f["residuals"], XS, ys, strict=True):
        assert r["rel"] == pytest.approx((y - c * x**k) / y, abs=1e-9)  # signed
    # r2 is that of the log-log regression
    ly = [math.log(y) for y in ys]
    pred = [math.log(c * x**k) for x in XS]
    mean = sum(ly) / len(ly)
    r2 = 1 - sum((a - b) ** 2 for a, b in zip(ly, pred, strict=True)) / sum(
        (a - mean) ** 2 for a in ly
    )
    assert f["r2"] == pytest.approx(r2, abs=1e-9) and 0 < f["r2"] < 1


def test_estimate_scaling_residual_sign_is_value_minus_fit():
    from quantum.estimate import scaling

    ys = [5 * x**2 for x in XS]
    ys[2] *= 1.5  # one point far ABOVE the curve
    f = scaling.fit_power_law(XS, ys)
    by_x = {r["x"]: r["rel"] for r in f["residuals"]}
    assert by_x[XS[2]] > 0.1, by_x


def test_estimate_scaling_linear_fit_recovers_known_slope_and_intercept():
    from quantum.estimate import scaling

    f = scaling.fit_linear(XS, [5 * x + 7 for x in XS])
    assert f["params"]["slope"] == pytest.approx(5.0) and f["params"]["intercept"] == pytest.approx(
        7.0
    )
    assert f["r2"] == pytest.approx(1.0, abs=1e-12)
    ys = [5 * x + 7 + d for x, d in zip(XS, [2, -3, 1, 4, -2, 1], strict=True)]
    g = scaling.fit_linear(XS, ys)
    a, b = ref.linear(XS, ys)
    assert g["params"]["slope"] == pytest.approx(a) and g["params"]["intercept"] == pytest.approx(b)
    for r, x, y in zip(g["residuals"], XS, ys, strict=True):
        assert r["rel"] == pytest.approx((y - (a * x + b)) / y, abs=1e-9)


def test_estimate_scaling_holdout_fits_on_the_smaller_sizes_and_scores_the_largest():
    from quantum.estimate import scaling

    exact = scaling.holdout(XS, [7 * x**2.5 for x in XS], scaling.fit_power_law)
    assert exact["n_bits"] == max(XS)
    assert exact["predicted"] == pytest.approx(exact["actual"], rel=1e-9)
    assert exact["rel_error"] == pytest.approx(0, abs=1e-9)

    ys = [7 * x**2.5 for x in XS]
    ys[-1] *= 1.1  # the held-out point is 10% above the law the others follow
    h = scaling.holdout(XS, ys, scaling.fit_power_law)
    assert h["predicted"] == pytest.approx(7 * XS[-1] ** 2.5, rel=1e-9)  # the smaller sizes alone
    assert h["actual"] == pytest.approx(ys[-1])
    assert h["rel_error"] == pytest.approx(abs(h["predicted"] - h["actual"]) / h["actual"])


def test_estimate_scaling_holdout_picks_the_largest_x_even_if_the_input_is_unsorted():
    from quantum.estimate import scaling

    order = [3, 0, 5, 2, 1, 4]
    xs = [XS[i] for i in order]
    ys = [5 * x + 7 for x in xs]
    h = scaling.holdout(xs, ys, scaling.fit_linear)
    assert h["n_bits"] == max(XS) and h["actual"] == pytest.approx(5 * max(XS) + 7)
    assert h["rel_error"] == pytest.approx(0, abs=1e-9)


# ======================================================================================
# the common basis (lead, 2026-11-08): Clifford + T/Tdg + rz + ccx, pi/4 multiples as T/S
# ======================================================================================
ALLOWED = {
    "h",
    "x",
    "y",
    "z",
    "s",
    "sdg",
    "t",
    "tdg",
    "rz",
    "cx",
    "cz",
    "ccx",
    "id",
    "measure",
    "reset",
    "barrier",
}


def _lone_cp(theta: float) -> QuantumCircuit:
    qc = QuantumCircuit(2)
    qc.cp(theta, 0, 1)
    return qc


def _both(qc: QuantumCircuit) -> tuple[dict, dict]:
    from quantum.estimate import common, qdk, qualtran_est

    form = common.estimation_form(qc)
    return (qdk.qdk_logical_counts(form), qualtran_est.qualtran_counts_from_qasm(qasm2.dumps(form)))


@pytest.mark.parametrize(
    "qc_factory", [lambda: qft(5), lambda: _lone_cp(0.3), cswap_circuit, lambda: ccx_circuit(2)]
)
def test_estimate_form_uses_only_the_common_basis_and_no_pi_over_4_rotation(qc_factory):
    from quantum.estimate import common

    form = common.estimation_form(qc_factory())
    names = {i.operation.name for i in form.data}
    assert names <= ALLOWED, f"gates outside the common basis: {names - ALLOWED}"
    for inst in form.data:
        if inst.operation.name == "rz":
            quarter = float(inst.operation.params[0]) / (pi / 4)
            assert abs(quarter - round(quarter)) > 1e-9, "a pi/4 multiple must be T/S, not rz"


@pytest.mark.parametrize("theta", [0.3, pi / 8, pi / 4, pi / 2])
def test_estimate_lone_cp_in_the_common_basis_gets_the_same_count_from_both_tools(theta):
    qdk_c, qt_c = _both(_lone_cp(theta))
    assert qdk_c["rotation_count"] == qt_c["rotations"], (theta, qdk_c, qt_c)
    assert qdk_c["t_count"] == qt_c["t"], (theta, qdk_c, qt_c)
    assert qt_c["toffoli"] == 0 and qdk_c["ccz_count"] + qdk_c["ccix_count"] == 0


def test_estimate_lone_generic_cp_is_three_rotations_in_the_common_basis():
    qdk_c, qt_c = _both(_lone_cp(0.3))
    assert qdk_c["rotation_count"] == qt_c["rotations"] == 3


def test_estimate_lone_controlled_s_is_three_t_gates_in_the_common_basis():
    qdk_c, qt_c = _both(_lone_cp(pi / 2))
    assert qdk_c["t_count"] == qt_c["t"] == 3 and qdk_c["rotation_count"] == 0


def test_estimate_cswap_is_one_toffoli_in_both_tools_after_lowering():
    qdk_c, qt_c = _both(cswap_circuit())
    assert qdk_c["ccz_count"] + qdk_c["ccix_count"] == qt_c["toffoli"] == 1


def test_estimate_both_tools_agree_on_whole_qfts_and_adders_in_the_common_basis():
    for n in (3, 5, 7):
        qdk_c, qt_c = _both(qft(n))
        assert _equiv_qdk(qdk_c) == pytest.approx(_equiv_qt(qt_c), rel=0.05), (n, qdk_c, qt_c)


# ---- Qualtran mapping rule (lead, 2026-11-08): toffoli = and_bloq + cswap + toffoli(raw) ----
def _cost_of(bloq):
    from qualtran.resource_counting import QECGatesCost, get_cost_value

    return get_cost_value(bloq, QECGatesCost())


def test_estimate_qualtran_mapping_one_and_counts_one_and_its_adjoint_counts_zero():
    """Hand count: compute an AND (1 Toffoli-equivalent), uncompute it by measurement (0)."""
    from qualtran import BloqBuilder
    from qualtran.bloqs.mcmt import And

    from quantum.estimate import qualtran_est

    bb = BloqBuilder()
    c = bb.add_register("c", 2)
    c0, c1 = bb.split(c)
    ctrl, target = bb.add(And(), ctrl=[c0, c1])
    ctrl = bb.add(And().adjoint(), ctrl=ctrl, target=target)
    cbloq = bb.finalize(c=bb.join(ctrl))
    raw = _cost_of(cbloq)
    assert (raw.and_bloq, raw.measurement) == (1, 1)  # one And, one measurement-based uncompute

    only_and = _cost_of(And())
    only_adj = _cost_of(And().adjoint())
    assert qualtran_est.qualtran_counts_from_cost(only_and, 3)["toffoli"] == 1
    assert qualtran_est.qualtran_counts_from_cost(only_adj, 3)["toffoli"] == 0
    assert qualtran_est.qualtran_counts_from_cost(raw, 2)["toffoli"] == 1


def test_estimate_qualtran_mapping_one_cswap_counts_one_and_a_raw_toffoli_counts_one():
    from qualtran.bloqs.basic_gates import CSwap, Toffoli

    from quantum.estimate import qualtran_est

    m = qualtran_est.qualtran_counts_from_cost
    assert m(_cost_of(CSwap(1)), 3)["toffoli"] == 1
    assert m(_cost_of(Toffoli()), 3)["toffoli"] == 1
