"""Phase 0: quantum/backends.py.

Contract agreed in the builder's [INTERFACE] message. Nothing here submits a job
to IBM or opens a network connection. The "real" backend is only tested on its
no-token failure path, with QiskitRuntimeService replaced by a tripwire so a
token found in a local .env cannot cause a real login.
"""

import pytest
from qiskit import QuantumCircuit
from qiskit.quantum_info import hellinger_fidelity
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_ibm_runtime.fake_provider import FakeKingston

from quantum import backends
from quantum.backends import (
    MissingTokenError,
    get_backend,
    get_fake_backend,
    get_ideal_simulator,
    get_noisy_simulator,
    get_real_backend,
)

SHOTS = 4000
# Non-gate instructions that are legal in an ISA circuit but are not in operation_names.
NON_GATES = {"measure", "barrier", "delay"}


def _bell() -> QuantumCircuit:
    qc = QuantumCircuit(2, 2, name="bell")
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qc


def _isa_bell(seed: int) -> QuantumCircuit:
    # Level 3 does noise-aware layout. Level 1 keeps physical qubits 0,1, which are
    # among Kingston's noisier pairs: Hellinger fidelity 0.83 there vs 0.99 on the
    # qubits level 3 picks. Real runs should use level 3, so the test does too.
    pm = generate_preset_pass_manager(
        optimization_level=3, backend=get_fake_backend(), seed_transpiler=seed
    )
    return pm.run(_bell())


@pytest.fixture
def no_ibm_login(monkeypatch):
    """Fail loudly if anything tries to log in to IBM, and hide any env token."""
    monkeypatch.delenv("QISKIT_IBM_TOKEN", raising=False)

    def tripwire(*args, **kwargs):
        raise AssertionError("test must not log in to IBM Quantum")

    monkeypatch.setattr("qiskit_ibm_runtime.QiskitRuntimeService", tripwire)
    if hasattr(backends, "QiskitRuntimeService"):
        monkeypatch.setattr(backends, "QiskitRuntimeService", tripwire)


# ---- the three simulator-side backends ----------------------------------------


def test_ideal_simulator_is_noiseless_and_unconstrained():
    sim = get_ideal_simulator()
    assert isinstance(sim, AerSimulator)
    assert sim.options.noise_model is None
    assert sim.coupling_map is None


def test_fake_backend_is_kingston():
    fake = get_fake_backend()
    assert isinstance(fake, FakeKingston)
    assert fake.num_qubits >= 100


def test_noisy_simulator_carries_a_noise_model():
    sim = get_noisy_simulator()
    assert isinstance(sim, AerSimulator)
    assert sim.options.noise_model is not None
    assert sim.num_qubits == get_fake_backend().num_qubits


# ---- transpilation targets the device's real basis ----------------------------


def test_transpiled_bell_uses_only_kingston_basis_gates(seed):
    fake = get_fake_backend()
    isa = _isa_bell(seed)
    used = set(isa.count_ops()) - NON_GATES
    assert used, "transpiled circuit has no gates"
    assert used <= set(fake.operation_names), (
        f"gates outside the device basis: {used - set(fake.operation_names)}"
    )
    # The textbook gates must have been rewritten, not passed through.
    assert "h" not in used
    assert "cx" not in used


def test_transpiled_two_qubit_gates_sit_on_coupled_qubits(seed):
    fake = get_fake_backend()
    isa = _isa_bell(seed)
    edges = {tuple(e) for e in fake.coupling_map.get_edges()}
    two_q = [
        tuple(isa.find_bit(q).index for q in inst.qubits)
        for inst in isa.data
        if inst.operation.num_qubits == 2 and inst.operation.name not in NON_GATES
    ]
    assert two_q, "Bell state needs an entangling gate"
    for pair in two_q:
        assert pair in edges, f"2q gate on uncoupled qubits {pair}"


# ---- noisy simulation: the answer is right, and not perfect -------------------


def test_noisy_bell_is_close_to_ideal_but_not_perfect(seed):
    isa = _isa_bell(seed)
    noisy = get_noisy_simulator()
    counts = noisy.run(isa, shots=SHOTS, seed_simulator=seed).result().get_counts()

    assert sum(counts.values()) == SHOTS
    ideal = {"00": 0.5, "11": 0.5}
    fidelity = hellinger_fidelity(counts, ideal)
    assert 0.9 < fidelity < 1.0, f"noisy Bell fidelity {fidelity:.3f}, {counts}"

    # An ideal run never produces 01/10. Noise must leak some weight there; this
    # is what separates "noisy" from "ideal" more reliably than fidelity < 1,
    # which finite-shot sampling alone can cause.
    leaked = counts.get("01", 0) + counts.get("10", 0)
    assert leaked > 0, f"noisy simulator looks noiseless: {counts}"
    assert leaked / SHOTS < 0.2


def test_ideal_sim_never_leaks_on_the_same_circuit(seed):
    """Control for the test above: same transpiled circuit, noiseless backend."""
    isa = _isa_bell(seed)
    counts = (
        get_ideal_simulator().run(isa, shots=SHOTS, seed_simulator=seed).result().get_counts()
    )
    assert set(counts) == {"00", "11"}, counts


# ---- the real backend: failure path only, no network --------------------------


def test_missing_token_error_is_a_runtime_error():
    assert issubclass(MissingTokenError, RuntimeError)


def test_real_backend_without_token_raises(no_ibm_login):
    with pytest.raises(MissingTokenError):
        get_real_backend()


# ---- dispatcher ---------------------------------------------------------------


def test_get_backend_dispatches_by_kind():
    assert isinstance(get_backend("ideal"), AerSimulator)
    assert get_backend("ideal").options.noise_model is None
    assert get_backend("noisy").options.noise_model is not None


def test_get_backend_real_without_token_raises(no_ibm_login):
    with pytest.raises(MissingTokenError):
        get_backend("real")


@pytest.mark.parametrize("kind", ["", "fake", "IDEAL", "hardware"])
def test_get_backend_rejects_unknown_kind(kind):
    with pytest.raises(ValueError):
        get_backend(kind)
