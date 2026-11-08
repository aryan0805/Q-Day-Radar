"""Analytic theoretical-success formulas. Never simulates a circuit."""

from __future__ import annotations

import math

from quantum.classical.postprocess import classical_order, order_from_shot


def qpe_probabilities(n_count: int, r: int) -> list[float]:
    """P(measured = m) for phase estimation of ``a`` mod N from the start state |1>.

    |1> is a uniform superposition of the r eigenstates with phases s/r, so
    P(m) = (1/r) * sum_s |sin(pi*(2^n*x - 2^n*s/r)) / (2^n sin(pi*(x - s/r)))|^2 with x = m/2^n.
    """
    big = 2**n_count
    probs = []
    for m in range(big):
        total = 0.0
        for s in range(r):
            delta = m / big - s / r
            denom = big * math.sin(math.pi * delta)
            if abs(denom) < 1e-12:
                total += 1.0
            else:
                total += (math.sin(math.pi * big * delta) / denom) ** 2
        probs.append(total / r)
    return probs


def shor_theoretical_success(N: int, a: int, n_count: int) -> float:
    """P(one shot -> order_from_shot == true order), from the analytic QPE distribution."""
    r = classical_order(a, N)
    probs = qpe_probabilities(n_count, r)
    return float(sum(p for m, p in enumerate(probs) if order_from_shot(m, n_count, a, N) == r))


def grover_theoretical_success(key_bits: int, n_consistent: int, iterations: int) -> float:
    """sin^2((2j+1) theta), theta = asin(sqrt(M / 2^k)), M from classical brute force."""
    theta = math.asin(math.sqrt(n_consistent / 2**key_bits))
    return float(math.sin((2 * iterations + 1) * theta) ** 2)


def shor_chance_baseline(N: int, a: int, n_count: int) -> float:
    """Fraction of all 2**n_count outcomes that post-process to the true order (uniform guess)."""
    r = classical_order(a, N)
    hits = sum(order_from_shot(m, n_count, a, N) == r for m in range(2**n_count))
    return hits / 2**n_count


def grover_chance_baseline(key_bits: int, n_consistent: int) -> float:
    """Probability that a uniformly random key is consistent: M / 2**k."""
    return n_consistent / 2**key_bits
