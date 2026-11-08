"""The QPU-seconds estimate (quantum/run/hardware.py). Names contain `budget`: it feeds the cap.

Lead's rule: estimate = max(builder's model, IBM baseline formula), x1.5 safety, rounded UP to
0.1 s. There are no dry runs on the Open Plan, so an estimate that is too low can overspend.
"""

import itertools
import math

import pytest

hardware = pytest.importorskip("quantum.run.hardware")

REP_DELAY, MEAS_PAD, SAFETY = 250e-6, 5e-6, 1.5


def builder_model(d, shots, n_mid=0):
    return 2.0 + shots * (REP_DELAY + d + 2e-6 * n_mid + MEAS_PAD)


def ibm_baseline(d, shots):
    return 2.0 + (REP_DELAY + d) * shots


def unrounded(d, shots, n_mid=0):
    return SAFETY * max(builder_model(d, shots, n_mid), ibm_baseline(d, shots))


GRID = list(itertools.product([1e-6, 2e-5, 1e-4, 4e-4, 1e-3], [1, 100, 4096, 8192], [0, 3, 40]))


@pytest.mark.parametrize(("d", "shots", "n_mid"), GRID)
def test_budget_estimate_matches_the_independent_formula_rounded_up(d, shots, n_mid):
    got = hardware.estimate_from_duration(d, shots, n_mid)
    want = unrounded(d, shots, n_mid)
    assert got >= want - 1e-9, "rounding must go up, never down"
    assert got <= want + 0.1 + 1e-9
    assert math.isclose(round(got * 10), got * 10, abs_tol=1e-6), "multiple of 0.1 s"


@pytest.mark.parametrize(("d", "shots", "n_mid"), GRID)
def test_budget_estimate_is_never_below_the_ibm_baseline(d, shots, n_mid):
    got = hardware.estimate_from_duration(d, shots, n_mid)
    assert got >= ibm_baseline(d, shots)
    assert got >= SAFETY * ibm_baseline(d, shots) - 1e-9


def test_budget_estimate_pinned_example():
    # 4096 shots of a 400 us circuit: IBM baseline 2 + 650e-6 * 4096 = 4.66 s; the model adds
    # 5 us/shot -> 2 + 655e-6 * 4096 = 4.68288 s; x1.5 = 7.02432 s; rounded UP to 0.1 s = 7.1 s
    d, shots = 400e-6, 4096
    assert ibm_baseline(d, shots) == pytest.approx(4.6624)
    assert unrounded(d, shots) == pytest.approx(1.5 * (2.0 + 4096 * 655e-6))
    assert unrounded(d, shots) == pytest.approx(7.02432)
    assert hardware.estimate_from_duration(d, shots) == pytest.approx(7.1)


def test_budget_estimate_grows_with_shots_duration_and_mid_circuit_operations():
    base = hardware.estimate_from_duration(2e-4, 4096, 0)
    assert hardware.estimate_from_duration(2e-4, 8192, 0) > base
    assert hardware.estimate_from_duration(4e-4, 4096, 0) > base
    assert hardware.estimate_from_duration(2e-4, 4096, 400) > base


@pytest.mark.parametrize("config", ["dd", "dd_twirl", "m3_cal", "control"])
def test_budget_estimate_for_any_config_is_at_least_the_raw_estimate(config):
    for d, shots in [(1e-4, 4096), (5e-4, 4096), (2e-4, 8192)]:
        raw = hardware.estimate_from_duration(d, shots, 0, config="raw")
        assert hardware.estimate_from_duration(d, shots, 0, config=config) >= raw


def test_budget_twirled_estimate_is_not_below_the_ibm_formula_for_randomizations():
    # 32 randomizations x 128 shots = 4096 executions: the baseline for the same total shots
    d = 3e-4
    assert hardware.estimate_from_duration(d, 4096, 0, config="dd_twirl") >= SAFETY * ibm_baseline(
        d, 4096
    )


def test_budget_estimate_seconds_uses_the_circuit_duration_on_the_target():
    from qiskit import QuantumCircuit
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    from quantum.backends import get_fake_backend

    backend = get_fake_backend()
    qc = QuantumCircuit(3, 3)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)
    qc.measure([0, 1, 2], [0, 1, 2])
    isa = generate_preset_pass_manager(
        optimization_level=3, backend=backend, seed_transpiler=1234
    ).run(qc)
    d = isa.estimate_duration(backend.target)
    assert d > 0
    got = hardware.estimate_seconds(isa, 4096, target=backend.target, config="raw")
    assert got == pytest.approx(hardware.estimate_from_duration(d, 4096, 0, config="raw"))
    assert got >= ibm_baseline(d, 4096)


def test_budget_longer_circuit_costs_more_than_a_shorter_one():
    from qiskit import QuantumCircuit
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    from quantum.backends import get_fake_backend

    backend = get_fake_backend()
    pm = generate_preset_pass_manager(optimization_level=0, backend=backend, seed_transpiler=1)

    def circ(depth):
        qc = QuantumCircuit(2, 2)
        for _ in range(depth):
            qc.cx(0, 1)
        qc.measure([0, 1], [0, 1])
        return pm.run(qc)

    short = hardware.estimate_seconds(circ(2), 4096, target=backend.target, config="raw")
    long = hardware.estimate_seconds(circ(200), 4096, target=backend.target, config="raw")
    assert long > short
