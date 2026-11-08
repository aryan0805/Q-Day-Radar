"""Textbook Shor for N=15, a=7. Label: ``compiled``.

The controlled modular multiplications are the known hand-built permutations for a=7 mod 15,
so the circuit is specialised to this one instance (it uses the structure of 7 mod 15, not
the order or factors as inputs). It is NOT a generic Shor builder.

Why ``compiled``: the controlled multiplications are the hand-built permutations for 7 mod 15,
and the blocks for j >= 2 are dropped because 7**4 = 1 mod 15 (r divides 4). Both bake the
instance, and so the order, into the circuit.

Metrics note: ``depth`` and ``n_qubits`` in the metrics JSON are the logical circuit's;
``two_qubit_gates`` and ``transpile.depth`` are after transpiling for FakeKingston.

Layout: 8 counting qubits (qubit j controls U^(2^j)), 4 work qubits holding |1>.
Classical register ``phase``: clbit j = phase bit of weight 2**j.
"""

from __future__ import annotations

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit.library import QFTGate

N = 15
A = 7
N_COUNT = 8
N_WORK = 4


def _controlled_mult(qc: QuantumCircuit, control: int, work: list[int], power: int) -> None:
    """Controlled multiplication of the work register by 7**power mod 15 (power = 2**j)."""
    multiplier = pow(A, power, N)
    if multiplier == 1:
        return
    w = work
    if multiplier == 7:
        qc.cswap(control, w[0], w[1])
        qc.cswap(control, w[1], w[2])
        qc.cswap(control, w[2], w[3])
        for q in w:
            qc.cx(control, q)
    elif multiplier == 4:
        qc.cswap(control, w[0], w[2])
        qc.cswap(control, w[1], w[3])
    else:  # pragma: no cover - only 1, 7, 4 occur for a=7 mod 15
        raise ValueError(f"unexpected multiplier {multiplier}")


def build_shor15_textbook() -> QuantumCircuit:
    count = QuantumRegister(N_COUNT, "count")
    work = QuantumRegister(N_WORK, "work")
    phase = ClassicalRegister(N_COUNT, "phase")
    qc = QuantumCircuit(count, work, phase, name="shor15_textbook")
    qc.x(work[0])
    qc.h(count)
    work_idx = [N_COUNT + i for i in range(N_WORK)]
    for j in range(N_COUNT):
        _controlled_mult(qc, j, work_idx, 2**j)
    qc.append(QFTGate(N_COUNT).inverse(), count)
    qc.measure(count, phase)
    qc.metadata = {
        "name": "shor15_textbook",
        "kind": "compiled",
        "N": N,
        "a": A,
        "n_count": N_COUNT,
        "compiled_reason": "hand-built multiply-by-7 mod 15; blocks for j>=2 dropped "
        "because 7**4 = 1 mod 15",
    }
    return qc
