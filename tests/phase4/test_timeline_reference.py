"""The reference timeline model, checked against known answers before it is used to check builder.

Falsifying checks: a series with a known doubling time, a regression worked by hand in exact
fractions, a Student-t table value, a CI whose long end does not exist, and a holdout whose answer
is known. If the oracle were wrong, builder's code would be judged by a wrong ruler.
"""

from __future__ import annotations

import math

import pytest

from tests.phase4 import reference as ref


def test_timeline_student_t_matches_the_textbook_table():
    """t(0.975) for 3, 4, 10 dof: 3.182, 2.776, 2.228 (any statistics text)."""
    assert ref.t_crit(3) == pytest.approx(3.1824, abs=5e-4)
    assert ref.t_crit(4) == pytest.approx(2.7764, abs=5e-4)
    assert ref.t_crit(10) == pytest.approx(2.2281, abs=5e-4)


def test_timeline_ols_hand_computed_five_points():
    """x = 0..4, y = 0.1, 0.9, 2.1, 2.9, 4.1 worked in exact fractions: a = 1/50, b = 1,
    SSE = 6/125, SST = 1256/125, se_b = sqrt(SSE / 3 / Sxx) = sqrt(0.048/30) = 0.04."""
    f = ref.ols([0, 1, 2, 3, 4], [0.1, 0.9, 2.1, 2.9, 4.1])
    assert f["a"] == pytest.approx(0.02, abs=1e-12)
    assert f["b"] == pytest.approx(1.0, abs=1e-12)
    assert f["se_b"] == pytest.approx(0.04, abs=1e-12)
    assert f["r2"] == pytest.approx(1 - 6 / 1256, abs=1e-12)
    assert sum(f["residuals"]) == pytest.approx(0.0, abs=1e-12)


def test_timeline_ci_hand_computed_five_points():
    """Slope 1 +- 3.1824 * 0.04 = 1.1273 / 0.8727, so the doubling time is 1 year with the CI
    [1/1.1273, 1/0.8727] = [0.887, 1.146]."""
    pts = [(0, 2**0.1), (1, 2**0.9), (2, 2**2.1), (3, 2**2.9), (4, 2**4.1)]
    f = ref.doubling_fit(pts)
    assert f["doubling_years"] == pytest.approx(1.0, abs=1e-12)
    assert f["ci95"][0] == pytest.approx(0.8871, abs=5e-4)
    assert f["ci95"][1] == pytest.approx(1.1459, abs=5e-4)
    assert f["ci95"][0] < f["doubling_years"] < f["ci95"][1]


@pytest.mark.parametrize("doubling", [0.5, 1.0, 1.9, 4.0])
def test_timeline_recovers_a_known_doubling_time_from_noise_free_points(doubling):
    pts = [(2015 + i, 50 * 2 ** (i / doubling)) for i in range(8)]
    f = ref.doubling_fit(pts)
    assert f["doubling_years"] == pytest.approx(doubling, rel=1e-9)
    assert f["r2"] == pytest.approx(1.0, abs=1e-12)
    assert f["ci95"][0] == pytest.approx(doubling, rel=1e-6)  # no scatter: the CI collapses
    assert f["ci95"][1] == pytest.approx(doubling, rel=1e-6)


def test_timeline_recovers_a_known_doubling_time_from_deterministic_wiggle():
    """True doubling 1.5 y with +-8% wiggle: estimate close, and the CI contains the truth."""
    wiggle = [1.08, 0.93, 1.05, 0.95, 1.07, 0.92, 1.04, 0.96]
    pts = [(2016 + i, 50 * 2 ** (i / 1.5) * w) for i, w in enumerate(wiggle)]
    f = ref.doubling_fit(pts)
    assert abs(f["doubling_years"] - 1.5) / 1.5 < 0.05
    assert f["ci95"][0] <= 1.5 <= f["ci95"][1]


def test_timeline_ci_long_end_is_none_when_the_slope_could_be_zero():
    """Flat, noisy series: the CI on the slope includes 0, so the long end of the doubling time
    does not exist (the brief: null if the bound's slope <= 0)."""
    pts = [(2000, 2**1.0), (2001, 2**0.0), (2002, 2**1.0), (2003, 2**0.0), (2004, 2**0.9)]
    f = ref.doubling_fit(pts)
    assert f["b"] - f["t"] * f["se_b"] < 0, "fixture must straddle zero"
    assert f["ci95"][1] is None
    assert f["ci95"][0] is not None and f["ci95"][0] > 0


def test_timeline_holdout_is_exact_on_exact_data_and_wrong_on_a_break_in_trend():
    pts = [(2018 + i, 10 * 2**i) for i in range(7)]  # doubles yearly
    h = ref.holdout(pts)
    assert h["year"] == 2024 and h["actual"] == 10 * 2**6
    assert h["predicted"] == pytest.approx(h["actual"], rel=1e-9)
    assert h["rel_error"] == pytest.approx(0.0, abs=1e-9)
    # the latest point jumps 4x above trend: the holdout must see it (predicted too low)
    broken = [*pts[:-1], (2024, 10 * 2**6 * 4)]
    hb = ref.holdout(broken)
    assert hb["rel_error"] == pytest.approx(-0.75, abs=1e-9)  # (1 - 4)/4


def test_timeline_holdout_uses_only_the_earlier_points():
    """Changing the held-out point must not change the fit that predicts it."""
    base = [(2018 + i, 10 * 2**i) for i in range(6)]
    a = ref.holdout([*base, (2024, 640)])
    b = ref.holdout([*base, (2024, 99999)])
    assert a["predicted"] == pytest.approx(b["predicted"], rel=1e-12)


def test_timeline_crqc_year_hand_computed():
    """Baseline 1,000 qubits, doubling every 2 y, attack needs 8,000 -> 3 doublings -> +6 years."""
    assert ref.crqc_year(2026, 2.0, 8000, 3600, 1000) == pytest.approx(2032.0, abs=1e-12)
    # already enough qubits: never earlier than as_of
    assert ref.crqc_year(2026, 2.0, 500, 3600, 1000) == 2026
    # a runtime above the one-year cap makes the target infeasible
    assert ref.crqc_year(2026, 2.0, 8000, 400 * 86400, 1000) is None
    assert math.isclose(ref.SECONDS_PER_YEAR, 31557600.0)
