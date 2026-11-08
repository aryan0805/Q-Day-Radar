"""Metrics recorder: run on the ideal simulator, transpile for FakeKingston, write JSON."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import qiskit
from qiskit import QuantumCircuit, transpile
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator

from quantum.backends import get_fake_backend

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "results" / "metrics"


def success_probability(name: str, counts: dict[str, int]) -> float:
    """Fraction of shots whose classical post-processing gives the right answer."""
    from quantum.circuits.registry import SUCCESS_FN

    check = SUCCESS_FN[name]
    total = sum(counts.values())
    return sum(n for bits, n in counts.items() if check(bits)) / total


def record_circuit_metrics(
    name: str,
    circuit: QuantumCircuit,
    *,
    shots: int = 8192,
    seed_simulator: int = 1234,
    seed_transpiler: int = 1234,
    optimization_level: int = 3,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict:
    """Measure ``circuit`` and write ``<out_dir>/<name>.json``; returns the record."""
    if shots < 8192:
        raise ValueError("shots must be >= 8192")
    # Shot branching: same counts as plain Aer, but mid-circuit measures cost one pass.
    ideal = AerSimulator(shot_branching_enable=True)
    sim_circuit = transpile(circuit, ideal, optimization_level=0)
    job = ideal.run(sim_circuit, shots=shots, seed_simulator=seed_simulator)
    counts = job.result().get_counts()

    pm = generate_preset_pass_manager(
        optimization_level=optimization_level,
        backend=get_fake_backend(),
        seed_transpiler=seed_transpiler,
    )
    tqc = pm.run(circuit)
    record = {
        "name": name,
        "kind": circuit.metadata["kind"],
        "n_qubits": circuit.num_qubits,
        "depth": circuit.depth(),
        "two_qubit_gates": tqc.num_nonlocal_gates(),
        "transpile": {
            "backend": "fake_kingston",
            "optimization_level": optimization_level,
            "seed_transpiler": seed_transpiler,
            "depth": tqc.depth(),
        },
        "success_probability": success_probability(name, counts),
        "theoretical_success": circuit.metadata["theoretical_success"],
        "chance_baseline": circuit.metadata["chance_baseline"],
        "shots": shots,
        "seed_simulator": seed_simulator,
        "qiskit_version": qiskit.__version__,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
    return record
