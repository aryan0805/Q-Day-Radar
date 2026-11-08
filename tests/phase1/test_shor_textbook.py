"""Phase 1 unit 2: textbook Shor N=15, a=7 (kind=compiled), and the scoring/metrics path.

The circuit is simulated here with AerSimulator directly and scored by counting peaks, so the
checks do not depend on builder's metrics or registry code.
"""

import json
import math
from datetime import datetime

import pytest
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator

from quantum.circuits import registry
from quantum.classical import postprocess
from quantum.metrics import record_circuit_metrics, success_probability
from tests.phase1.reference import shor_chance_baseline, shor_theoretical_success

SHOTS = 8192
PEAKS = {0, 64, 128, 192}  # j/4 of 2**8
SCHEMA = {
    "name", "kind", "n_qubits", "depth", "two_qubit_gates", "transpile",
    "success_probability", "theoretical_success", "shots", "seed_simulator",
    "qiskit_version", "timestamp",
}  # fmt: skip
HERON_BASIS = {"cz", "id", "rz", "sx", "x"}


@pytest.fixture(scope="module")
def circuit():
    return registry.build_circuit("shor15_textbook")


@pytest.fixture(scope="module")
def counts(circuit):
    sim = AerSimulator(seed_simulator=1234)
    return sim.run(transpile(circuit, sim, optimization_level=0), shots=SHOTS).result().get_counts()


# ---- the circuit gives the right distribution ---------------------------------------


def test_shor_textbook_support_is_exactly_the_four_peaks(counts):
    assert {int(b, 2) for b in counts} <= PEAKS
    assert {int(b, 2) for b in counts} == PEAKS  # all four appear in 8192 shots


def test_shor_textbook_peaks_are_equally_likely(counts):
    for peak in PEAKS:
        frac = sum(n for b, n in counts.items() if int(b, 2) == peak) / SHOTS
        assert abs(frac - 0.25) < 0.03, f"peak {peak}: {frac}"


def test_shor_textbook_bit_order_is_weight_2_to_j(counts):
    # m = 64 is '01000000' read as int(bitstring, 2); a reversed register would give m = 2
    assert "01000000" in counts and "00000010" not in counts


def test_shor_textbook_shots_recover_order_4_and_factors_3_5(counts):
    recovered = {
        int(b, 2): postprocess.order_from_shot(int(b, 2), 8, 7, 15) for b in counts
    }
    assert recovered == {0: None, 64: 4, 128: None, 192: 4}
    assert postprocess.factors_from_order(7, 4, 15) == (3, 5)


def test_shor_textbook_success_fraction_is_one_half_by_hand_count(counts):
    good = sum(n for b, n in counts.items() if int(b, 2) in (64, 192)) / SHOTS
    assert abs(good - 0.5) < 0.03
    assert abs(success_probability("shor15_textbook", counts) - good) < 1e-12


# ---- labels and what the circuit exposes ---------------------------------------------


def test_shor_textbook_metadata_label_and_inputs(circuit):
    md = circuit.metadata
    assert md["name"] == "shor15_textbook"
    assert md["kind"] == "compiled"
    assert (md["N"], md["a"], md["n_count"]) == (15, 7, 8)
    assert not {"r", "order", "factors", "p", "q"} & set(md)


def test_shor_textbook_single_classical_register_phase(circuit):
    assert [(r.name, r.size) for r in circuit.cregs] == [("phase", 8)]


def test_shor_textbook_theoretical_success_matches_independent_value(circuit):
    assert math.isclose(
        circuit.metadata["theoretical_success"], shor_theoretical_success(7, 15, 8), abs_tol=1e-6
    )


# ---- registry scoring and theory tables ----------------------------------------------


def test_shor_registry_names_cover_the_seven_required():
    required = {
        "shor15_textbook", "shor15_beauregard", "shor21_beauregard",
        "grover_present_k2", "grover_present_k3", "grover_present_k4", "grover_present_k5",
    }  # fmt: skip
    assert set(registry.SUCCESS_FN) == required == set(registry.THEORY_FN)


