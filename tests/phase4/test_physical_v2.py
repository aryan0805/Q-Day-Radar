"""Physical model v2: the pre-registered generalization test and its truthful record.

Lead and the human (2026-11-08, IMPROVE round 2): v2 rebuilds Gidney 2025's own accounting; the
tolerance (1.5x) and the five parameters were fixed before the first run. (a) v2 on Gidney's own
logical counts vs his 897,864 is a CONSISTENCY check (agreement is by construction); (b) v2 on the
Google 2026 ECC-256 counts vs its "fewer than half a million" bound is the independent holdout.
The human chose to RECORD the failure of (b). These tests check that the record is truthful, that
the registered parameters did not move, and that no scenario adopted v2.

The v2 formula is re-derived here from Gidney's printed components, independently of
quantum/estimate/physical.py:
  physical = L * (c * cold + (1 - c) * hot) + patches * hot
  with hot = 2 (d + 1)^2 and c = m / max_logical.
"""

from __future__ import annotations

import pytest

from tests.phase4 import reference as ref

# Pre-registered values (the builder's interface note, accepted unchanged on 2026-11-08):
REGISTERED = {
    "g2025_code_distance": 25,
    "g2025_cold_storage_physical_per_logical": 430,
    "g2025_cold_logical_qubits_m": 1280,
    "g2025_max_algorithmic_logical_qubits": 1409,
    "g2025_compute_region_hot_patches": 126,
}
REGISTERED_HOT_PATCH_QUBITS = 1352  # 2 * (25 + 1)^2
REGISTERED_COMPUTE_REGION = 170352  # 126 * 1352
TOLERANCE = 1.5


@pytest.fixture(scope="module")
def lit() -> dict:
    return {e["id"]: e for e in ref.literature()}


@pytest.fixture(scope="module")
def rows() -> dict:
    cal = ref.load_json(ref.EST / "calibration.json")["comparisons"]
    got = {(r["target"]): r for r in cal if r["estimator"] == "physical_v2"}
    assert set(got) == {"rsa2048", "ecc256"}, f"physical_v2 rows: {sorted(got)}"
    return got


def v2(logical: float) -> float:
    d = REGISTERED["g2025_code_distance"]
    hot = 2 * (d + 1) ** 2
    c = (
        REGISTERED["g2025_cold_logical_qubits_m"]
        / REGISTERED["g2025_max_algorithmic_logical_qubits"]
    )
    cold = REGISTERED["g2025_cold_storage_physical_per_logical"]
    return (
        logical * (c * cold + (1 - c) * hot) + REGISTERED["g2025_compute_region_hot_patches"] * hot
    )


def test_physical_v2_registered_parameters_equal_the_literature_values(lit):
    for i, want in REGISTERED.items():
        assert lit[i]["value"] == want, f"{i}: {lit[i]['value']} != registered {want}"
    assert 2 * (REGISTERED["g2025_code_distance"] + 1) ** 2 == REGISTERED_HOT_PATCH_QUBITS
    assert (
        REGISTERED["g2025_compute_region_hot_patches"] * REGISTERED_HOT_PATCH_QUBITS
        == REGISTERED_COMPUTE_REGION
    )


def test_physical_v2_hand_arithmetic_on_gidneys_own_counts():
    """1409 logical: 1280 cold x 430 = 550,400; 129 hot x 1352 = 174,408; compute 170,352."""
    assert 1280 * 430 == 550_400 and 129 * 1352 == 174_408
    assert 550_400 + 174_408 + REGISTERED_COMPUTE_REGION == 895_160
    assert v2(1409) == pytest.approx(895_160, abs=1e-6)


def test_physical_v2_rows_equal_the_independent_formula(rows, lit):
    for target, row in rows.items():
        assert row["ours"] == pytest.approx(v2(row["input_logical_qubits"]), rel=1e-9), target
        assert row["v2"]["code_distance"] == REGISTERED["g2025_code_distance"]
        assert row["v2"]["hot_patch_qubits"] == REGISTERED_HOT_PATCH_QUBITS
        assert row["v2"]["compute_region_qubits"] == REGISTERED_COMPUTE_REGION
        assert row["v2"]["distance_extension"] is False, (
            "at p = 1e-3 the labelled non-Gidney suppression extension must not be used"
        )


