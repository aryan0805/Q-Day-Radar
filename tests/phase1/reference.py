"""Independent reference values for Phase 1. Owned by reviewer.

Nothing here imports from ``quantum``. Every number a circuit claims as
``theoretical_success`` is recomputed from these closed forms, never by
simulating the circuit under test.
"""

from __future__ import annotations

import math

import numpy as np


def mult_order(a: int, n: int) -> int:
    """Smallest r > 0 with a**r = 1 (mod n), by brute force."""
    if math.gcd(a, n) != 1:
        raise ValueError("a must be coprime to n")
    x, r = a % n, 1
    while x != 1:
        x = (x * a) % n
        r += 1
    return r


def cf_denominators(y: int, t: int, n: int) -> list[int]:
    """Denominators < n of the continued-fraction convergents of y / 2**t."""
    num, den = y, 2**t
    dens, (h0, h1), (k0, k1) = [], (0, 1), (1, 0)
    while den:
        q, (num, den) = num // den, (den, num % den)
        h0, h1 = h1, q * h1 + h0
        k0, k1 = k1, q * k1 + k0
        if 0 < k1 < n:
            dens.append(k1)
    return dens


def qpe_outcome_probs(t: int, phase: float) -> np.ndarray:
    """P(y) for t-bit phase estimation of an exact eigenphase ``phase`` (Fejer kernel)."""
    size = 2**t
    delta = phase - np.arange(size) / size
    with np.errstate(divide="ignore", invalid="ignore"):
        k = np.sin(np.pi * size * delta) / (size * np.sin(np.pi * delta))
    # delta an integer -> the kernel is exactly 1
    k = np.where(np.isclose(np.sin(np.pi * delta), 0.0, atol=1e-12), 1.0, k)
    return k**2


def shor_theoretical_success(a: int, n: int, t: int) -> float:
    """P(r = ord(a mod n) is a convergent denominator of the shot, denominators < n).

    Input is |1>, an equal superposition of the r eigenstates, so the outcome
    distribution is the average of the QPE distributions at phases s/r.
    """
    r = mult_order(a, n)
    probs = sum(qpe_outcome_probs(t, s / r) for s in range(r)) / r
    assert math.isclose(probs.sum(), 1.0, abs_tol=1e-9)
    good = np.array([r in cf_denominators(y, t, n) for y in range(2**t)])
    return float(probs[good].sum())


def factors_from_order(a: int, n: int, r: int) -> tuple[int, int] | None:
    """Nontrivial factors of n from even order r, or None."""
    if r % 2:
        return None
    half = pow(a, r // 2, n)
    if half == n - 1:
        return None
    p, q = math.gcd(half - 1, n), math.gcd(half + 1, n)
    if 1 < p < n and 1 < q < n:
        return tuple(sorted((p, q)))  # type: ignore[return-value]
    return None


def grover_success(m: int, space: int, iterations: int) -> float:
    """sin^2((2j+1) theta), sin^2 theta = M / 2**k, for M marked items out of ``space``."""
    theta = math.asin(math.sqrt(m / space))
    return math.sin((2 * iterations + 1) * theta) ** 2


def shor_chance_baseline(a: int, n: int, t: int) -> float:
    """P(success) if all 2**t outcomes were equally likely (what a fully dephased run scores)."""
    r = mult_order(a, n)
    return sum(r in cf_denominators(y, t, n) for y in range(2**t)) / 2**t


def grover_chance_baseline(m: int, key_bits: int) -> float:
    """P(success) for a uniformly random key guess: M / 2**k."""
    return m / 2**key_bits
