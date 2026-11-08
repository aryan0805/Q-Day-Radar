"""Physical scenarios, calibration against the literature, and the literature file itself."""

from __future__ import annotations

import datetime as dt
import math

import pytest

from tests.phase3 import reference as ref

ORDER = ref.SCENARIOS  # optimistic -> pessimistic: error rate rises, so cost must not fall


@pytest.fixture(scope="module")
def scen() -> dict:
    return ref.load_json(ref.EST / "scenarios.json")


def test_estimate_scenarios_error_rates_are_ordered_optimistic_to_pessimistic(scen):
    rates = [scen["scenarios"][s]["physical_error_rate"] for s in ORDER]
    assert all(isinstance(r, (int, float)) and 0 < r < 0.1 for r in rates), rates
    assert rates == sorted(rates) and rates[0] < rates[-1], f"error rates {rates}"


@pytest.mark.parametrize("target", ref.TARGETS)
def test_estimate_scenarios_lower_error_rate_means_fewer_physical_qubits(scen, target):
    by = scen["targets"][target]["by_scenario"]
    phys = [by[s]["physical_qubits"] for s in ORDER]
    dist = [by[s]["code_distance"] for s in ORDER]
    assert phys == sorted(phys), f"{target}: physical qubits {dict(zip(ORDER, phys, strict=False))}"
    assert dist == sorted(dist), f"{target}: code distance {dict(zip(ORDER, dist, strict=False))}"


@pytest.mark.parametrize("target", ref.TARGETS)
def test_estimate_scenarios_logical_counts_do_not_depend_on_the_scenario(scen, target):
    by = scen["targets"][target]["by_scenario"]
    assert len({by[s]["logical_qubits"] for s in ORDER}) == 1, f"{target}: {by}"
    for s in ORDER:
        r = by[s]
        assert all(
            r[k] > 0 and math.isfinite(r[k])
            for k in ("logical_qubits", "physical_qubits", "runtime_seconds", "code_distance")
        )
        assert r["physical_qubits"] > r["logical_qubits"] * r["code_distance"], f"{target}/{s}"


def test_estimate_scenarios_runtime_does_not_fall_with_a_worse_cycle_time(scen):
    for t in ref.TARGETS:
        by = scen["targets"][t]["by_scenario"]
        rt = [by[s]["runtime_seconds"] for s in ORDER]
        assert rt == sorted(rt), f"{t}: runtime {dict(zip(ORDER, rt, strict=False))}"


def test_estimate_scenarios_sources_and_labels(scen):
    ids = {e["id"] for e in ref.literature()}
    for s in ORDER:
        sc = scen["scenarios"][s]
        assert sc["source_ids"] and set(sc["source_ids"]) <= ids, f"{s}: {sc['source_ids']}"
        assert sc["qec_scheme"] and sc["error_budget"]
    for t in ref.TARGETS:
        assert scen["targets"][t]["logical_source"], f"{t}: no logical_source"
    aes = scen["targets"]["aes128"]
    assert aes["peel_last_sbox"] is False
    if "toy" in str(aes["logical_source"]).lower() or "spn" in str(aes["logical_source"]).lower():
        assert aes.get("label") == "projection", "toy-SPN -> AES step must be labelled projection"


def test_estimate_calibration_covers_all_targets_and_every_row_cites_a_real_entry():
    cal = ref.load_json(ref.EST / "calibration.json")["comparisons"]
    ids = {e["id"] for e in ref.literature()}
    assert {r["target"] for r in cal} >= set(ref.TARGETS)
    for r in cal:
        tag = f"{r['target']}/{r['estimator']}/{r['quantity']}"
        assert r["literature_id"] in ids, f"{tag}: unknown literature id"
        assert r["ours"] > 0 and r["literature_value"] > 0 and r["ratio"] > 0, tag


def test_estimate_literature_schema_and_coverage():
    entries = ref.literature()
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate literature ids"
    for e in entries:
        assert {
            "id",
            "target",
            "quantity",
            "value",
            "units",
            "assumptions",
            "source_url",
            "locator",
            "retrieved",
        } <= set(e), f"{e.get('id')}: {e.keys()}"
        assert e["target"] in (*ref.TARGETS, "other"), e["id"]
        assert str(e["source_url"]).startswith("https://"), e["id"]
        assert str(e["locator"]).strip(), e["id"]
        retrieved = (
            e["retrieved"]
            if isinstance(e["retrieved"], dt.date)
            else dt.date.fromisoformat(str(e["retrieved"]))
        )
        assert retrieved <= dt.date.today(), f"{e['id']}: retrieved in the future"
    assert set(ref.TARGETS) <= {e["target"] for e in entries}


def test_estimate_every_literature_entry_is_fact_checked_and_nothing_stale():
    entries = ref.literature()
    fc = ref.load_json(ref.FACTCHECK)
    yaml_ids = {e["id"] for e in entries}
    assert set(fc) == yaml_ids, (
        f"factcheck ids differ: only in yaml {yaml_ids - set(fc)}, "
        f"only in factcheck {set(fc) - yaml_ids}"
    )
    for eid, r in fc.items():
        assert r["status"] == "verified", f"{eid}: {r['status']} ({r.get('note')})"
        assert str(r["checked_url"]).startswith("https://") and str(r["locator"]).strip(), eid
        assert str(r.get("note", "")).strip(), f"{eid}: no note saying what was compared"