def test_physical_v2_rows_cite_the_right_literature_entries_and_inputs(rows, lit):
    rsa, ecc = rows["rsa2048"], rows["ecc256"]
    assert rsa["literature_id"] == "g2025_physical_qubits_rsa2048"
    assert ecc["literature_id"] == "google2026_physical_qubits_ecc256"
    assert rsa["input_logical_qubits_id"] == "g2025_max_algorithmic_logical_qubits"
    assert ecc["input_logical_qubits_id"] == "google2026_logical_qubits_ecc256"
    for r in (rsa, ecc):
        assert r["literature_value"] == lit[r["literature_id"]]["value"]
        assert r["input_logical_qubits"] == lit[r["input_logical_qubits_id"]]["value"]
        assert r["quantity"] == "physical_qubits"


def test_physical_v2_ratio_and_within_flag_are_recomputed_not_trusted(rows):
    for target, r in rows.items():
        ratio = r["ours"] / r["literature_value"]
        assert r["ratio"] == pytest.approx(ratio, rel=1e-9), target
        assert r["tolerance"]["factor"] == TOLERANCE, "the tolerance was fixed at 1.5 before BUILD"
        kind = r["tolerance"]["kind"]
        if target == "rsa2048":
            assert kind == "two_sided"
            want = 1 / TOLERANCE <= ratio <= TOLERANCE
        else:
            assert kind == "one_sided"  # the Google figure is an upper bound
            want = ratio <= TOLERANCE
        assert r["tolerance"]["within"] is want, f"{target}: ratio {ratio:.4f}, within={want}"


def test_physical_v2_the_holdout_failure_is_recorded_as_a_failure_and_says_so(rows):
    ecc = rows["ecc256"]
    assert ecc["ratio"] > TOLERANCE, "this test records the registered outcome: the holdout fails"
    assert ecc["tolerance"]["within"] is False
    assert "fail" in ecc["explanation"].lower()
    assert "tun" in ecc["explanation"].lower(), "the row must say it was not tuned"


def test_physical_v2_the_consistency_row_says_it_is_not_independent_evidence(rows):
    rsa = rows["rsa2048"]
    text = rsa["explanation"].lower()
    assert "consistency" in text and "not independent" in text


def test_physical_v2_not_adopted_by_any_scenario_or_downstream_number():
    """No scenario row equals v2's value for its logical qubits; v2 is a calibration row only."""
    scen = ref.load_json(ref.EST / "scenarios.json")
    text = (ref.EST / "scenarios.json").read_text() + (ref.RESULTS / "timeline.json").read_text()
    assert "physical_v2" not in text, "a result file names physical_v2 as its estimator"
    for target, body in scen["targets"].items():
        for name, row in body["by_scenario"].items():
            assert row["physical_qubits"] != pytest.approx(v2(row["logical_qubits"]), rel=1e-6), (
                f"{target}/{name} equals the v2 value"
            )
    tl = ref.load_json(ref.RESULTS / "timeline.json")
    for name in ref.SCENARIOS:
        for target, row in tl["scenarios"][name]["targets"].items():
            assert row["physical_source"] != "physical_v2", (name, target)


def test_physical_v2_every_parameter_has_a_locator_and_is_a_verified_gidney_entry(lit):
    fc = ref.factcheck()
    spec = ref.load_yaml(ref.EST.parent.parent / "quantum" / "estimate" / "scenarios.yaml")[
        "physical_v2"
    ]
    ids = [v for k, v in spec.items() if k.endswith("_id")]
    assert set(REGISTERED) <= set(ids), "a registered component is missing from the spec"
    for i in ids:
        e = lit[i]
        assert str(e["locator"]).strip() and str(e["source_url"]).startswith("https://"), i
        assert "2505.15917" in e["source_url"], f"{i}: not from Gidney 2025"
        assert fc[i]["status"] == "verified", f"{i}: {fc[i]['status']}"
    # the only non-Gidney number is labelled as such in the spec
    assert (
        "NOT from Gidney" in (ref.EST.parent.parent / "quantum/estimate/scenarios.yaml").read_text()
    )
    assert spec["tolerance_factor"] == TOLERANCE


