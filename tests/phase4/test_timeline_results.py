"""results/risk/timeline.json recomputed from its own points and from the literature.

Everything the file reports is recomputed here with tests/phase4/reference.py: the fit, the CI, the
holdout, the baseline, the per-scenario doubling times and every CRQC year. Fields the gate will
read are also required to exist. A missing file FAILS (never skips).
"""

from __future__ import annotations

import pytest

from tests.phase4 import reference as ref

PATH = ref.RESULTS / "timeline.json"


@pytest.fixture(scope="module")
def tl() -> dict:
    return ref.load_json(PATH)


@pytest.fixture(scope="module")
def lit() -> dict:
    return {e["id"]: e for e in ref.literature()}


def _raw(tl):
    return [(p["year"], p["qubits"]) for p in tl["points"]]


def _frontier(tl):
    """Running maximum of the raw per-year series: a dip after a record does not lower it."""
    out, best = [], 0
    for year, q in sorted(_raw(tl)):
        best = max(best, q)
        out.append((year, best))
    return out


def test_timeline_has_the_fixed_interface(tl):
    for key in (
        "as_of",
        "as_of_year",
        "runtime_cap_years",
        "points",
        "frontier",
        "fit",
        "baseline",
        "scenarios",
        "survey_check",
        "sensitivity_raw_series",
    ):
        assert key in tl, key
    assert {"doubling_years", "ci95", "r2", "residuals", "holdout"} <= set(tl["fit"])
    assert set(tl["scenarios"]) == set(ref.SCENARIOS)
    assert tl["runtime_cap_years"] == 1


def test_timeline_has_at_least_six_distinct_years_in_order(tl):
    years = [p["year"] for p in tl["points"]]
    assert len(years) >= 6, years
    assert all(isinstance(y, int) for y in years), years
    assert years == sorted(set(years)), "points must be one per year, ascending"
    assert years[-1] <= tl["as_of_year"]


def test_timeline_every_point_is_a_literature_entry_with_the_same_year_and_qubits(tl, lit):
    for p in tl["points"]:
        e = lit.get(p["literature_id"])
        assert e is not None, f"{p['literature_id']} is not in literature.yaml"
        assert e["target"] == "timeline", p["literature_id"]
        assert e["year"] == p["year"], f"{p['literature_id']}: year {e['year']} vs {p['year']}"
        assert e["value"] == p["qubits"], f"{p['literature_id']}: value {e['value']}"
        assert p["qubits"] > 0


def test_timeline_every_timeline_literature_entry_is_used_once_per_year(tl, lit):
    """The rule picks one entry per year; two timeline entries for one year would be ambiguous."""
    years = [e["year"] for e in lit.values() if e["target"] == "timeline"]
    assert len(years) == len(set(years)), "two timeline entries for the same year"
    assert sorted(years) == [p["year"] for p in tl["points"]]


def test_timeline_frontier_is_the_running_maximum_so_a_dip_does_not_lower_it(tl):
    assert [(f["year"], f["qubits"]) for f in tl["frontier"]] == _frontier(tl)
    q = [f["qubits"] for f in tl["frontier"]]
    assert q == sorted(q), "frontier must never decrease"
    raw = dict(_raw(tl))
    assert any(raw[f["year"]] < f["qubits"] for f in tl["frontier"]), (
        "no dip in the data: this test would prove nothing"
    )


def test_timeline_fit_runs_on_the_frontier_and_is_recomputed(tl):
    r = ref.doubling_fit(_frontier(tl))
    f = tl["fit"]
    assert f["doubling_years"] == pytest.approx(r["doubling_years"], rel=1e-9)
    assert f["r2"] == pytest.approx(r["r2"], abs=1e-9)
    for got, want in zip(f["ci95"], r["ci95"], strict=True):
        if want is None:
            assert got is None
        else:
            assert got == pytest.approx(want, rel=1e-9)
    assert [x["year"] for x in f["residuals"]] == [y for y, _ in _frontier(tl)]


def test_timeline_residuals_are_signed_relative_errors_of_the_fitted_qubits(tl):
    """rel = (actual - fitted) / actual, the Phase 3 convention, with fitted = 2^(a + b year)."""
    fr = _frontier(tl)
    r = ref.doubling_fit(fr)
    for (year, q), row in zip(fr, tl["fit"]["residuals"], strict=True):
        fitted = ref.predict_qubits(r, year)
        assert row["rel"] == pytest.approx((q - fitted) / q, abs=1e-9), year


