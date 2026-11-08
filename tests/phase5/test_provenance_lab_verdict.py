"""Provenance of the Lab verdict (lead's rule, DECISIONS 2026-11-08 P5).

Rule: the headline verdict for a circuit is the RAW configuration's, because the raw configuration
was fixed before the data; "above random guessing" only if the raw 95% Wilson lower bound is above
the chance baseline, otherwise "no better than random guessing". The error-suppression settings
(dd, dd_twirl) are shown beside it, labelled exploratory, and can never move the headline.
The rule is applied here to the raw rows of the Phase 2 analysis file in results/, not to
lab.json, so a wrong headline in lab.json cannot be checked against itself.
"""

from __future__ import annotations

import copy
import json

import pytest

from quantum.risk import webdata

from .helpers import REPO, load_data

SUMMARY = REPO / "results" / "analysis" / "phase2" / "summary-batch-20261108T044751Z.json"
ABOVE = "above random guessing"
NOT_ABOVE = "no better than random guessing"


def _entries() -> dict[str, dict]:
    return json.loads(SUMMARY.read_text())["entries"]


def rule(row: dict) -> str:
    """The lead's rule, written independently of webdata._verdict."""
    return ABOVE if row["wilson_95"][0] > row["chance_baseline"] else NOT_ABOVE


def _raw(name: str) -> dict | None:
    return _entries().get(f"{name}/raw")


CIRCUITS = [c["name"] for c in load_data("lab")["circuits"]]


# ------------------------------------------------ the shipped headline equals the rule on raw


@pytest.mark.parametrize("name", CIRCUITS)
def test_provenance_lab_headline_is_the_raw_row_under_the_rule(name: str) -> None:
    circuit = next(c for c in load_data("lab")["circuits"] if c["name"] == name)
    raw = _raw(name)
    head = circuit["hardware_headline"]
    if raw is None:
        assert head is None, "a headline for a circuit that never ran raw on hardware"
        return
    assert head["config"] == "raw"
    assert head["verdict"] == rule(raw)
    assert head["success_probability"] == raw["success_probability"]
    assert head["chance_baseline"] == raw["chance_baseline"]
    assert head["normalized_score"] == raw["normalized_score"]


def test_provenance_lab_the_verdict_has_exactly_two_possible_values() -> None:
    verdicts = {
        c["hardware_headline"]["verdict"]
        for c in load_data("lab")["circuits"]
        if c["hardware_headline"]
    }
    assert verdicts <= {ABOVE, NOT_ABOVE}


def test_provenance_lab_summary_counts_are_recomputed_from_results() -> None:
    ran = [n for n in CIRCUITS if _raw(n) is not None]
    above = [n for n in ran if rule(_raw(n)) == ABOVE]
    assert load_data("lab")["hardware_summary"] == {
        "ran": len(ran),
        "above": len(above),
        "no_better": len(ran) - len(above),
    }


def test_provenance_lab_the_k5_case_that_prompted_the_rule() -> None:
    # raw below chance (its Wilson interval does not clear 0.03125) must read "no better",
    # even though dd measured higher; the best-of-three headline it replaced said "above"
    raw = _raw("grover_present_k5")
    dd = _entries()["grover_present_k5/dd"]
    assert raw["wilson_95"][0] <= raw["chance_baseline"] < dd["success_probability"]
    head = next(c for c in load_data("lab")["circuits"] if c["name"] == "grover_present_k5")
    assert head["hardware_headline"]["verdict"] == NOT_ABOVE


@pytest.mark.parametrize("name", CIRCUITS)
def test_provenance_lab_exploratory_rows_are_the_other_configs_with_no_verdict(name: str) -> None:
    circuit = next(c for c in load_data("lab")["circuits"] if c["name"] == name)
    others = sorted(
        k.split("/")[1] for k in _entries() if k.startswith(name + "/") and not k.endswith("/raw")
    )
    shown = circuit["hardware_exploratory"]
    assert sorted(r["config"] for r in shown) == others
    assert all("verdict" not in r for r in shown), "an exploratory row must not carry a verdict"
    for r in shown:
        src = _entries()[f"{name}/{r['config']}"]
        assert r["success_probability"] == src["success_probability"]
        assert r["normalized_score"] == src["normalized_score"]


