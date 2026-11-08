"""ECC-256 inputs: the newest verified on-family estimate, older ones kept as history only.

Human instruction (2026-11-08, IMPROVE round 2): ECC-256 logical counts come from the newest
verified estimate that gives BOTH logical qubits and a Toffoli count; Roetteler 2017 and Litinski
2023 stay as history, marked `superseded_by`; the PRX Quantum paper and arXiv 2603.28846 are ONE
work, never counted twice. The selection is re-derived here from literature.yaml, not read from
scenarios.json.
"""

from __future__ import annotations

import pytest

from tests.phase4 import reference as ref


@pytest.fixture(scope="module")
def lit() -> dict:
    return {e["id"]: e for e in ref.literature()}


@pytest.fixture(scope="module")
def src() -> dict:
    return ref.load_json(ref.EST / "scenarios.json")["targets"]["ecc256"]["logical_source"]


def _selected(lit):
    """Newest on-family ecc256 estimate with both a logical-qubit and a Toffoli entry."""
    cands = []
    for i, e in lit.items():
        if e["target"] != "ecc256" or e["quantity"] != "logical_qubits" or e.get("superseded_by"):
            continue
        if i.endswith("_alt"):
            continue  # the second circuit variant of the same paper
        stem = i.replace("logical_qubits", "toffoli")
        toffoli = lit.get(stem) or lit.get(i.replace("logical_qubits", "toffoli_count"))
        if toffoli is None:
            continue
        text = e["assumptions"].lower()
        if "not on any scenario" in text or "logical level only" in text:
            continue  # off-family: no hardware assumptions at all
        cands.append((e["year"], i, toffoli["id"]))
    assert cands, "no candidate ECC-256 estimate with both logical qubits and Toffoli count"
    return max(cands)


def test_timeline_ecc_logical_source_is_the_newest_verified_on_family_estimate(lit, src):
    _, qid, tid = _selected(lit)
    assert src["literature_ids"] == [qid, tid], src["literature_ids"]
    fc = ref.factcheck()
    for i in src["literature_ids"]:
        assert fc[i]["status"] == "verified", i
        assert not lit[i].get("superseded_by"), f"{i} is marked superseded but feeds the scenarios"
    assert src["logical_counts"]["numQubits"] == lit[qid]["value"]
    assert src["logical_counts"]["cczCount"] == lit[tid]["value"]


def test_timeline_ecc_logical_inputs_are_labelled_upper_bounds(lit, src):
    assert src["bound"] == "upper"
    for i in src["literature_ids"]:
        assert lit[i].get("bound") == "upper", i
        assert "upper bound" in lit[i]["units"].lower(), i


def test_timeline_older_ecc_estimates_are_history_and_marked_superseded(lit, src):
    assert {h["source"].split()[0] for h in src["history"]} >= {"Roetteler", "Litinski"}
    for h in src["history"]:
        for i in h["literature_ids"]:
            e = lit[i]
            assert e.get("superseded_by"), f"{i}: history entry without superseded_by"
            assert e["superseded_by"].startswith("google2026_"), i
            assert e["superseded_by"] in lit, f"{i}: superseded_by names no entry"
            assert lit[e["superseded_by"]]["year"] == 2026, i  # the newer work
            assert h["superseded_by"] in lit, f"history row {h['source']}: unknown superseded_by"
            assert ref.factcheck()[i]["status"] == "verified", i
    # nothing in history feeds the scenario
    assert not (
        {i for h in src["history"] for i in h["literature_ids"]} & set(src["literature_ids"])
    )


def test_timeline_roetteler_is_history_only_nothing_downstream_uses_its_numbers(lit):
    sup = {i for i, e in lit.items() if i.startswith("roetteler2017") and e.get("superseded_by")}
    assert sup == {i for i in lit if i.startswith("roetteler2017")}, "every Roetteler id superseded"
    est = (ref.EST / "scenarios.json").read_text()
    tl = (ref.RESULTS / "timeline.json").read_text()
    for i in sup:
        assert i not in tl, f"{i} appears in timeline.json"
    assert "roetteler2017" in est, "kept as history in scenarios.json"
    qdk_ecc = ref.load_json(ref.EST / "scenarios.json")["targets"]["ecc256"]["by_scenario"]
    for row in qdk_ecc.values():
        assert row["logical_qubits"] != lit["roetteler2017_logical_qubits_p256"]["value"]


def test_timeline_prx_quantum_and_arxiv_are_one_source_never_counted_twice(lit):
    google = {i: e for i, e in lit.items() if i.startswith("google2026_")}
    assert google, "no google2026 entries"
    for i, e in google.items():
        assert e["source_url"] == "https://arxiv.org/abs/2603.28846", i
    published = [i for i, e in google.items() if e.get("also_published_as")]
    assert sorted(published) == sorted(google), (
        "put the PRX cross-reference on every google2026 entry"
    )
    for i in published:
        text = google[i]["also_published_as"].lower()
        assert "metadata match" in text and "no registered link" in text, i
        assert "never two independent results" in text, i
    # no second entry whose source is the journal: one work, one source
    for i, e in lit.items():
        url = str(e["source_url"]).lower()
        assert "prxquantum" not in url and "j3xf-bw18" not in url, (
            f"{i} cites the journal as its own source"
        )
    # one value per (quantity, variant): no duplicated figure under two ids
    seen = {}
    for i, e in google.items():
        key = (e["quantity"], e["value"], e.get("bound"))
        assert key not in seen, f"{i} repeats {seen[key]}"
        seen[key] = i


def test_timeline_chevignard_is_context_only_and_never_feeds_a_scenario(lit, src):
    ids = {i for i in lit if i.startswith("chevignard2026")}
    assert ids == {"chevignard2026_logical_qubits_ecc256", "chevignard2026_toffoli_per_run_ecc256"}
    for i in ids:
        assert not lit[i].get("feeds"), i
        assert i not in src["literature_ids"], i
    ctx = [i for c in src["context"] for i in c["literature_ids"]]
    assert set(ids) <= set(ctx)
    assert (
        "logical level only" in lit["chevignard2026_logical_qubits_ecc256"]["assumptions"].lower()
    )


def test_timeline_the_ecc_logical_qubit_count_matches_the_toffoli_counts_variant(lit):
    """The 1200-logical figure goes with 90M Toffoli (the other variant: 1450 with 70M); the pair
    must never be crossed."""
    assert lit["google2026_logical_qubits_ecc256"]["value"] == 1200
    assert lit["google2026_toffoli_ecc256"]["value"] == 9e7
    assert lit["google2026_logical_qubits_ecc256_alt"]["value"] == 1450
    assert lit["google2026_toffoli_ecc256_alt"]["value"] == 7e7
