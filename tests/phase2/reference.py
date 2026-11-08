"""Independent statistics for Phase 2 (nothing imports from quantum/).

Wilson score interval, normalized score and Hellinger fidelity, written from their textbook
definitions so builder's quantum/run/stats.py is checked against something it did not produce.
"""

from __future__ import annotations

import math

Z95 = 1.959963984540054  # two-sided 95% normal quantile


def wilson(successes: float, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, clipped to [0, 1]."""
    if n <= 0:
        raise ValueError("n must be positive")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def normalized(success: float, theory: float, chance: float) -> float:
    """(success - chance) / (theory - chance): 0 = chance, 1 = the noiseless prediction."""
    if theory == chance:
        raise ValueError("theory equals chance: the score is undefined")
    return (success - chance) / (theory - chance)


def hellinger_fidelity(p: dict[str, float], q: dict[str, float]) -> float:
    """(sum_x sqrt(p(x) q(x)))**2 for normalised distributions; 1 = identical, 0 = disjoint."""
    sp, sq = sum(p.values()), sum(q.values())
    bc = sum(math.sqrt(p[x] / sp * q[x] / sq) for x in p.keys() & q.keys())
    return bc * bc


def to_probs(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    return {k: v / total for k, v in counts.items()}