def test_timeline_holdout_refits_without_the_latest_frontier_point_and_predicts_it(tl):
    h, r = tl["fit"]["holdout"], ref.holdout(_frontier(tl))
    assert h["year"] == r["year"] == _frontier(tl)[-1][0]
    assert h["actual"] == r["actual"]
    assert h["predicted"] == pytest.approx(r["predicted"], rel=1e-9)
    assert h["signed_rel_error"] == pytest.approx(r["rel_error"], abs=1e-9)
    assert h["rel_error"] == pytest.approx(abs(r["rel_error"]), abs=1e-9)


def test_timeline_sensitivity_fit_on_the_raw_series_is_recomputed_and_labelled(tl):
    s = tl["sensitivity_raw_series"]
    r = ref.doubling_fit(_raw(tl))
    assert s["doubling_years"] == pytest.approx(r["doubling_years"], rel=1e-9)
    assert s["r2"] == pytest.approx(r["r2"], abs=1e-9)
    assert s["holdout"]["actual"] == _raw(tl)[-1][1]
    assert "not used" in s["note"].lower()


def test_timeline_baseline_is_the_latest_record_of_the_frontier(tl):
    fr = _frontier(tl)
    record = fr[-1][1]
    first_year = next(y for y, q in fr if q == record)
    b = tl["baseline"]
    assert (b["year"], b["qubits"]) == (first_year, record)
    pt = next(p for p in tl["points"] if p["year"] == first_year)
    assert b["literature_id"] == pt["literature_id"]


def test_timeline_scenario_doubling_times_use_the_ci_ends_and_the_point_fit(tl):
    r = ref.doubling_fit(_frontier(tl))
    s = tl["scenarios"]
    assert s["median"]["doubling_years"] == pytest.approx(r["doubling_years"], rel=1e-9)
    assert s["optimistic"]["doubling_years"] == pytest.approx(r["ci95"][0], rel=1e-9)
    assert r["ci95"][1] is not None, "fixture: this series' long CI end exists"
    assert s["pessimistic"]["doubling_years"] == pytest.approx(r["ci95"][1], rel=1e-9)
    d = [s[n]["doubling_years"] for n in ref.SCENARIOS]
    assert d == sorted(d), f"faster progress first: {d}"


def _feeds(lit):
    return [e for e in lit.values() if e.get("feeds")]


def test_timeline_only_physical_qubit_feeds_exist(lit):
    """Lead (2026-11-08): papers feed physical qubits only; runtime always comes from the model."""
    kinds = {e["feeds"]["kind"] for e in _feeds(lit)}
    assert kinds == {"physical_qubits"}, f"feed kinds {kinds}"


def test_timeline_every_feed_is_a_verified_entry_with_all_its_fields(lit):
    fc = ref.factcheck()
    for e in _feeds(lit):
        f = e["feeds"]
        assert {"target", "kind", "qec_family", "physical_error_rate", "bound"} <= set(f), e["id"]
        assert f["target"] == e["target"] and e["quantity"] == "physical_qubits", e["id"]
        assert fc[e["id"]]["status"] == "verified", f"{e['id']}: {fc[e['id']]['status']}"
        assert 0 < f["physical_error_rate"] < 0.1
        assert f["bound"] in (None, "upper"), e["id"]
        assert (f["bound"] == "upper") == ("upper bound" in e["units"].lower()), (
            f"{e['id']}: feeds.bound and the units text disagree"
        )


def _model_row(target, name):
    return ref.load_json(ref.EST / "scenarios.json")["targets"][target]["by_scenario"][name]


def _expected_physical(target, name, lit):
    sc = ref.load_json(ref.EST / "scenarios.json")["scenarios"][name]
    model = _model_row(target, name)["physical_qubits"]
    best, src = model, "model"
    for e in _feeds(lit):
        f = e["feeds"]
        if f["kind"] != "physical_qubits":
            continue  # rejected separately by test_timeline_only_physical_qubit_feeds_exist
        same_family = sc["qec_scheme"]["name"] == "surface_code" and f["qec_family"].startswith(
            "surface_code"
        )
        if (
            f["target"] == target
            and same_family
            and sc["physical_error_rate"] <= f["physical_error_rate"]
        ):
            if e["value"] < best:
                best, src = e["value"], e["id"]
    return best, src