@pytest.mark.parametrize(
    ("name", "n", "a", "t"),
    [
        ("shor15_textbook", 15, 7, 8),
        ("shor15_beauregard", 15, 7, 8),
        ("shor21_beauregard", 21, 2, 10),
    ],
)
def test_shor_registry_theory_matches_independent_qpe_value(name, n, a, t):
    assert math.isclose(
        registry.THEORY_FN[name](), shor_theoretical_success(a, n, t), abs_tol=1e-6
    )


@pytest.mark.parametrize(
    ("bits", "expected"),
    [("01000000", True), ("11000000", True), ("10000000", False), ("00000000", False),
     ("00000001", False), ("0100 0000", True)],
)  # fmt: skip
def test_shor_registry_success_fn_textbook(bits, expected):
    assert registry.SUCCESS_FN["shor15_textbook"](bits) is expected


def _check_chance_baseline(rec, expected):
    # recomputed independently (tests/phase1/reference.py), then: a circuit that beats chance in
    # theory must beat it in the measurement
    assert math.isclose(rec["chance_baseline"], expected, abs_tol=1e-9)
    if rec["theoretical_success"] > rec["chance_baseline"]:
        assert rec["success_probability"] > rec["chance_baseline"]


def test_shor_chance_baselines_pinned():
    # 44 of the 256 outcomes at N=15 (t=8), 80 of 1024 at N=21 (t=10)
    assert math.isclose(shor_chance_baseline(7, 15, 8), 44 / 256)
    assert math.isclose(shor_chance_baseline(2, 21, 10), 80 / 1024)
    assert math.isclose(shor_chance_baseline(7, 15, 8), 0.171875)


# ---- metrics recorder, end to end into tmp_path --------------------------------------


@pytest.fixture(scope="module")
def record(circuit, tmp_path_factory):
    out = tmp_path_factory.mktemp("metrics")
    rec = record_circuit_metrics("shor15_textbook", circuit, out_dir=out)
    return rec, out


def test_shor_metrics_schema_and_types(record):
    rec, _ = record
    assert set(rec) == SCHEMA | {"chance_baseline"}
    assert rec["name"] == "shor15_textbook" and rec["kind"] == "compiled"
    assert rec["n_qubits"] == 12
    assert isinstance(rec["depth"], int) and rec["depth"] > 0
    assert isinstance(rec["two_qubit_gates"], int) and rec["two_qubit_gates"] > 0
    assert rec["shots"] >= 8192
    assert set(rec["transpile"]) == {"backend", "optimization_level", "seed_transpiler", "depth"}
    assert rec["transpile"]["backend"] == "fake_kingston"
    assert rec["transpile"]["depth"] >= rec["depth"] // 4 > 0
    datetime.fromisoformat(rec["timestamp"])
    assert rec["qiskit_version"].startswith("2.")


def test_shor_metrics_file_matches_returned_record(record):
    rec, out = record
    assert json.loads((out / "shor15_textbook.json").read_text()) == rec


def test_shor_metrics_success_meets_theory_minus_tolerance(record):
    rec, _ = record
    assert rec["success_probability"] >= rec["theoretical_success"] - 0.02
    # two-sided: a circuit that leaks the answer would score ABOVE theory (audit finding)
    assert abs(rec["success_probability"] - rec["theoretical_success"]) <= 0.02
    _check_chance_baseline(rec, shor_chance_baseline(7, 15, 8))
    assert math.isclose(rec["theoretical_success"], 0.5, abs_tol=1e-6)


def test_shor_metrics_success_is_a_probability_not_trivially_one(record):
    rec, _ = record
    assert 0.4 < rec["success_probability"] < 0.6


def test_shor_metrics_two_qubit_count_uses_only_heron_basis(circuit):
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    from quantum.backends import get_fake_backend

    pm = generate_preset_pass_manager(
        optimization_level=3, backend=get_fake_backend(), seed_transpiler=1234
    )
    tqc = pm.run(circuit)
    assert set(tqc.count_ops()) - {"measure", "barrier", "delay"} <= HERON_BASIS


