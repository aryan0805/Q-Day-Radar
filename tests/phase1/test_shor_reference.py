"""Phase 1: Shor reference values and post-processing on known inputs.

These pin the *definitions* the brief uses, independent of builder's code.
"""

import math

import pytest

from tests.phase1.reference import (
    cf_denominators,
    factors_from_order,
    mult_order,
    qpe_outcome_probs,
    shor_theoretical_success,
)


@pytest.mark.parametrize(
    ("a", "n", "r"),
    [
        (7, 15, 4),
        (2, 15, 4),
        (11, 15, 2),
        (4, 15, 2),
        (13, 15, 4),
        (2, 21, 6),
        (4, 21, 3),
        (5, 21, 6),
    ],
)
def test_shor_known_orders(a, n, r):
    assert mult_order(a, n) == r


def test_shor_order_rejects_non_coprime():
    with pytest.raises(ValueError):
        mult_order(3, 15)


def test_shor_7_mod_15_factors_3_and_5():
    assert factors_from_order(7, 15, 4) == (3, 5)


def test_shor_odd_or_trivial_order_gives_no_factors():
    assert factors_from_order(4, 21, 3) is None  # odd order
    assert factors_from_order(14, 15, 2) is None  # a^(r/2) = -1 mod N


@pytest.mark.parametrize(
    ("y", "expected"),
    [(64, {1, 4}), (192, {1, 4}), (128, {1, 2}), (0, {1})],
)
def test_shor_continued_fractions_n15_t8(y, expected):
    # peaks of a=7, N=15 are at 0, 64, 128, 192 for t=8; 128 -> 1/2 gives only r/2
    assert set(cf_denominators(y, 8, 15)) == expected


def test_shor_qpe_distribution_normalized_and_exact_peak():
    p = qpe_outcome_probs(6, 0.25)
    assert math.isclose(p.sum(), 1.0, abs_tol=1e-9)
    assert math.isclose(p[16], 1.0, abs_tol=1e-9)  # 0.25 * 64 = 16 exactly


def test_shor_theoretical_n15_a7_is_one_half():
    # phases s/4 are exact for any t >= 2; only s = 1, 3 give denominator 4
    for t in (4, 6, 8):
        assert math.isclose(shor_theoretical_success(7, 15, t), 0.5, abs_tol=1e-9)


def test_shor_theoretical_n15_a11_is_one_half_of_orders():
    # r = 2: phases 0 and 1/2; only s=1 gives denominator 2
    assert math.isclose(shor_theoretical_success(11, 15, 8), 0.5, abs_tol=1e-9)


def test_shor_theoretical_n21_inexact_peaks_below_phi_over_r():
    # r = 6, phi(6)/6 = 1/3 is the ceiling; non-dyadic peaks leak a little
    p = shor_theoretical_success(2, 21, 8)
    assert 0.25 < p <= 1 / 3 + 1e-9
