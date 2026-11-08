"""quantum/run/stats.py against the independent reference in tests/phase2/reference.py."""

import itertools
import math

import pytest

from quantum.run import stats
from tests.phase2 import reference as ref

GRID_N = [1, 2, 7, 100, 4096, 8192]


@pytest.mark.parametrize("n", GRID_N)
def test_stats_wilson_matches_reference_on_a_grid(n):
    for k in sorted({0, 1, n // 3, n // 2, n - 1, n}):
        got, want = stats.wilson_interval(k, n), ref.wilson(k, n)
        assert math.isclose(got[0], want[0], abs_tol=1e-12), (k, n)
        assert math.isclose(got[1], want[1], abs_tol=1e-12), (k, n)


def test_stats_wilson_z_default_is_the_95_percent_quantile():
    assert math.isclose(stats.WILSON_Z_95, ref.Z95, rel_tol=1e-12)
    wide = stats.wilson_interval(30, 100, z=2.5758293035489)  # 99%
    narrow = stats.wilson_interval(30, 100)
    assert wide[0] < narrow[0] and wide[1] > narrow[1]


def test_stats_wilson_rejects_bad_input():
    for k, n in [(0, 0), (1, 0), (-1, 10), (11, 10)]:
        with pytest.raises(ValueError):
            stats.wilson_interval(k, n)


def test_stats_wilson_known_values():
    lo, hi = stats.wilson_interval(1, 10)
    assert math.isclose(lo, 0.017876, abs_tol=1e-6) and math.isclose(hi, 0.404150, abs_tol=1e-6)
    lo, hi = stats.wilson_interval(0, 10)
    assert lo == 0.0 and math.isclose(hi, 0.27753, abs_tol=1e-5)


@pytest.mark.parametrize(
    ("s", "t", "c"), [(0.172, 0.5, 0.172), (0.5, 0.5, 0.172), (0.336, 0.5, 0.172), (0.1, 0.5, 0.2)]
)
def test_stats_normalized_score_matches_reference(s, t, c):
    assert math.isclose(stats.normalized_score(s, t, c), ref.normalized(s, t, c), abs_tol=1e-12)


def test_stats_normalized_score_is_not_clipped_and_rejects_theory_equal_chance():
    assert stats.normalized_score(0.1, 0.5, 0.2) < 0
    assert stats.normalized_score(0.9, 0.5, 0.2) > 1
    with pytest.raises(ValueError):
        stats.normalized_score(0.3, 0.25, 0.25)


CASES = [
    ({"0": 1.0}, {"0": 1.0}),
    ({"0": 1.0}, {"1": 1.0}),
    ({"0": 0.5, "1": 0.5}, {"0": 1.0}),
    ({"00": 4000, "01": 120, "10": 80, "11": 3992}, {"00": 3900, "11": 4100, "10": 192}),
    ({"a": 3, "b": 1}, {"a": 1, "b": 3, "c": 10}),
]


@pytest.mark.parametrize(("p", "q"), CASES)
def test_stats_hellinger_matches_reference_and_is_in_unit_interval(p, q):
    got = stats.hellinger_fidelity(p, q)
    assert math.isclose(got, ref.hellinger_fidelity(p, q), abs_tol=1e-12)
    assert 0.0 <= got <= 1.0
    assert math.isclose(got, stats.hellinger_fidelity(q, p), abs_tol=1e-12)  # symmetric


def test_stats_hellinger_normalises_counts_and_probabilities_alike():
    counts = {"0": 300, "1": 700}
    probs = {"0": 0.3, "1": 0.7}
    other = {"0": 0.6, "1": 0.4}
    assert math.isclose(
        stats.hellinger_fidelity(counts, other), stats.hellinger_fidelity(probs, other)
    )
    assert stats.hellinger_fidelity(counts, counts) == pytest.approx(1.0)


def test_stats_hellinger_rejects_empty_distributions():
    with pytest.raises(ValueError):
        stats.hellinger_fidelity({}, {"0": 1})


def test_stats_has_signal_is_strict():
    assert stats.has_signal(0.1720001, 0.172)
    assert not stats.has_signal(0.172, 0.172)
    assert not stats.has_signal(0.1, 0.172)


def test_stats_signal_rule_follows_the_wilson_lower_bound_for_all_small_counts():
    chance, n = 0.25, 200
    for k in range(0, n + 1, 5):
        lo, _ = stats.wilson_interval(k, n)
        assert stats.has_signal(lo, chance) is (ref.wilson(k, n)[0] > chance)
    # monotone: more hits can only turn the signal on, never off
    flags = [stats.has_signal(stats.wilson_interval(k, n)[0], chance) for k in range(n + 1)]
    assert flags == sorted(flags)
    assert not flags[0] and flags[-1]
    assert list(itertools.groupby(flags))[0][0] is False