# -------------------------------------------------------- the rule, boundary and independence


def test_provenance_lab_boundary_equal_to_chance_is_not_above() -> None:
    base = {"chance_baseline": 0.25}
    assert rule({**base, "wilson_95": [0.2500001, 0.3]}) == ABOVE
    assert rule({**base, "wilson_95": [0.25, 0.3]}) == NOT_ABOVE  # strictly greater is required
    assert rule({**base, "wilson_95": [0.2, 0.3]}) == NOT_ABOVE
    assert rule({**base, "wilson_95": [0.1, 0.2]}) == NOT_ABOVE  # no third "worse" verdict


def test_provenance_lab_the_builders_verdict_function_agrees_with_the_rule() -> None:
    for lo in (0.0, 0.2, 0.25, 0.2500001, 0.9):
        row = {"chance_baseline": 0.25, "wilson_95": [lo, 1.0]}
        assert webdata._verdict(lo, 0.25) == rule(row), lo


def _hw_rows() -> list[dict]:
    return copy.deepcopy(next(c for c in load_data("lab")["circuits"] if c["hardware"])["hardware"])


def test_provenance_lab_the_headline_ignores_row_order_and_other_configs() -> None:
    rows = _hw_rows()
    base = webdata._headline_hardware(rows)
    assert base["config"] == "raw"
    assert webdata._headline_hardware(list(reversed(rows))) == base
    for r in rows:  # make every non-raw config spectacular: still no change
        if r["config"] != "raw":
            r["success_probability"], r["wilson_95"] = 0.99, [0.98, 1.0]
            r["normalized_score"] = 0.99
    assert webdata._headline_hardware(rows) == base
    assert webdata._headline_hardware([r for r in rows if r["config"] != "raw"]) is None


# ------------------------------------------ the lead's mutation: a copy where dd beats raw


@pytest.fixture
def summary_where_dd_beats_raw(tmp_path, monkeypatch) -> str:  # noqa: ANN001
    summary = json.loads(SUMMARY.read_text())
    name = next(n for n in CIRCUITS if _raw(n) and rule(_raw(n)) == NOT_ABOVE)
    dd = summary["entries"][f"{name}/dd"]
    dd["success_probability"] = 0.999
    dd["wilson_95"] = [0.99, 1.0]
    dd["normalized_score"] = 0.999
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary))
    monkeypatch.setattr(webdata, "HW_SUMMARY", path)
    return name


def test_provenance_lab_a_copy_where_dd_beats_raw_does_not_change_the_headline(
    summary_where_dd_beats_raw: str, monkeypatch
) -> None:  # noqa: ANN001
    name = summary_where_dd_beats_raw
    mutated = next(c for c in webdata.build_lab()["circuits"] if c["name"] == name)
    monkeypatch.undo()  # back to the real summary
    real = next(c for c in webdata.build_lab()["circuits"] if c["name"] == name)
    assert mutated["hardware_headline"] == real["hardware_headline"]
    assert mutated["hardware_headline"]["verdict"] == NOT_ABOVE
    # ...while the exploratory row did move, so the mutation really reached the data
    dd_m = next(r for r in mutated["hardware_exploratory"] if r["config"] == "dd")
    dd_r = next(r for r in real["hardware_exploratory"] if r["config"] == "dd")
    assert dd_m["success_probability"] == 0.999 != dd_r["success_probability"]


def test_provenance_lab_a_copy_where_raw_clears_chance_does_change_the_headline(
    tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    # the converse: moving the RAW row must move the verdict, so the rule is wired to raw
    summary = json.loads(SUMMARY.read_text())
    name = next(n for n in CIRCUITS if _raw(n) and rule(_raw(n)) == NOT_ABOVE)
    raw = summary["entries"][f"{name}/raw"]
    raw["wilson_95"] = [raw["chance_baseline"] + 0.1, raw["chance_baseline"] + 0.2]
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary))
    monkeypatch.setattr(webdata, "HW_SUMMARY", path)
    head = next(c for c in webdata.build_lab()["circuits"] if c["name"] == name)
    assert head["hardware_headline"]["verdict"] == ABOVE