def test_shor_metrics_refuses_fewer_than_8192_shots(circuit, tmp_path):
    with pytest.raises(ValueError):
        record_circuit_metrics("shor15_textbook", circuit, shots=4096, out_dir=tmp_path)


# ---- the multiplier blocks do what the metadata says (a=7), not only "an order-4 map" ------


def _block_table(power: int, control: int) -> dict[int, int]:
    """Map x -> output of the controlled block for 7**power, on every nonzero x."""
    from quantum.circuits.shor_textbook import _controlled_mult

    out = {}
    for x in range(1, 15):
        qc = QuantumCircuit(5)  # qubit 0 control, 1..4 work (little-endian x)
        _controlled_mult(qc, 0, [1, 2, 3, 4], power)
        sv = Statevector.from_int(control | (x << 1), 32).evolve(qc)
        idx = int(abs(sv.data).argmax())
        assert abs(abs(sv.data[idx]) - 1) < 1e-9, "block must map basis states to basis states"
        assert idx & 1 == control  # the control is untouched
        out[x] = idx >> 1
    return out


@pytest.mark.parametrize("power", [1, 2, 4, 8])
def test_shor_textbook_blocks_multiply_by_7_to_the_power_mod_15(power):
    # The outcome distribution is the same for a and a**-1, so only a block-level test can tell
    # x*7 from x*13 (7**-1 mod 15). Metadata and docstring say a = 7.
    mult = pow(7, power, 15)
    got = _block_table(power, control=1)
    assert got == {x: (mult * x) % 15 for x in range(1, 15)}, f"power={power}: not x*{mult}"


@pytest.mark.parametrize("power", [1, 2])
def test_shor_textbook_blocks_do_nothing_when_control_is_zero(power):
    assert _block_table(power, control=0) == {x: x for x in range(1, 15)}


def test_shor_textbook_transpiled_circuit_matches_theory():
    # metrics.py never simulates the transpiled circuit it counts gates for; do it here
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    from quantum.backends import get_fake_backend

    qc = registry.build_circuit("shor15_textbook")
    tqc = generate_preset_pass_manager(
        optimization_level=3, backend=get_fake_backend(), seed_transpiler=1234
    ).run(qc)
    sim = AerSimulator(seed_simulator=99)
    counts = sim.run(tqc, shots=SHOTS).result().get_counts()
    assert {int(b, 2) for b in counts} <= PEAKS
    assert abs(success_probability("shor15_textbook", counts) - 0.5) < 0.03


# ---- audit follow-ups: F7 compiled_reason, F8 registry/builder agreement, P004 metadata -------


def test_shor_textbook_metadata_explains_why_it_is_compiled(circuit):
    reason = circuit.metadata["compiled_reason"]
    assert isinstance(reason, str) and len(reason) > 20


def test_shor_registry_rejects_builder_metadata_that_disagrees():
    good = dict(registry.build_circuit("shor15_beauregard").metadata)
    registry._check_metadata("shor15_beauregard", good)  # agreement is accepted
    for key, bad in [("N", 21), ("a", 2), ("n_count", 6)]:
        with pytest.raises(ValueError):
            registry._check_metadata("shor15_beauregard", {**good, key: bad})


@pytest.mark.parametrize(
    ("name", "n", "a", "t"),
    [("shor15_textbook", 15, 7, 8), ("shor15_beauregard", 15, 7, 8),
     ("shor21_beauregard", 21, 2, 10)],
)  # fmt: skip
def test_shor_circuit_metadata_carries_the_independent_chance_baseline(name, n, a, t):
    md = registry.build_circuit(name).metadata
    assert math.isclose(md["chance_baseline"], shor_chance_baseline(a, n, t), abs_tol=1e-9)
    assert md["theoretical_success"] > md["chance_baseline"]
