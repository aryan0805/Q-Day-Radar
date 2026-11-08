"""Phase 1 units 3+4: generic Beauregard Shor (N=15, N=21) with a recycled control.

Every expected value comes from tests/phase1/reference.py (closed-form QPE). Circuits are
simulated here with AerSimulator directly. The leak tests rebuild the SAME builder for other
(N, a) and check it still finds the classically computed order and factors.
"""

import ast
import inspect
import json
import math
from math import gcd

import numpy as np
import pytest
from qiskit import ClassicalRegister, QuantumCircuit, transpile
from qiskit_aer import AerSimulator

from quantum.circuits import beauregard, registry
from quantum.circuits.beauregard import build_shor
from quantum.classical import postprocess
from quantum.metrics import record_circuit_metrics
from tests.phase1.reference import (
    factors_from_order,
    mult_order,
    qpe_outcome_probs,
    shor_chance_baseline,
    shor_theoretical_success,
)

SHOTS = 8192
N15_A = [2, 4, 7, 8, 11, 13, 14]
N21_A = [2, 4, 5, 8, 10, 11, 13, 16, 17, 19, 20]
CASES = [(15, a) for a in N15_A] + [(21, a) for a in N21_A]
_CACHE: dict = {}


def _counts(circuit, seed=1234):
    sim = AerSimulator(seed_simulator=seed, shot_branching_enable=True)
    return sim.run(transpile(circuit, sim, optimization_level=0), shots=SHOTS).result().get_counts()


def run(n, a, *, fold=True):
    key = (n, a, fold)
    if key not in _CACHE:
        qc = build_shor(n, a, fold_constants=fold)
        # one seed per case: bases with the same order would otherwise give identical samples
        _CACHE[key] = (qc, _counts(qc, seed=1000 + 31 * n + a))
    return _CACHE[key]


def _dephased(qc, where):
    """Z-basis measurement of the recycled control (a full dephasing) around the final H."""
    junk = ClassicalRegister(1, "junk")
    out = QuantumCircuit(*qc.qregs, *qc.cregs, junk)
    for inst in qc.data:
        if inst.operation.name == "measure":
            assert out.data[-1].operation.name == "h"
            if where == "before_final_h":
                h = out.data.pop()
                out.measure(inst.qubits[0], junk[0])
                out.append(h.operation, h.qubits)
            else:  # dephasing after the final H is a no-op for the measured bit
                out.measure(inst.qubits[0], junk[0])
        out.append(inst.operation, inst.qubits, inst.clbits)
    return out


def _success(counts, n, a, t):
    r = mult_order(a, n)
    return (
        sum(c for b, c in counts.items() if postprocess.order_from_shot(int(b, 2), t, a, n) == r)
        / SHOTS
    )


# ---- structure of the dynamic circuit -----------------------------------------------------


@pytest.mark.parametrize(("n", "a", "qubits", "t"), [(15, 7, 11, 8), (21, 2, 13, 10)])
def test_shor_beauregard_layout_is_2n_plus_3_with_one_recycled_control(n, a, qubits, t):
    qc = build_shor(n, a)
    assert qc.num_qubits == qubits  # 2 * bit_length + 3
    assert [(r.name, r.size) for r in qc.cregs] == [("phase", t)]
    ops = qc.count_ops()
    assert ops["measure"] == t  # one measurement per phase bit
    assert ops["reset"] == t - 1  # the single control is recycled between them
    assert ops["if_else"] == t * (t - 1) // 2  # semi-classical QFT: one correction per earlier bit


@pytest.mark.parametrize(("name", "n", "a", "t"), [
    ("shor15_beauregard", 15, 7, 8), ("shor21_beauregard", 21, 2, 10),
])  # fmt: skip
def test_shor_beauregard_registry_metadata(name, n, a, t):
    qc = registry.build_circuit(name)
    md = qc.metadata
    assert md["name"] == name and md["kind"] == "generic"
    assert (md["N"], md["a"], md["n_count"]) == (n, a, t)
    assert not {"r", "order", "factors", "p", "q"} & set(md)
    assert math.isclose(md["theoretical_success"], shor_theoretical_success(a, n, t), abs_tol=1e-6)


def test_shor_beauregard_rejects_bad_inputs():
    for n, a in [(15, 3), (15, 1), (15, 15), (2, 1), (21, 7)]:
        with pytest.raises(ValueError):
            build_shor(n, a)


# ---- the distribution is the analytic QPE distribution ------------------------------------


@pytest.mark.parametrize(("n", "a"), CASES)
def test_shor_beauregard_success_matches_theory_for_other_inputs(n, a):
    t = 2 * n.bit_length()
    _, counts = run(n, a)
    got = _success(counts, n, a, t)
    want = shor_theoretical_success(a, n, t)
    assert abs(got - want) < 0.02, f"N={n} a={a}: {got:.4f} vs {want:.4f}"


