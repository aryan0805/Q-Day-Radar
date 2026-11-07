"""Phase 0 smoke test: Bell state on the ideal simulator.

Checks the *answer*, not just that the run completes: only the correlated
outcomes 00 and 11 may appear, and both must appear at roughly equal weight.
A negative control proves the check can fail on an uncorrelated circuit.

Uses AerSimulator directly, so it does not depend on quantum/backends.py.
"""

import pytest
from qiskit import QuantumCircuit
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2

SHOTS = 4000


def _bell() -> QuantumCircuit:
    qc = QuantumCircuit(2, 2, name="bell")
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qc


def _uncorrelated() -> QuantumCircuit:
    """Control: H on both qubits, no entanglement. All four outcomes appear."""
    qc = QuantumCircuit(2, 2, name="uncorrelated")
    qc.h(0)
    qc.h(1)
    qc.measure([0, 1], [0, 1])
    return qc


def _counts(qc: QuantumCircuit, seed: int) -> dict[str, int]:
    backend = AerSimulator(seed_simulator=seed)
    isa = generate_preset_pass_manager(
        optimization_level=1, backend=backend, seed_transpiler=seed
    ).run(qc)
    sampler = SamplerV2(default_shots=SHOTS, seed=seed)
    result = sampler.run([isa]).result()
    return result[0].data.c.get_counts()


def test_bell_only_correlated_outcomes(seed):
    counts = _counts(_bell(), seed)
    assert set(counts) == {"00", "11"}, f"unexpected outcomes: {counts}"
    assert sum(counts.values()) == SHOTS


def test_bell_outcomes_are_balanced(seed):
    counts = _counts(_bell(), seed)
    # Binomial sigma at 4000 shots is ~32 counts; accept +/- 200 (~6 sigma).
    assert abs(counts["00"] - SHOTS / 2) < 200, counts
    assert abs(counts["11"] - SHOTS / 2) < 200, counts


@pytest.mark.parametrize("bad", ["01", "10"])
def test_check_catches_uncorrelated_circuit(seed, bad):
    """Control: the Bell assertion must fail on a circuit without entanglement."""
    counts = _counts(_uncorrelated(), seed)
    assert bad in counts, "control circuit should produce anti-correlated outcomes"
    assert set(counts) != {"00", "11"}
