"""Noisy simulation of the Phase 1 circuits on FakeKingston's noise model."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator

from quantum.backends import get_fake_backend
from quantum.classical.postprocess import classical_order
from quantum.classical.theory import qpe_probabilities
from quantum.run.stats import has_signal, hellinger_fidelity, normalized_score, wilson_interval

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "results" / "noisy"


def ideal_distribution(name: str, circuit: QuantumCircuit | None = None) -> dict[str, float]:
    """Exact ideal outcome probabilities over the scored register (not sampled)."""
    from quantum.circuits.registry import SHOR_CASES, build_circuit

    if name in SHOR_CASES:
        case = SHOR_CASES[name]
        probs = qpe_probabilities(case.n_count, classical_order(case.a, case.N))
        return {format(m, f"0{case.n_count}b"): p for m, p in enumerate(probs) if p > 1e-15}
    circuit = circuit if circuit is not None else build_circuit(name)
    key_bits = circuit.metadata["key_bits"]
    bare = circuit.remove_final_measurements(inplace=False)
    probs = Statevector.from_instruction(bare).probabilities(list(range(key_bits)))
    return {format(i, f"0{key_bits}b"): float(p) for i, p in enumerate(probs) if p > 1e-15}


def run_noisy(
    name: str,
    circuit: QuantumCircuit,
    *,
    shots: int = 8192,
    seed_simulator: int = 1234,
    seed_transpiler: int = 1234,
    optimization_level: int = 3,
    out_dir: Path = DEFAULT_OUT_DIR,
    reduced_reason: str | None = None,
) -> dict:
    """Run ``circuit`` with FakeKingston noise and write ``<out_dir>/<name>.json``."""
    from quantum.circuits.registry import SUCCESS_FN
    from quantum.metrics import success_probability

    if shots < 1024:
        raise ValueError("shots must be >= 1024 even with a reduced_reason")
    if shots < 8192 and not reduced_reason:
        raise ValueError("shots must be >= 8192 (or pass reduced_reason to explain why not)")
    device = get_fake_backend()
    pm = generate_preset_pass_manager(
        optimization_level=optimization_level, backend=device, seed_transpiler=seed_transpiler
    )
    isa = pm.run(circuit)
    sim = AerSimulator.from_backend(device, shot_branching_enable=True)
    counts = sim.run(isa, shots=shots, seed_simulator=seed_simulator).result().get_counts()

    check = SUCCESS_FN[name]
    hits = sum(n for bits, n in counts.items() if check(bits))
    success = success_probability(name, counts)
    lo, hi = wilson_interval(hits, shots)
    theory = circuit.metadata["theoretical_success"]
    chance = circuit.metadata["chance_baseline"]
    record = {
        "name": name,
        "kind": circuit.metadata["kind"],
        "noise_model": "fake_kingston",
        "shots": shots,
        "seed_simulator": seed_simulator,
        "seed_transpiler": seed_transpiler,
        "optimization_level": optimization_level,
        "success_probability": success,
        "wilson_95": [lo, hi],
        "theoretical_success": theory,
        "chance_baseline": chance,
        "normalized_score": normalized_score(success, theory, chance),
        "hellinger_vs_ideal": hellinger_fidelity(counts, ideal_distribution(name, circuit)),
        "signal": has_signal(lo, chance),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if reduced_reason:
        record["reduced_shots_reason"] = reduced_reason
        record["prediction"] = "at chance" if lo <= chance else "signal"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
    return record