def test_timeline_physical_qubits_are_min_of_model_and_an_applicable_paper(tl, lit):
    for name in ref.SCENARIOS:
        for target, row in tl["scenarios"][name]["targets"].items():
            want, src = _expected_physical(target, name, lit)
            assert row["physical_qubits"] == pytest.approx(want, rel=1e-9), (name, target)
            assert row["physical_source"] == src, (name, target, row["physical_source"], src)
            bound = lit[src]["feeds"]["bound"] if src != "model" else None
            assert row["physical_bound"] == bound, (name, target)


def test_timeline_runtime_always_comes_from_the_phase3_model(tl):
    for name in ref.SCENARIOS:
        for target, row in tl["scenarios"][name]["targets"].items():
            assert row["runtime_source"] == "model", (name, target, row["runtime_source"])
            want = _model_row(target, name)["runtime_seconds"]
            assert row["runtime_seconds"] == pytest.approx(want, rel=1e-9), (name, target)


def test_timeline_a_paper_is_never_used_when_it_would_be_worse_than_the_model(tl, lit):
    for name in ref.SCENARIOS:
        for target, row in tl["scenarios"][name]["targets"].items():
            assert row["physical_qubits"] <= _model_row(target, name)["physical_qubits"] * (
                1 + 1e-12
            )


def test_timeline_every_crqc_year_is_recomputed(tl):
    b = tl["baseline"]["qubits"]
    for name in ref.SCENARIOS:
        sc = tl["scenarios"][name]
        for target, row in sc["targets"].items():
            want = ref.crqc_year(
                tl["as_of_year"],
                sc["doubling_years"],
                row["physical_qubits"],
                row["runtime_seconds"],
                b,
                tl["runtime_cap_years"],
            )
            assert row["feasible"] is (want is not None), (name, target)
            if want is None:
                assert row["crqc_year"] is None, (name, target)
            else:
                assert row["crqc_year"] == pytest.approx(want, rel=1e-9), (name, target)


def test_timeline_crqc_year_never_later_in_a_faster_scenario_null_counts_as_never(tl):
    """optimistic <= median <= pessimistic for every target (None = never = +inf)."""
    for target in ref.TARGETS:
        years = [tl["scenarios"][n]["targets"][target]["crqc_year"] for n in ref.SCENARIOS]
        key = [float("inf") if y is None else y for y in years]
        assert key == sorted(key), (target, years)


def test_timeline_scenario_notes_state_truthfully_which_shor_attacks_fit_the_cap(tl):
    """scenario_notes (web scenarios.json) are computed text: they must agree with the data. If no
    Shor attack is feasible in a scenario the note must say so (and that no asset then has a
    quantum margin); otherwise it must not claim that."""
    notes = ref.load_json(ref.WEB_DATA / "scenarios.json").get("scenario_notes")
    assert notes and set(notes) == set(ref.SCENARIOS)
    for name in ref.SCENARIOS:
        shor = [tl["scenarios"][name]["targets"][t]["feasible"] for t in ("rsa2048", "ecc256")]
        text = notes[name].lower()
        if any(shor):
            assert "at least one" in text and "fits" in text, (name, notes[name])
        else:
            assert "exceeds" in text and "no asset has a finite" in text, (name, notes[name])


def test_timeline_the_shor_targets_that_miss_the_cap_exceed_it_by_the_stated_runtime(tl):
    for name in ref.SCENARIOS:
        for t in ("rsa2048", "ecc256"):
            r = tl["scenarios"][name]["targets"][t]
            over = r["runtime_seconds"] > tl["runtime_cap_years"] * ref.SECONDS_PER_YEAR
            assert r["feasible"] is (not over), (name, t)


def test_timeline_survey_check_delta_is_model_year_minus_survey_year(tl, lit):
    s = tl["survey_check"]
    e = lit[s["literature_id"]]
    assert e["target"] != "timeline"
    assert s["survey_year"] == e["year"] + e["value"]
    assert s["model_year"] == pytest.approx(
        tl["scenarios"]["median"]["targets"]["rsa2048"]["crqc_year"], rel=1e-12
    )
    assert s["delta_years"] == pytest.approx(s["model_year"] - s["survey_year"], abs=1e-9)


def test_timeline_inclusion_rule_lives_in_one_place_and_the_file_carries_it(tl):
    rule = ref.load_yaml(ref.RISK / "exposure.yaml")["timeline_inclusion_rule"]
    assert " ".join(str(tl["inclusion_rule"]).split()) == " ".join(rule.split())
    text = ref.LIT.read_text()
    assert text.count("Inclusion rule (one rule") == 0, "rule text must not be copied into the yaml"
