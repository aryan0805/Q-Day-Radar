"""Phase 1: post-processing must come from the shot, never from knowing the order.

Rule (lead's P1 decision, builder's interface): walk the continued-fraction
convergents of measured / 2**n_count and return the first denominator d with
1 <= d < N and pow(a, d, N) == 1, else None. It never brute-forces r.
"""

import pytest

from tests.phase1.reference import cf_denominators, mult_order

postprocess = pytest.importorskip("quantum.classical.postprocess")

CASES = [(7, 15, 3), (7, 15, 8), (2, 15, 8), (11, 15, 6), (2, 21, 8), (5, 21, 9)]


def test_leak_postprocess_wrong_shot_is_not_rescued():
    # phase 4/8 = 1/2 -> denominator 2, and 7**2 = 4 (mod 15) != 1: must be None, not 4
    assert postprocess.order_from_shot(4, 3, 7, 15) is None


def test_leak_postprocess_zero_shot_gives_none():
    for a, n, t in CASES:
        assert postprocess.order_from_shot(0, t, a, n) is None


@pytest.mark.parametrize(("a", "n", "t"), CASES)
def test_leak_postprocess_matches_independent_rule_on_every_shot(a, n, t):
    r = mult_order(a, n)
    for y in range(2**t):
        got = postprocess.order_from_shot(y, t, a, n)
        hit = r in cf_denominators(y, t, n)
        assert (got == r) == hit, f"shot {y}"
        assert got is None or got % r == 0, f"shot {y} returned non-order {got}"


@pytest.mark.parametrize(("a", "n", "t"), CASES)
def test_leak_postprocess_does_not_answer_every_shot(a, n, t):
    answered = sum(postprocess.order_from_shot(y, t, a, n) is not None for y in range(2**t))
    assert 0 < answered < 2**t


def test_shor_postprocess_7_mod_15_gives_order_4_and_factors_3_5():
    r = postprocess.order_from_shot(64, 8, 7, 15)
    assert r == 4
    assert postprocess.factors_from_order(7, r, 15) == (3, 5)


def test_shor_postprocess_factors_none_for_odd_or_minus_one():
    assert postprocess.factors_from_order(4, 3, 21) is None
    assert postprocess.factors_from_order(14, 2, 15) is None


def test_shor_classical_order_matches_reference():
    for a, n in [(7, 15), (2, 15), (11, 15), (2, 21), (5, 21)]:
        assert postprocess.classical_order(a, n) == mult_order(a, n)
