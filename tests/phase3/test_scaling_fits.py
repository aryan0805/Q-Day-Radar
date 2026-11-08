"""Scaling fits: every point is rebuilt from the per-case files and every fit is refitted here.

scaling.json holds several models per (estimator, quantity); exactly one is `selected` (the one
with the lower holdout error). Each model is refitted with tests/phase3/reference.py, which shares
no code with quantum/estimate/scaling.py.
"""

from __future__ import annotations

import math
import re
import statistics

import pytest

from tests.phase3 import reference as ref

CASE = {
    "qdk": re.compile(r"^beauregard_N(\d+)_a(\d+)$"),
    "qualtran": re.compile(r"^modexp_N(\d+)_a(\d+)$"),
}
MODELS = {"power_law", "poly_n4", "linear"}
CAVEAT_THRESHOLD = 0.05  # lead's rule: any |rel| or the holdout rel_error above this needs a caveat
# Effective-exponent windows for the POWER-LAW model. Beauregard's asymptote is n^4 (2n controlled
# multipliers x n modular adders x an O(n^2) QFT around each addition), but over n = 4..14 the
# lower-order terms inflate the fitted exponent; Qualtran's ModExp is Toffoli arithmetic (~n^3).
EXPONENT_WINDOW = {"qdk": (3.0, 6.0), "qualtran": (1.0, 4.0)}


@pytest.fixture(scope="module")
def fits() -> list[dict]:
    return ref.load_json(ref.EST / "scaling.json")["fits"]


def _is_qubits(f: dict) -> bool:
    return "qubit" in f["quantity"]


def _tag(f: dict) -> str:
    return f"{f['estimator']}/{f['quantity']}/{f['model']}"


def _from_files(f: dict, n_bits: int) -> tuple[list[int], list[float]]:
    """Bases and the per-base value for one size, read from the per-case files."""
    tool, vals, bases = f["estimator"], [], []
    for case, c in ref.cases(tool).items():
        if CASE[tool].match(case) and c["n_bits"] == n_bits:
            bases.append(c["base_a"])
            vals.append(ref.qubits_of(tool, c) if _is_qubits(f) else c["toffoli_equiv"])
    return bases, vals


def reference_predictor(model: str, xs: list[float], ys: list[float]):
    """Fit `model` to (xs, ys) from scratch; returns (predict, params-for-comparison)."""
    if model == "power_law":
        k, c = ref.power_law(xs, ys)
        return (lambda x: c * x**k), {"exponent": k, "c": c}
    if model == "linear":
        a, b = ref.linear(xs, ys)
        return (lambda x: a * x + b), {"slope": a, "intercept": b}
    if model == "poly_n4":
        coeffs = ref.poly_rel(xs, ys, 4)
        return (lambda x: ref.polyval(coeffs, x)), {"coeffs": coeffs}
    raise AssertionError(f"unknown model {model!r}")


def _sorted_points(f):
    pts = sorted(f["points"], key=lambda p: p["n_bits"])
    return pts, [p["n_bits"] for p in pts], [p["value"] for p in pts]


# ---------------------------------------------------------------------------------------------
def test_scaling_gate_shape_every_fit_has_points_residuals_holdout_and_2048(fits):
    for tool in ("qdk", "qualtran"):
        mine = [f for f in fits if f["estimator"] == tool]
        assert len(mine) >= 2, f"{tool}: {len(mine)} fits"
        assert {_is_qubits(f) for f in mine} == {True, False}, (
            f"{tool}: need a qubit and a cost fit"
        )
    for f in fits:
        assert f["model"] in MODELS, _tag(f)
        assert len(f["points"]) >= 5, _tag(f)
        assert sorted(p["n_bits"] for p in f["points"]) == sorted(
            r["n_bits"] for r in f["residuals"]
        ), _tag(f)
        assert f["holdout"]["rel_error"] is not None, _tag(f)
        assert f["extrapolated"]["n_bits"] == 2048 and f["extrapolated"]["value"] > 0, _tag(f)


