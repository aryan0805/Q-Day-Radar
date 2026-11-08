"""The reference statistics against textbook values and SciPy / Qiskit (not builder's code)."""

import math

import pytest
from qiskit.quantum_info import hellinger_fidelity as qiskit_hellinger
from scipy.stats import binomtest

from tests.phase2.reference import hellinger_fidelity, normalized, to_probs, wilson


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [
        (50, 100, 0.40383, 0.59617),
        (1, 10, 0.017876, 0.404150),
        (0, 10, 0.0, 0.27753),
        (10, 10, 0.72247, 1.0),
        (4096, 8192, 0.48917, 0.51083),
    ],
)
def test_wilson_reference_known_values(k, n, lo, hi):
    got = wilson(k, n)
    assert math.isclose(got[0], lo, abs_tol=2e-5) and math.isclose(got[1], hi, abs_tol=2e-5)


@pytest.mark.parametrize(("k", "n"), [(0, 50), (3, 50), (25, 50), (49, 50), (50, 50), (1700, 8192)])
def test_wilson_reference_matches_scipy(k, n):
    ci = binomtest(k, n).proportion_ci(confidence_level=0.95, method="wilson")
    lo, hi = wilson(k, n)
    assert math.isclose(lo, ci.low, abs_tol=1e-9) and math.isclose(hi, ci.high, abs_tol=1e-9)


def test_wilson_interval_contains_the_estimate_and_is_inside_the_unit_interval():
    for n in (1, 2, 10, 4096):
        for k in range(0, min(n, 20) + 1):
            lo, hi = wilson(k, n)
            assert -1e-12 <= lo <= k / n + 1e-12 and k / n - 1e-12 <= hi <= 1 + 1e-12


def test_normalized_score_anchor_points():
    assert normalized(0.172, 0.5, 0.172) == 0.0  # at chance
    assert normalized(0.5, 0.5, 0.172) == 1.0  # at the noiseless prediction
    assert math.isclose(normalized(0.336, 0.5, 0.172), 0.5)
    assert normalized(0.1, 0.5, 0.172) < 0  # below chance is negative, not clipped
    with pytest.raises(ValueError):
        normalized(0.3, 0.2, 0.2)


def test_hellinger_fidelity_anchor_points():
    assert hellinger_fidelity({"0": 1.0}, {"0": 1.0}) == 1.0
    assert hellinger_fidelity({"0": 1.0}, {"1": 1.0}) == 0.0
    assert math.isclose(hellinger_fidelity({"0": 0.5, "1": 0.5}, {"0": 1.0}), 0.5)
    assert math.isclose(
        hellinger_fidelity({"00": 0.5, "11": 0.5}, {"00": 0.25, "01": 0.25, "11": 0.5}),
        (math.sqrt(0.125) + math.sqrt(0.25)) ** 2,
    )


def test_hellinger_fidelity_is_symmetric_and_normalises_counts():
    a, b = {"0": 30, "1": 70}, {"0": 5, "1": 3, "2": 2}
    assert math.isclose(
        hellinger_fidelity(to_probs(a), to_probs(b)), hellinger_fidelity(to_probs(b), to_probs(a))
    )
    assert math.isclose(hellinger_fidelity(a, b), hellinger_fidelity(to_probs(a), to_probs(b)))


def test_hellinger_reference_matches_qiskit():
    a, b = {"00": 4000, "01": 120, "10": 80, "11": 3992}, {"00": 3900, "11": 4100, "10": 192}
    assert math.isclose(
        hellinger_fidelity(to_probs(a), to_probs(b)), qiskit_hellinger(a, b), abs_tol=1e-12
    )
