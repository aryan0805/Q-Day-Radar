"""Classical post-processing for Shor and Grover. Pure functions, no circuit imports.

``order_from_shot`` deliberately does NOT search for the order: it walks the continued-fraction
convergents of one measured phase and accepts the first denominator that works. A bad shot
therefore fails, which is what makes the success rate a real measurement.
"""

from __future__ import annotations

from fractions import Fraction
from math import gcd


def convergents(numerator: int, denominator: int) -> list[Fraction]:
    """Continued-fraction convergents of ``numerator / denominator`` (denominators increase)."""
    if denominator <= 0 or numerator < 0:
        raise ValueError("need numerator >= 0 and denominator > 0")
    terms: list[int] = []
    n, d = numerator, denominator
    while d:
        q = n // d
        terms.append(q)
        n, d = d, n - q * d
    result: list[Fraction] = []
    h_prev, h = 1, terms[0]
    k_prev, k = 0, 1
    result.append(Fraction(h, k))
    for q in terms[1:]:
        h_prev, h = h, q * h + h_prev
        k_prev, k = k, q * k + k_prev
        result.append(Fraction(h, k))
    return result


def order_from_shot(measured: int, n_count: int, a: int, N: int) -> int | None:
    """Order of ``a`` mod ``N`` from ONE shot, or None.

    Walks the convergents of ``measured / 2**n_count`` and returns the first denominator d with
    1 <= d < N and ``pow(a, d, N) == 1``. No scan over r, no multiples of d.
    """
    if measured == 0:
        return None
    for frac in convergents(measured, 2**n_count):
        d = frac.denominator
        if 1 <= d < N and pow(a, d, N) == 1:
            return d
    return None


def factors_from_order(a: int, r: int, N: int) -> tuple[int, int] | None:
    """Non-trivial factors (p, q), p <= q, from the order ``r`` of ``a``; None if it fails."""
    if r <= 0 or r % 2:
        return None
    x = pow(a, r // 2, N)
    if x == N - 1:
        return None
    p = gcd(x - 1, N)
    if p in (1, N):
        p = gcd(x + 1, N)
    if p in (1, N):
        return None
    return tuple(sorted((p, N // p)))  # type: ignore[return-value]


def classical_order(a: int, N: int) -> int:
    """Brute-force multiplicative order. For scoring and theory only, never inside a circuit."""
    if gcd(a, N) != 1:
        raise ValueError(f"a={a} is not coprime to N={N}")
    r, x = 1, a % N
    while x != 1:
        x = x * a % N
        r += 1
    return r


def consistent_keys(key_bits: int, pairs: list[tuple[int, int]]) -> list[int]:
    """All keys of ``key_bits`` bits that map every plaintext to its ciphertext (brute force)."""
    from quantum.classical.toy_spn import encrypt

    return [
        key
        for key in range(2**key_bits)
        if all(encrypt(pt, key, key_bits) == ct for pt, ct in pairs)
    ]


def grover_key_ok(key: int, key_bits: int, pairs: list[tuple[int, int]]) -> bool:
    """True if ``key`` is consistent with every (plaintext, ciphertext) pair."""
    from quantum.classical.toy_spn import encrypt

    return 0 <= key < 2**key_bits and all(encrypt(pt, key, key_bits) == ct for pt, ct in pairs)
