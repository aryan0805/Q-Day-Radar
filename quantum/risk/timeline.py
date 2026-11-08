"""Hardware timeline fit and CRQC years, exactly as fixed in the Phase 4 brief.

log2(qubits) = a + b*year by OLS; doubling_years = 1/b; 95% CI on the doubling time =
[1/(b + t*se_b), 1/(b - t*se_b)] with Student t on n-2 dof (upper bound None if its slope <= 0).
crqc_year = as_of_year + doubling_years * max(0, log2(P / baseline)) if the runtime is within the
cap, else None. Qubit COUNT only: the timeline says nothing about qubit quality.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from scipy import stats

SECONDS_PER_YEAR = 365.25 * 86400
UNIT_SECONDS = {
    "second": 1.0,
    "seconds": 1.0,
    "s": 1.0,
    "minute": 60.0,
    "minutes": 60.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "day": 86400.0,
    "days": 86400.0,
}


def _ols(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float, float, float]:
    """slope, intercept, standard error of the slope, residual sum of squares."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    a = my - b * mx
    ssr = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys, strict=True))
    se = math.sqrt(ssr / (n - 2) / sxx) if n > 2 else float("nan")
    return b, a, se, ssr


def fit_timeline(years: Sequence[int], qubits: Sequence[float]) -> dict:
    if len(years) < 3:
        raise ValueError("timeline fit needs at least 3 points")
    ly = [math.log2(q) for q in qubits]
    b, a, se, ssr = _ols(years, ly)
    n = len(years)
    t = stats.t.ppf(0.975, n - 2)
    my = sum(ly) / n
    sst = sum((y - my) ** 2 for y in ly)
    hi = 1 / (b - t * se) if b - t * se > 0 else None
    return {
        "slope": b,
        "intercept": a,
        "doubling_years": 1 / b,
        "ci95": [1 / (b + t * se), hi],
        "r2": 1 - ssr / sst if sst else 1.0,
        "residuals": [
            {"year": int(x), "rel": (q - 2 ** (a + b * x)) / q}
            for x, q in zip(years, qubits, strict=True)
        ],
    }


def predict(fit: dict, year: float) -> float:
    return 2 ** (fit["intercept"] + fit["slope"] * year)


def holdout(years: Sequence[int], qubits: Sequence[float]) -> dict:
    """Fit without the latest point, predict it."""
    order = sorted(range(len(years)), key=lambda i: (years[i], qubits[i]))
    train, last = order[:-1], order[-1]
    fit = fit_timeline([years[i] for i in train], [qubits[i] for i in train])
    predicted = predict(fit, years[last])
    actual = float(qubits[last])
    return {
        "year": int(years[last]),
        "predicted": predicted,
        "actual": actual,
        "rel_error": abs(predicted - actual) / actual,
        "signed_rel_error": (predicted - actual) / actual,
    }


def frontier(points: Sequence[dict]) -> list[dict]:
    """Record so far: for each year, the largest device announced up to and including that year."""
    out: list[dict] = []
    best = 0
    for p in sorted(points, key=lambda p: (p["year"], p["qubits"])):
        best = max(best, p["qubits"])
        if out and out[-1]["year"] == p["year"]:
            out[-1] = {"year": p["year"], "qubits": best}
        else:
            out.append({"year": p["year"], "qubits": best})
    return out


def crqc_year(
    physical_qubits: float,
    runtime_seconds: float,
    baseline_qubits: float,
    doubling_years: float | None,
    as_of_year: int,
    runtime_cap_years: float,
) -> float | None:
    if runtime_seconds / SECONDS_PER_YEAR > runtime_cap_years or not doubling_years:
        return None
    return as_of_year + doubling_years * max(0.0, math.log2(physical_qubits / baseline_qubits))