@pytest.mark.parametrize("a", N15_A)
def test_shor_beauregard_n15_support_is_exactly_the_dyadic_peaks(a):
    # r in {2, 4}: phases s/r are exact multiples of 1/2**8, so any off-peak shot is an error
    r = mult_order(a, 15)
    t = 8
    peaks = {s * 2**t // r for s in range(r)}
    _, counts = run(15, a)
    assert {int(b, 2) for b in counts} <= peaks
    for peak in peaks:
        frac = sum(c for b, c in counts.items() if int(b, 2) == peak) / SHOTS
        assert abs(frac - 1 / r) < 0.03, f"a={a} peak={peak}: {frac}"


@pytest.mark.parametrize(("n", "a"), [(21, 2), (21, 5), (21, 4)])
def test_shor_beauregard_n21_histogram_close_to_analytic_distribution(n, a):
    t, r = 10, mult_order(a, n)
    probs = sum(qpe_outcome_probs(t, s / r) for s in range(r)) / r
    _, counts = run(n, a)
    emp = np.zeros(2**t)
    for b, c in counts.items():
        emp[int(b, 2)] = c / SHOTS
    tv = 0.5 * np.abs(emp - probs).sum()
    assert tv < 0.1, f"N={n} a={a} total variation {tv:.3f}"


@pytest.mark.parametrize(("n", "a"), [(21, 2), (21, 10)])
def test_shor_beauregard_n21_is_coherent_not_dephased(n, a):
    t = 2 * n.bit_length()
    _, counts = run(n, a)
    assert _success(counts, n, a, t) > 0.25


def _phase_counts(counts):
    merged: dict[str, int] = {}
    for b, c in counts.items():
        phase = b.split()[-1]  # registers print as 'junk phase'
        merged[phase] = merged.get(phase, 0) + c
    return merged


@pytest.mark.parametrize(("n", "a", "chance_ceiling"), [(15, 7, 0.3), (21, 2, 0.15)])
def test_shor_beauregard_detects_a_dephased_control(n, a, chance_ceiling):
    # Dephasing the control before the final H randomises every bit: success falls to chance
    # (0.17 at N=15, 0.075 at N=21). Both sizes can tell coherent from dephased.
    t = 2 * n.bit_length()
    sim = AerSimulator(seed_simulator=7, shot_branching_enable=True)
    qc = _dephased(build_shor(n, a), "before_final_h")
    counts = sim.run(transpile(qc, sim, optimization_level=0), shots=SHOTS).result().get_counts()
    assert _success(_phase_counts(counts), n, a, t) < chance_ceiling


def test_shor_beauregard_dephasing_after_the_final_h_changes_nothing():
    # guards the test above: a dephasing placed after the H is invisible, so it must NOT be
    # the 'noise' we use to claim a circuit is sensitive
    sim = AerSimulator(seed_simulator=7, shot_branching_enable=True)
    qc = _dephased(build_shor(21, 2), "after_final_h")
    counts = sim.run(transpile(qc, sim, optimization_level=0), shots=SHOTS).result().get_counts()
    assert abs(_success(_phase_counts(counts), 21, 2, 10) - 0.3307) < 0.03


# ---- leak tests: the same builder recovers order and factors for other inputs --------------


@pytest.mark.parametrize(("n", "a"), CASES)
def test_leak_shor_beauregard_recovers_classical_order_and_factors(n, a):
    t = 2 * n.bit_length()
    r = mult_order(a, n)
    _, counts = run(n, a)
    recovered: dict = {}
    for b, c in counts.items():
        d = postprocess.order_from_shot(int(b, 2), t, a, n)
        recovered[d] = recovered.get(d, 0) + c  # SUM the shots per recovered value
    assert r in recovered, f"N={n} a={a}: true order {r} never recovered; got {list(recovered)}"
    answered = {d: c for d, c in recovered.items() if d is not None}
    # the true order is the modal answer, and wrong answers (multiples of r) are rare noise
    assert max(answered, key=answered.get) == r
    assert answered[r] / sum(answered.values()) > 0.97
    assert postprocess.factors_from_order(a, r, n) == factors_from_order(a, n, r)


@pytest.mark.parametrize("n", [15, 21])
def test_leak_shor_beauregard_signature_takes_no_order_or_factor(n):
    params = inspect.signature(build_shor).parameters
    assert set(params) == {"N", "a", "fold_constants", "skip_identity"}, set(params)
    # the opt-in flags are keyword-only and default to the honest, generic behaviour
    assert params["fold_constants"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["skip_identity"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["fold_constants"].default is True and params["skip_identity"].default is False


def test_leak_shor_beauregard_source_never_uses_the_classical_answer_helpers():
    tree = ast.parse(inspect.getsource(beauregard))
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imported = {
        a.name.split(".")[-1]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in n.names
    } | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    forbidden = {
        "classical_order", "order_from_shot", "factors_from_order", "mult_order",
        "THEORY_FN", "SUCCESS_FN", "SHOR_CASES",
    }  # fmt: skip
    assert not (used | imported) & forbidden, (used | imported) & forbidden
    assert not any("registry" in str(m) or "postprocess" in str(m) for m in imported)


@pytest.mark.parametrize("n", [15, 21])
def test_leak_shor_beauregard_unfolded_structure_is_independent_of_a(n):
    # fold_constants=False builds all 2n controlled multipliers whatever a is: same cswap count
    bits = n.bit_length()
    counts = {
        build_shor(n, a, fold_constants=False).count_ops().get("cswap")
        for a in (N15_A if n == 15 else N21_A)
    }
    assert counts == {2 * bits * bits}, counts


@pytest.mark.parametrize("n", [15, 21])
def test_leak_shor_beauregard_default_structure_is_independent_of_the_order(n):
    # P003: honest generic = 1 controlled load + (2*bits - 1) full multipliers whatever a (and r)
    bits = n.bit_length()
    want = (2 * bits - 1) * bits
    got = {a: build_shor(n, a).count_ops().get("cswap", 0) for a in (N15_A if n == 15 else N21_A)}
    assert set(got.values()) == {want}, got


@pytest.mark.parametrize("name", ["shor15_beauregard", "shor21_beauregard"])
def test_leak_shor_beauregard_registry_circuits_are_the_honest_build(name):
    qc = registry.build_circuit(name)
    bits = qc.metadata["N"].bit_length()
    assert qc.metadata["kind"] == "generic"
    assert qc.count_ops()["cswap"] == (2 * bits - 1) * bits


@pytest.mark.parametrize("n", [15, 21])
def test_leak_shor_beauregard_default_kind_is_generic_for_every_a(n):
    for a in N15_A if n == 15 else N21_A:
        assert build_shor(n, a).metadata["kind"] == "generic"
        assert build_shor(n, a, fold_constants=False).metadata["kind"] == "generic"


def test_leak_shor_beauregard_skip_identity_is_labeled_compiled_and_shrinks_with_order():
    # the opt-in shortcut is allowed only if it is declared: it makes size depend on r
    for a, r in [(7, 4), (4, 2)]:
        qc = build_shor(15, a, skip_identity=True)
        assert qc.metadata["kind"] == "compiled", (a, r)
        assert qc.count_ops().get("cswap", 0) < 28
    assert build_shor(15, 4, skip_identity=True).count_ops().get("cswap", 0) == 0
    # and for an order that is not a power of two nothing is skipped, so it is still the same
    assert build_shor(21, 2, skip_identity=True).count_ops()["cswap"] == 45


def test_shor_beauregard_skip_identity_variant_still_gives_correct_distribution():
    qc = build_shor(15, 7, skip_identity=True)
    counts = _counts(qc)
    assert {int(b, 2) for b in counts} <= {0, 64, 128, 192}
    assert abs(_success(counts, 15, 7, 8) - 0.5) < 0.03


# ---- the unfolded arithmetic itself -------------------------------------------------------


def test_shor_beauregard_unfolded_n15_a7_matches_theory():
    # fold_constants=False exercises every modular multiplier, not just the folded subset
    _, counts = run(15, 7, fold=False)
    assert {int(b, 2) for b in counts} <= {0, 64, 128, 192}
    assert abs(_success(counts, 15, 7, 8) - 0.5) < 0.03


def test_shor_beauregard_unfolded_n21_a2_matches_theory():
    _, counts = run(21, 2, fold=False)
    assert abs(_success(counts, 21, 2, 10) - shor_theoretical_success(2, 21, 10)) < 0.03


# ---- metrics ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def records(tmp_path_factory):
    out = tmp_path_factory.mktemp("beauregard_metrics")
    return {
        name: record_circuit_metrics(name, registry.build_circuit(name), out_dir=out)
        for name in ("shor15_beauregard", "shor21_beauregard")
    }, out


@pytest.mark.parametrize("name", ["shor15_beauregard", "shor21_beauregard"])
def test_shor_beauregard_metrics_record(records, name):
    recs, out = records
    rec = recs[name]
    assert rec["kind"] == "generic" and rec["shots"] >= 8192
    assert rec["success_probability"] >= rec["theoretical_success"] - 0.02
    assert abs(rec["success_probability"] - rec["theoretical_success"]) <= 0.02  # two-sided
    n, a = (15, 7) if name == "shor15_beauregard" else (21, 2)
    assert math.isclose(
        rec["chance_baseline"], shor_chance_baseline(a, n, 2 * n.bit_length()), abs_tol=1e-9
    )
    assert rec["success_probability"] > rec["chance_baseline"]  # theory is above chance here
    assert rec["two_qubit_gates"] > 0 and rec["transpile"]["optimization_level"] == 3
    assert json.loads((out / f"{name}.json").read_text()) == rec
    assert gcd(rec["n_qubits"], 1) == 1 and rec["n_qubits"] in (11, 13)
