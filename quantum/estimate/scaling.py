"""Least-squares fits for the scaling study: power law (log-log) and linear, with holdout."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np

FitFn = Callable[[Sequence[float], Sequence[float]], dict]


def predict(fit: dict, x: float) -> float:
    p = fit["params"]
    if "coeffs" in p:
        return float(np.polyval(p["coeffs"], x))
    if "exponent" in p:
        return float(p["c"] * x ** p["exponent"])
    return float(p["slope"] * x + p["intercept"])


def _r2(actual: np.ndarray, fitted: np.ndarray) -> float:
    ss_res = float(np.sum((actual - fitted) ** 2))
    ss_tot = float(np.sum((actual - actual.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot else 1.0


def fit_power_law(xs: Sequence[float], ys: Sequence[float]) -> dict:
    """y = c * x**k by least squares on (log x, log y). r2 is the log-space r2.

    Residuals are signed relative: rel = (y - fit) / y, in input order.
    """
    x = np.asarray(xs, float)
    y = np.asarray(ys, float)
    if len(x) < 2 or np.any(x <= 0) or np.any(y <= 0):
        raise ValueError("power-law fit needs >= 2 positive points")
    k, logc = np.polyfit(np.log(x), np.log(y), 1)
    c = math.exp(logc)
    fitted_log = logc + k * np.log(x)
    fit = {
        "model": "power_law",
        "params": {"c": c, "exponent": float(k)},
        "exponent": float(k),
        "r2": _r2(np.log(y), fitted_log),
    }
    fit["residuals"] = [
        {"x": float(xi), "rel": float((yi - c * xi**k) / yi)} for xi, yi in zip(x, y, strict=True)
    ]
    return fit


def fit_linear(xs: Sequence[float], ys: Sequence[float]) -> dict:
    """y = slope * x + intercept (ordinary least squares); signed relative residuals."""
    x = np.asarray(xs, float)
    y = np.asarray(ys, float)
    if len(x) < 2:
        raise ValueError("linear fit needs >= 2 points")
    slope, intercept = np.polyfit(x, y, 1)
    fit = {
        "model": "linear",
        "params": {"slope": float(slope), "intercept": float(intercept)},
        "r2": _r2(y, slope * x + intercept),
    }
    fit["residuals"] = [
        {"x": float(xi), "rel": float((yi - (slope * xi + intercept)) / yi)}
        for xi, yi in zip(x, y, strict=True)
    ]
    return fit


def fit_poly(xs: Sequence[float], ys: Sequence[float], degree: int = 4) -> dict:
    """y = c4 x^4 + c3 x^3 + ... + c0 (theory shape: leading term x^degree plus lower orders).

    Linear least squares with weights 1/y, so every size counts equally in relative terms.
    `exponent` is the fixed leading power. Residuals are signed relative, as elsewhere.
    """
    x = np.asarray(xs, float)
    y = np.asarray(ys, float)
    if len(x) < degree + 1 or np.any(y <= 0):
        raise ValueError(f"poly fit of degree {degree} needs >= {degree + 1} positive points")
    vander = np.vander(x, degree + 1)
    coeffs, *_ = np.linalg.lstsq(vander / y[:, None], np.ones_like(y), rcond=None)
    fitted = vander @ coeffs
    return {
        "model": f"poly_n{degree}",
        "params": {"coeffs": [float(c) for c in coeffs]},
        "exponent": float(degree),
        "r2": _r2(y, fitted),
        "residuals": [
            {"x": float(xi), "rel": float((yi - fi) / yi)}
            for xi, yi, fi in zip(x, y, fitted, strict=True)
        ],
    }


def holdout(xs: Sequence[float], ys: Sequence[float], fit_fn: FitFn) -> dict:
    """Fit on every point but the largest x, then score the prediction at that x."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    train, last = order[:-1], order[-1]
    fit = fit_fn([xs[i] for i in train], [ys[i] for i in train])
    predicted = predict(fit, xs[last])
    actual = float(ys[last])
    return {
        "n_bits": xs[last],
        "predicted": predicted,
        "actual": actual,
        "rel_error": abs(predicted - actual) / actual,
    }
