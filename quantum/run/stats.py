"""Small, pure statistics helpers for comparing measured counts with theory."""

from __future__ import annotations

import math
from collections.abc import Mapping

WILSON_Z_95 = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = WILSON_Z_95) -> tuple[float, float]:
    """Wilson score interval for ``successes`` out of ``n``, clipped to [0, 1]."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= successes <= n:
        raise ValueError("successes must be in [0, n]")
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def normalized_score(success: float, theory: float, chance: float) -> float:
    """(success - chance) / (theory - chance); 0 = chance, 1 = theory. Not clipped."""
    if theory == chance:
        raise ValueError("theory equals chance: normalized score is undefined")
    return (success - chance) / (theory - chance)


def hellinger_fidelity(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    """Hellinger fidelity (sum sqrt(p_i q_i))^2: 1 = identical, 0 = disjoint."""
    tp, tq = sum(p.values()), sum(q.values())
    if tp <= 0 or tq <= 0:
        raise ValueError("distributions must have positive total weight")
    overlap = sum(math.sqrt(v / tp * q[k] / tq) for k, v in p.items() if k in q)
    return min(1.0, overlap * overlap)


def has_signal(wilson_lo: float, chance: float) -> bool:
    """True when the lower Wilson bound is strictly above the chance baseline."""
    return wilson_lo > chance