def test_scaling_exactly_one_model_is_selected_per_quantity_and_it_has_the_lower_holdout(fits):
    groups: dict[tuple[str, str], list[dict]] = {}
    for f in fits:
        groups.setdefault((f["estimator"], f["quantity"]), []).append(f)
    for (est, qty), g in groups.items():
        sel = [f for f in g if f.get("selected") is True]
        assert len(sel) == 1, f"{est}/{qty}: {len(sel)} selected fits"
        best = min(f["holdout"]["rel_error"] for f in g)
        assert sel[0]["holdout"]["rel_error"] == pytest.approx(best, rel=1e-9), f"{est}/{qty}"
    for tool in ("qdk", "qualtran"):  # the cost quantity must offer a real choice of models
        models = {f["model"] for f in fits if f["estimator"] == tool and not _is_qubits(f)}
        assert {"power_law", "poly_n4"} <= models, f"{tool}: cost models {models}"


def test_scaling_points_are_the_median_over_bases_of_the_per_case_files(fits):
    for f in fits:
        for p in f["points"]:
            bases, vals = _from_files(f, p["n_bits"])
            tag = f"{_tag(f)} n={p['n_bits']}"
            assert sorted(p["bases"]) == sorted(bases), (
                f"{tag}: bases {p['bases']} vs files {bases}"
            )
            assert p["value"] == pytest.approx(statistics.median(vals), rel=1e-9), tag
            assert p["spread"] >= 0 and math.isfinite(p["spread"]), tag
            if len(set(vals)) > 1:
                assert p["spread"] > 0, f"{tag}: bases differ but spread is 0"


def test_scaling_P005_no_point_rests_on_one_base_or_order_two_bases_only(fits):
    for f in fits:
        for p in f["points"]:
            tag = f"{_tag(f)} n={p['n_bits']}"
            assert len(set(p["bases"])) >= 3, f"{tag}: bases {p['bases']}"
            assert any(ref.order(a, p["N"]) > 2 for a in p["bases"]), f"{tag}: order-2 bases only"


# ---- every model, refitted independently -------------------------------------------------------
def test_scaling_every_fit_is_reproduced_by_an_independent_refit(fits):
    for f in fits:
        _, xs, ys = _sorted_points(f)
        predict, params = reference_predictor(f["model"], xs, ys)
        tag = _tag(f)
        for key, want in params.items():
            got = f["params"][key]
            if isinstance(want, list):
                assert got == pytest.approx(want, rel=1e-6, abs=1e-6), f"{tag}: {key}"
            else:
                assert got == pytest.approx(want, rel=1e-6, abs=1e-9), f"{tag}: {key}"
        want2048 = predict(2048.0)
        assert f["extrapolated"]["value"] == pytest.approx(want2048, rel=1e-6), tag


def test_scaling_residuals_are_signed_value_minus_fit_over_value_for_every_model(fits):
    for f in fits:
        _, xs, ys = _sorted_points(f)
        predict, _ = reference_predictor(f["model"], xs, ys)
        by_n = {r["n_bits"]: r["rel"] for r in f["residuals"]}
        for x, y in zip(xs, ys, strict=True):
            want = (y - predict(x)) / y
            assert by_n[x] == pytest.approx(want, abs=1e-6), f"{_tag(f)} n={x}: {by_n[x]} vs {want}"
            if abs(want) > 0.05:  # large enough that a flipped sign cannot hide in the tolerance
                assert by_n[x] * want > 0, f"{_tag(f)} n={x}: wrong sign"