def _preregistration_order_problem(events: dict) -> str | None:
    """None when the events happened in the required order, else what is wrong."""
    order = ("interface", "decision", "first_calibration")
    missing = [k for k in order if k not in events]
    if missing:
        return f"missing events {missing}"
    stamps = [events[k]["time"] for k in order]  # "YYYY-MM-DD HH:MM" sorts as time
    if not stamps[0] < stamps[1] <= stamps[2]:
        return f"calibration reported before the parameters were pre-registered: {stamps}"
    return None


def test_physical_v2_was_pre_registered_before_its_first_calibration():
    """Event order (copied once from the dev log): the builder's interface note for physical v2,
    then the lead's decision computing the ratios, then the builder's report carrying the first
    calibration rows. Reading the copy, not the log: the log is not in the public repo."""
    events = ref.load_json(ref.ROOT / "tests" / "data" / "private_facts.json")[
        "preregistration_events"
    ]
    assert _preregistration_order_problem(events) is None, _preregistration_order_problem(events)
    assert [events[k]["type"] for k in ("interface", "decision", "first_calibration")] == [
        "INTERFACE",
        "DECISION",
        "READY_FOR_TEST",
    ]


def test_physical_v2_order_check_catches_a_calibration_reported_first():
    """Planted defect: swap the first and last times and the check must fail."""
    events = ref.load_json(ref.ROOT / "tests" / "data" / "private_facts.json")[
        "preregistration_events"
    ]
    bad = {k: dict(v) for k, v in events.items()}
    bad["interface"]["time"], bad["first_calibration"]["time"] = (
        events["first_calibration"]["time"],
        events["interface"]["time"],
    )
    assert _preregistration_order_problem(bad) is not None


# builder's [INTERFACE] (15:24, forwarded verbatim by lead), item -> literature id the code reads:
PREREGISTERED_ITEMS = {
    "1 hot patch 2(d+1)^2 qubits": "g2025_code_distance",
    "2 d = 25 sufficient at p = 1e-3 (target 1e-15 per round)": "g2025_physical_error_rate",
    "3 cold storage 430 physical per logical": "g2025_cold_storage_physical_per_logical",
    "4a cold logical qubits m = 1280": "g2025_cold_logical_qubits_m",
    "4b algorithmic logical qubits at the maximum = 1409": "g2025_max_algorithmic_logical_qubits",
    "5 compute region 7x18 = 126 hot patches": "g2025_compute_region_hot_patches",
}


def test_physical_v2_the_spec_holds_exactly_the_preregistered_items_and_two_labelled_extras():
    """Every v2 parameter appears in the pre-registered [INTERFACE]; nothing else was added except
    the lead-fixed tolerance and the labelled non-Gidney threshold (introduced when lead answered
    the extension question, used only for error rates other than 1e-3)."""
    spec = ref.load_yaml(ref.ROOT / "quantum" / "estimate" / "scenarios.yaml")["physical_v2"]
    ids = {k: v for k, v in spec.items() if k.endswith("_id")}
    assert set(ids.values()) == set(PREREGISTERED_ITEMS.values()), ids
    assert set(spec) - set(ids) == {"p_threshold", "tolerance_factor"}, sorted(spec)


def test_physical_v2_function_equals_the_independent_formula_and_ignores_the_target_error():
    """physical_estimate_v2 equals the formula re-derived here; the 1e-15 target quoted in the
    interface is not a parameter of the spec."""
    from quantum.estimate import physical

    base = physical.physical_estimate_v2(1200, 1e-3)["physical_qubits"]
    assert base == pytest.approx(v2(1200), rel=1e-9)
    # the target error per round is quoted in the interface but is not an input to the formula
    assert (
        "g2025_target_logical_error_per_round"
        not in (ref.ROOT / "quantum" / "estimate" / "scenarios.yaml")
        .read_text()
        .split("physical_v2:")[1]
    )


def test_physical_v2_gap_between_the_paper_total_and_a_v2_on_its_own_counts_is_two_hot_patches(lit):
    """v2 with 1409 logical qubits has 129 hot patches (1409 - 1280); the paper's own text has
    131 (and 1280 + 131 = 1411): the 0.3% shortfall of check (a) is 2 patches of 1352 qubits."""
    paper = lit["g2025_physical_qubits_rsa2048"]["value"]
    assert paper == 550_400 + 131 * 1352 + REGISTERED_COMPUTE_REGION
    assert paper - v2(1409) == pytest.approx(2 * 1352, abs=1e-6)
