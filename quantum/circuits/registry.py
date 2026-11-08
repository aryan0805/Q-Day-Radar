"""Registry of every Phase 1 circuit, plus how each one is scored.

Success and theoretical success live HERE, not in the builders, so no builder ever calls
``classical_order`` or reads a key. Each Shor circuit has one classical register ``phase`` of
``n_count`` bits, where clbit j holds the phase bit of weight 2**j (standard QPE reading,
``int(bitstring, 2)``). Each Grover circuit has one classical register ``key`` of ``key_bits``
bits, with key bit i in clbit i (``int(bitstring, 2)`` is the key).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from qiskit import QuantumCircuit

from quantum.classical.postprocess import (
    classical_order,
    consistent_keys,
    grover_key_ok,
    order_from_shot,
)
from quantum.classical.theory import (
    grover_chance_baseline,
    grover_theoretical_success,
    shor_chance_baseline,
    shor_theoretical_success,
)
from quantum.classical.toy_spn import encrypt

GROVER_KEYS = (2, 3, 4, 5)
# Demo plaintexts; ciphertexts are generated with a demo key held only here (never in a circuit).
# OPTIMIZE r1: two pairs already fix the key for k <= 4 (M = 1 for every key); k = 5 needs three.
GROVER_PLAINTEXTS = {2: (0x1, 0x6), 3: (0x1, 0x6), 4: (0x1, 0x6), 5: (0x1, 0x6, 0xB)}
GROVER_DEMO_KEYS = {2: 0b10, 3: 0b101, 4: 0b1011, 5: 0b10110}


@dataclass(frozen=True)
class ShorCase:
    N: int
    a: int
    n_count: int


SHOR_CASES = {
    "shor15_textbook": ShorCase(15, 7, 8),
    "shor15_beauregard": ShorCase(15, 7, 8),
    "shor21_beauregard": ShorCase(21, 2, 10),
}


def grover_pairs(key_bits: int) -> list[tuple[int, int]]:
    key = GROVER_DEMO_KEYS[key_bits]
    return [(pt, encrypt(pt, key, key_bits)) for pt in GROVER_PLAINTEXTS[key_bits]]


def _shor_success_fn(case: ShorCase) -> Callable[[str], bool]:
    r = classical_order(case.a, case.N)

    def check(bits: str) -> bool:
        return order_from_shot(int(bits.replace(" ", ""), 2), case.n_count, case.a, case.N) == r

    return check


def _grover_success_fn(key_bits: int) -> Callable[[str], bool]:
    pairs = grover_pairs(key_bits)

    def check(bits: str) -> bool:
        return grover_key_ok(int(bits.replace(" ", ""), 2), key_bits, pairs)

    return check


def _grover_theory(key_bits: int) -> float:
    from quantum.circuits.grover_present import default_iterations

    m = len(consistent_keys(key_bits, grover_pairs(key_bits)))
    return grover_theoretical_success(key_bits, m, default_iterations(key_bits))


SUCCESS_FN: dict[str, Callable[[str], bool]] = {
    **{name: _shor_success_fn(case) for name, case in SHOR_CASES.items()},
    **{f"grover_present_k{k}": _grover_success_fn(k) for k in GROVER_KEYS},
}

THEORY_FN: dict[str, Callable[[], float]] = {
    **{
        name: (lambda c=case: shor_theoretical_success(c.N, c.a, c.n_count))
        for name, case in SHOR_CASES.items()
    },
    **{f"grover_present_k{k}": (lambda k=k: _grover_theory(k)) for k in GROVER_KEYS},
}

CHANCE_FN: dict[str, Callable[[], float]] = {
    **{
        name: (lambda c=case: shor_chance_baseline(c.N, c.a, c.n_count))
        for name, case in SHOR_CASES.items()
    },
    **{
        f"grover_present_k{k}": (
            lambda k=k: grover_chance_baseline(k, len(consistent_keys(k, grover_pairs(k))))
        )
        for k in GROVER_KEYS
    },
}

REQUIRED_NAMES = tuple(SUCCESS_FN)


def _build(name: str) -> QuantumCircuit:
    if name == "shor15_textbook":
        from quantum.circuits.shor_textbook import build_shor15_textbook

        return build_shor15_textbook()
    if name.endswith("_beauregard"):
        from quantum.circuits.beauregard import build_shor

        case = SHOR_CASES[name]
        return build_shor(case.N, case.a)
    from quantum.circuits.grover_present import build_grover

    key_bits = int(name.rsplit("_k", 1)[1])
    return build_grover(key_bits, grover_pairs(key_bits))


def _check_metadata(name: str, meta: dict) -> None:
    """Fail loudly if the scoring constants here disagree with what the builder produced."""
    if name in SHOR_CASES:
        case = SHOR_CASES[name]
        got = (meta["N"], meta["a"], meta["n_count"])
        if got != (case.N, case.a, case.n_count):
            raise ValueError(f"{name}: builder metadata {got} != registry {case}")
        return
    from quantum.circuits.grover_present import default_iterations

    key_bits = int(name.rsplit("_k", 1)[1])
    if meta["key_bits"] != key_bits or meta["iterations"] != default_iterations(key_bits):
        raise ValueError(f"{name}: builder metadata disagrees with registry scoring constants")
    if [tuple(p) for p in meta["pairs"]] != grover_pairs(key_bits):
        raise ValueError(f"{name}: builder pairs differ from registry pairs")


def build_circuit(name: str) -> QuantumCircuit:
    """Build one registry circuit and attach its analytic ``theoretical_success``."""
    qc = _build(name)
    _check_metadata(name, qc.metadata)
    qc.metadata = {
        **qc.metadata,
        "name": name,
        "theoretical_success": THEORY_FN[name](),
        "chance_baseline": CHANCE_FN[name](),
    }
    qc.name = name
    return qc


def build_all() -> dict[str, QuantumCircuit]:
    """All required circuits keyed by name."""
    return {name: build_circuit(name) for name in REQUIRED_NAMES}