def test_scaling_holdout_is_the_largest_size_fitted_on_the_smaller_ones_for_every_model(fits):
    for f in fits:
        _, xs, ys = _sorted_points(f)
        h, tag = f["holdout"], _tag(f)
        assert h["n_bits"] == xs[-1], f"{tag}: holdout at {h['n_bits']}"
        assert h["actual"] == pytest.approx(ys[-1], rel=1e-9), tag
        predict, _ = reference_predictor(f["model"], xs[:-1], ys[:-1])
        pred = predict(float(xs[-1]))
        assert h["predicted"] == pytest.approx(pred, rel=1e-6), tag
        assert h["rel_error"] == pytest.approx(abs(pred - ys[-1]) / ys[-1], abs=1e-6), tag


def test_scaling_power_law_exponent_is_in_its_window(fits):
    for f in fits:
        if f["model"] != "power_law" or _is_qubits(f):
            continue
        _, xs, ys = _sorted_points(f)
        k, _ = ref.power_law(xs, ys)
        assert f["exponent"] == pytest.approx(k, abs=1e-6), _tag(f)
        lo, hi = EXPONENT_WINDOW[f["estimator"]]
        assert lo < f["exponent"] < hi, f"{_tag(f)}: exponent {f['exponent']} outside ({lo}, {hi})"


def test_scaling_qubit_fits_are_linear_with_positive_slope(fits):
    for f in fits:
        if _is_qubits(f):
            assert f["model"] == "linear" and f["params"]["slope"] > 0, _tag(f)


# ---- curvature of the QDK Beauregard cost: measured, not assumed ------------------------
def _local_slopes(pts: list[dict]) -> list[float]:
    return [
        math.log(b["value"] / a["value"]) / math.log(b["n_bits"] / a["n_bits"])
        for a, b in zip(pts, pts[1:], strict=False)
    ]


def _qdk_cost(fits, model):
    return next(
        f for f in fits if f["estimator"] == "qdk" and f["model"] == model and not _is_qubits(f)
    )


def test_scaling_beauregard_local_slope_falls_toward_four_so_one_power_law_overshoots(fits):
    f = _qdk_cost(fits, "power_law")
    s = _local_slopes(sorted(f["points"], key=lambda p: p["n_bits"]))
    assert all(a >= b - 0.05 for a, b in zip(s, s[1:], strict=False)), f"slopes not falling: {s}"
    assert 3.9 < s[-1] < 4.5, f"last local slope {s[-1]}"
    assert f["exponent"] > s[-1] + 0.2, "single power law should sit above the last local slope"


def test_scaling_beauregard_selected_fit_is_the_degree_four_polynomial_not_the_power_law(fits):
    pl, poly = _qdk_cost(fits, "power_law"), _qdk_cost(fits, "poly_n4")
    assert poly["selected"] is True and not pl["selected"]
    assert poly["holdout"]["rel_error"] < pl["holdout"]["rel_error"]
    assert (
        max(abs(r["rel"]) for r in poly["residuals"])
        < 0.05
        < max(abs(r["rel"]) for r in pl["residuals"])
    )
    assert poly["params"]["coeffs"][0] > 0, "leading n^4 coefficient must be positive"
    assert poly["extrapolated"]["value"] < pl["extrapolated"]["value"] / 5, "power law overshoots"


def test_scaling_unweighted_degree_four_polynomial_lands_within_25_percent_of_the_selected_one(
    fits,
):
    """Model spread: an unweighted degree-4 fit is a sanity bracket, not a replacement."""
    import numpy as np

    poly = _qdk_cost(fits, "poly_n4")
    _, xs, ys = _sorted_points(poly)
    other = np.polyval(np.polyfit(xs, ys, 4), 2048.0)
    assert other == pytest.approx(poly["extrapolated"]["value"], rel=0.25)


# ---- caveats (lead, 2026-11-08): anything above 5% needs a caveat and a bracket ---------
def test_scaling_fits_with_a_residual_or_holdout_over_five_percent_carry_a_caveat_and_a_bracket(
    fits,
):
    flagged = 0
    for f in fits:
        worst = max(abs(r["rel"]) for r in f["residuals"])
        if worst <= CAVEAT_THRESHOLD and f["holdout"]["rel_error"] <= CAVEAT_THRESHOLD:
            continue
        flagged += 1
        e, tag = f["extrapolated"], _tag(f)
        assert str(f.get("caveat", "")).strip(), f"{tag}: |rel| {worst:.3f}, no caveat"
        assert 0 < e["low"] <= e["value"] <= e["high"], (
            f"{tag}: bracket {e.get('low')}, {e.get('high')}"
        )
    assert flagged >= 1, "the free QDK power law is known to exceed 5%; the rule matched nothing"


def test_scaling_selected_qualtran_cost_fit_predicts_the_directly_measured_2048_bit_modexp(fits):
    """Out-of-sample by a factor of 146 in n: fit stops at 14 bits, the bloq is costed at 2048."""
    sel = next(
        f for f in fits if f["estimator"] == "qualtran" and f["selected"] and not _is_qubits(f)
    )
    measured = ref.cases("qualtran")["rsa2048_modexp"]["toffoli_equiv"]
    assert sel["extrapolated"]["value"] == pytest.approx(measured, rel=1e-3)
    q = next(f for f in fits if f["estimator"] == "qualtran" and f["selected"] and _is_qubits(f))
    assert q["extrapolated"]["value"] == pytest.approx(
        ref.cases("qualtran")["rsa2048_modexp"]["logical_qubits"]
    )


def test_scaling_eps_consistent_extrapolation_prices_rotations_at_the_precision_n2048_needs(fits):
    """eps_consistent_*: same fit, rotation cost re-priced; it can only go up, and not at all for
    a tool whose circuit has no rotations."""
    for f in fits:
        if _is_qubits(f):
            continue
        e, tag = f["extrapolated"], _tag(f)
        base_cost = next(iter(ref.cases(f["estimator"]).values()))["rotation_t_cost"]
        assert e["eps_consistent_rotation_t_cost"] >= base_cost, tag
        assert e["eps_consistent_value"] >= e["value"] * (1 - 1e-9), tag
        if f["estimator"] == "qualtran":
            assert e["eps_consistent_value"] == pytest.approx(e["value"], rel=1e-9), tag


def test_scaling_reference_fits_recover_known_answers_from_synthetic_data():
    """Guards the oracles used above."""
    xs = [4, 6, 8, 12, 16, 24]
    k, c = ref.power_law(xs, [3 * x**2.5 for x in xs])
    assert k == pytest.approx(2.5, abs=1e-9) and c == pytest.approx(3.0, rel=1e-9)
    a, b = ref.linear(xs, [5 * x + 7 for x in xs])
    assert (a, b) == (pytest.approx(5.0), pytest.approx(7.0))
    xs2 = [4, 5, 6, 7, 8, 9, 10]
    coeffs = ref.poly_rel(xs2, [2 * x**4 - 3 * x**3 + x + 5 for x in xs2], 4)
    assert coeffs == pytest.approx([2, -3, 0, 1, 5], abs=1e-6)
    assert ref.polyval(coeffs, 10.0) == pytest.approx(2 * 10**4 - 3 * 10**3 + 10 + 5, rel=1e-9)


def test_scaling_sign_convention_is_checked_by_the_reference_not_assumed():
    """Convex data fitted by a power law: the ends are under-fit (+), the middle over-fit (-)."""
    xs = [4, 8, 16, 32, 64]
    ys = [x**2 + 0.5 * x**3 for x in xs]
    k, c = ref.power_law(xs, ys)
    rel = [(y - c * x**k) / y for x, y in zip(xs, ys, strict=True)]
    assert abs(sum(math.log(c * x**k / y) for x, y in zip(xs, ys, strict=True))) < 1e-9
    assert rel[0] * rel[2] < 0 or rel[-1] * rel[2] < 0, rel
