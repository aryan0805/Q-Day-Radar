"""The real hardware batch, checked against its own raw files. Reads results/, writes nothing.

These tests need the real data (results/hardware/<BATCH>, results/analysis/phase2/<BATCH>,
results/budget.json); without it they FAIL rather than skip, because "the audit has no data" must
not look like a pass. Every number is recomputed here from the raw counts with
tests/phase2/reference.py (independent of quantum/run/stats.py) and, for M3, with a plain
tensor-product matrix inverse instead of the mthree package the analysis uses.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import reduce

import numpy as np
import pytest
from qiskit import qasm3

from quantum.circuits import registry
from quantum.run import hardware
from quantum.run.noisy import ideal_distribution
from tests.phase2 import reference as ref
from tests.phase2.guards import ROOT

BATCH = "batch-20261108T044751Z"
HW = ROOT / "results" / "hardware" / BATCH
ANALYSIS = ROOT / "results" / "analysis" / "phase2" / BATCH
N_JOBS = 33
SHOTS = 4096
CAP_SECONDS = 540.0


def jload(path):
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def plan():
    return jload(HW / "plan.json")


@pytest.fixture(scope="module")
def raw():
    return {i: jload(HW / "jobs" / f"{i}.json") for i in range(N_JOBS)}


@pytest.fixture(scope="module")
def ana():
    return {i: jload(ANALYSIS / f"{i}.json") for i in range(N_JOBS)}


def ts(value):
    return datetime.fromisoformat(value)


def success_of(name, counts):
    n = sum(counts.values())
    return sum(v for b, v in counts.items() if registry.SUCCESS_FN[name](b)) / n


def is_experiment(job):
    return job["config"] != "m3_cal"


# ---- completeness and pre-registration -----------------------------------------------------------


def test_every_planned_job_ran_and_was_analysed_once(plan, raw, ana):
    assert [j["index"] for j in plan["jobs"]] == list(range(N_JOBS))
    assert {r["status"] for r in raw.values()} == {"DONE"}
    assert not any(r["usage_unknown"] for r in raw.values())
    assert sorted(p.stem for p in ANALYSIS.glob("*.json")) == sorted(str(i) for i in range(N_JOBS))
    for i, job in enumerate(plan["jobs"]):
        assert raw[i]["name"] == job["name"] and raw[i]["config"] == job["config"]
        assert ana[i]["name"] == job["name"] and ana[i]["job_id"] == raw[i]["job_id"]
        assert raw[i]["isa_sha256"] == job["isa_sha256"] == ana[i]["isa_sha256"]
        assert raw[i]["backend"] == plan["backend"] == "ibm_kingston"
        assert raw[i]["shots"] == SHOTS == sum(raw[i]["counts"].values())


def test_approval_predictions_were_on_file_before_every_job_was_created(plan, raw):
    approval = jload(HW / "approval.json")
    assert approval["approved_by"] == "human"
    assert approval["plan_sha256"] == hardware.sha256_hex((HW / "plan.json").read_bytes()), (
        "plan.json (with its predictions) is byte-for-byte the plan that was approved"
    )
    resumes = [json.loads(x) for x in (HW / "resumes.jsonl").read_text().splitlines()]
    assert len(resumes) == 1 and resumes[0]["approved_by"] == "human"
    assert resumes[0]["plan_sha256"] == approval["plan_sha256"]
    sent_on_resume = set(resumes[0]["indices"])
    for i, r in raw.items():
        boundary = resumes[0]["resumed_at"] if i in sent_on_resume else approval["approved_at"]
        assert ts(r["created"]) > ts(boundary), f"job {i} was created before its approval"
    first = jload(HW / "stopped.json")
    assert (first["reason"], first["code"], first["index"]) == ("submit_failed", 6, 4)
    assert "1217" in first["message"]
    assert sent_on_resume == set(range(4, N_JOBS)), "the resume sent exactly what never went out"
    assert not (HW / "SUPERSEDED.md").exists()


def test_every_job_has_a_prediction_and_the_analysis_quotes_it_unchanged(plan, ana):
    for job in plan["jobs"]:
        pred = job["prediction"]
        assert sum(pred["counts"].values()) == SHOTS
        if is_experiment(job):
            a = ana[job["index"]]
            assert a["predicted_success"] == pred["success_probability"]
            assert a["predicted_success"] == pytest.approx(success_of(job["name"], pred["counts"]))


def test_budget_ledger_has_each_job_once_and_equals_the_measured_usage(raw):
    entries = jload(ROOT / "results" / "budget.json")["entries"]
    by_id = {e["job_id"]: e for e in entries}
    assert len(by_id) == len(entries), "no job id twice"
    assert {r["job_id"] for r in raw.values()} <= set(by_id)
    for r in raw.values():
        assert by_id[r["job_id"]]["seconds"] == pytest.approx(r["usage_seconds"])
    total = sum(r["usage_seconds"] for r in raw.values())
    assert total == pytest.approx(115.0), "the figure the human compares with the Instances page"
    assert sum(e["seconds"] for e in entries) <= CAP_SECONDS


def test_no_job_used_more_than_its_estimate_and_the_plan_stayed_under_the_cap(plan, raw):
    assert plan["total_estimated_seconds"] <= 300.0
    for job in plan["jobs"]:
        assert 0 < raw[job["index"]]["usage_seconds"] <= job["estimated_seconds"]


# ---- the same circuit really was the same circuit ------------------------------------------------


def test_repeats_and_configs_of_one_circuit_have_equal_content(plan):
    by_name = {}
    for job in plan["jobs"]:
        by_name.setdefault(job["name"], []).append(job)
    for name, jobs in by_name.items():
        assert len({j["content_sha256"] for j in jobs}) == 1, name
        loaded = [
            hardware.load_qpy((HW / "circuits" / f"{j['index']}.qpy").read_bytes()) for j in jobs
        ]
        texts = {qasm3.dumps(c) for c in loaded}
        assert len(texts) == 1, f"{name}: loaded circuits differ"
    pilots = [j for j in plan["jobs"] if j["name"] == "shor15_textbook"][:3]
    assert [j["config"] for j in pilots] == ["raw", "dd", "dd_twirl"]
    assert len({j["content_sha256"] for j in pilots}) == 1, "jobs 1-3 are one circuit"


# ---- the analysis equals an independent recomputation --------------------------------------------


def test_analysis_statistics_recompute_from_the_raw_counts(plan, raw, ana):
    for job in plan["jobs"]:
        i, name, a = job["index"], job["name"], ana[job["index"]]
        counts = raw[i]["counts"]
        if not is_experiment(job):
            target = "1" if name.endswith("ones") else "0"
            hits = sum(v for b, v in counts.items() if set(b) <= {target})
            assert a["success_probability"] == pytest.approx(hits / SHOTS)
            assert a["wilson_95"] == pytest.approx(ref.wilson(hits, SHOTS))
            continue
        meta = jload(ROOT / "results" / "metrics" / f"{name}.json")
        hits = sum(v for b, v in counts.items() if registry.SUCCESS_FN[name](b))
        s = hits / SHOTS
        assert a["success_probability"] == pytest.approx(s), i
        assert a["wilson_95"] == pytest.approx(ref.wilson(hits, SHOTS)), i
        assert a["chance_baseline"] == pytest.approx(meta["chance_baseline"])
        assert a["theoretical_success"] == pytest.approx(meta["theoretical_success"])
        assert a["normalized_score"] == pytest.approx(
            ref.normalized(s, meta["theoretical_success"], meta["chance_baseline"])
        ), i
        assert a["hellinger_vs_ideal"] == pytest.approx(
            ref.hellinger_fidelity(ref.to_probs(counts), ideal_distribution(name)), abs=1e-9
        ), i
        assert a["hellinger_vs_prediction"] == pytest.approx(
            ref.hellinger_fidelity(ref.to_probs(counts), ref.to_probs(job["prediction"]["counts"])),
            abs=1e-9,
        ), i
        lo, hi = ref.wilson(round(job["prediction"]["success_probability"] * SHOTS), SHOTS)
        assert a["prediction_wilson_95"] == pytest.approx([lo, hi])
        assert a["predicted_vs_chance"] == (
            "at chance" if lo <= meta["chance_baseline"] else "signal"
        )


def test_every_hellinger_value_is_in_the_unit_interval(ana):
    for a in ana.values():
        for key in ("hellinger_vs_ideal", "hellinger_vs_prediction"):
            if a.get(key) is not None:
                assert 0.0 <= a[key] <= 1.0, (a["index"], key)
        if isinstance(a.get("m3"), dict):
            assert 0.0 <= a["m3"]["hellinger_vs_ideal"] <= 1.0


# ---- raw and mitigated results are kept apart ----------------------------------------------------


def test_top_level_numbers_are_raw_and_mitigated_ones_sit_in_their_own_block(plan, raw, ana):
    for job in plan["jobs"]:
        a = ana[job["index"]]
        if not is_experiment(job):
            assert "m3" not in a
            continue
        assert a["success_probability"] == pytest.approx(
            success_of(job["name"], raw[job["index"]]["counts"])
        ), "the top-level value is the raw one"
        if job["index"] == 0:
            continue
        m3 = a["m3"]
        assert isinstance(m3, dict) and "mthree" in m3["method"]
        assert m3["success_probability"] != a["success_probability"], "kept as a separate block"


def test_pilot_0_the_dynamic_circuit_has_no_m3_block_and_is_labelled_predicted_at_chance(ana, plan):
    a = ana[0]
    assert (a["name"], a["config"]) == ("shor15_beauregard", "raw")
    assert a["m3"] is None and a["m3_reason"] == "measured qubits not calibrated"
    assert a["predicted_vs_chance"] == "at chance"
    assert a["prediction_wilson_95"][0] <= a["chance_baseline"]
    measured = set(plan["jobs"][0]["measured_qubits"])
    assert not measured <= set(plan["m3_qubits"]), "it measures qubits the calibration never saw"


def readout_matrices(plan, raw):
    """Per-qubit [[P(0|0), P(0|1)], [P(1|0), P(1|1)]], computed here straight from the counts."""
    qubits = plan["jobs"][4]["measured_qubits"]
    assert plan["jobs"][4]["name"] == "m3_cal_zeros" and plan["jobs"][32]["name"] == "m3_cal_ones"
    zeros, ones = raw[4]["counts"], raw[32]["counts"]
    out = {}
    for pos, q in enumerate(qubits):
        flip_up = sum(v for b, v in zeros.items() if b[::-1][pos] == "1") / SHOTS
        flip_down = sum(v for b, v in ones.items() if b[::-1][pos] == "0") / SHOTS
        out[q] = np.array([[1 - flip_up, flip_down], [flip_up, 1 - flip_down]])
    return out


def test_m3_calibration_matrices_undo_their_own_calibration_data(plan, raw):
    mats = readout_matrices(plan, raw)
    qubits = plan["jobs"][4]["measured_qubits"]
    assert qubits == plan["m3_qubits"]
    for pos, q in enumerate(qubits):
        for counts, prepared in ((raw[4]["counts"], 0), (raw[32]["counts"], 1)):
            p1 = sum(v for b, v in counts.items() if b[::-1][pos] == "1") / SHOTS
            corrected = np.linalg.inv(mats[q]) @ np.array([1 - p1, p1])
            assert corrected[prepared] == pytest.approx(1.0), (q, prepared)
        assert mats[q].sum(axis=0) == pytest.approx([1.0, 1.0])


def test_m3_success_matches_an_independent_tensor_inverse_within_0p01(plan, raw, ana):
    mats = readout_matrices(plan, raw)
    for job in [*plan["jobs"][1:4], *plan["jobs"][5:32]]:  # every job but pilot 0 and the cal jobs
        qubits = job["measured_qubits"]
        # bit i (from the right) is read from qubits[i]: the leftmost kron factor is the last bit
        full = reduce(np.kron, [mats[q] for q in reversed(qubits)])
        counts = raw[job["index"]]["counts"]
        n = len(qubits)
        p = np.zeros(2**n)
        for b, v in counts.items():
            p[int(b, 2)] = v / SHOTS
        quasi = np.linalg.solve(full, p)
        mitigated = sum(
            quasi[x] for x in range(2**n) if registry.SUCCESS_FN[job["name"]](format(x, f"0{n}b"))
        )
        assert ana[job["index"]]["m3"]["success_probability"] == pytest.approx(
            mitigated, abs=0.01
        ), f"job {job['index']} {job['name']}/{job['config']}"


# ---- repeats, drift and the mitigation claims ----------------------------------------------------


def groups(plan, raw):
    out = {}
    for job in plan["jobs"]:
        if is_experiment(job):
            out.setdefault((job["name"], job["config"]), []).append(job["index"])
    return out


def hits_of(plan_raw, idxs, name):
    hits = [
        sum(v for b, v in plan_raw[i]["counts"].items() if registry.SUCCESS_FN[name](b))
        for i in idxs
    ]
    return hits


def overlaps(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def test_summary_matches_a_recomputation_from_the_raw_counts(plan, raw):
    summary = jload(ANALYSIS.parent / f"summary-{BATCH}.json")
    entries = summary["entries"]
    expected_drift = set()
    for (name, cfg), idxs in groups(plan, raw).items():
        hits = hits_of(raw, idxs, name)
        e = entries[f"{name}/{cfg}"]
        assert [r["index"] for r in e["repeats"]] == idxs
        assert [r["success"] for r in e["repeats"]] == pytest.approx([h / SHOTS for h in hits])
        assert e["wilson_95"] == pytest.approx(ref.wilson(sum(hits), SHOTS * len(idxs)))
        assert e["repeat_spread"] == pytest.approx((max(hits) - min(hits)) / SHOTS)
        intervals = [ref.wilson(h, SHOTS) for h in hits]
        drifted = any(
            not overlaps(a, b) for k, a in enumerate(intervals) for b in intervals[k + 1 :]
        )
        assert e["drift_beyond_shot_noise"] is drifted, f"{name}/{cfg}"
        if drifted:
            expected_drift.add(f"{name}/{cfg}")
    assert {k for k, e in entries.items() if e["drift_beyond_shot_noise"]} == expected_drift
    assert expected_drift, "the audit's drift finding stands only if something drifted"


def test_mitigation_comparisons_recompute_from_the_raw_counts_and_resolve_the_expected_rows(
    plan, raw
):
    summary = jload(ANALYSIS.parent / f"summary-{BATCH}.json")
    g = groups(plan, raw)
    resolved_keys = set()
    n_comparisons = 0
    for (name, cfg), idxs in g.items():
        if cfg == "raw" or name == "shor15_beauregard":
            continue
        n_comparisons += 1
        raw_hits = hits_of(raw, g[(name, "raw")], name)
        hits = hits_of(raw, idxs, name)
        n_r, n_m = SHOTS * len(raw_hits), SHOTS * len(hits)
        diff = sum(hits) / n_m - sum(raw_hits) / n_r
        lo_r, hi_r = ref.wilson(sum(raw_hits), n_r)
        lo_m, hi_m = ref.wilson(sum(hits), n_m)
        half = max((hi_r - lo_r) / 2, (hi_m - lo_m) / 2)
        spread = max((max(h) - min(h)) / SHOTS for h in (hits, raw_hits))
        c = summary["comparisons"][f"{name}: {cfg} - raw"]
        assert c["difference"] == pytest.approx(diff)
        assert c["wilson_half_width_max"] == pytest.approx(half)
        assert c["repeat_spread_max"] == pytest.approx(spread)
        assert c["gain_resolved"] is (diff > half and diff > spread), f"{name} {cfg}"
        chance = registry.build_circuit(name).metadata["chance_baseline"]
        assert c["raw_wilson_lo_above_chance"] is (lo_r > chance)
        assert c["mitigated_wilson_lo_above_chance"] is (lo_m > chance)
        if c["gain_resolved"]:
            resolved_keys.add(f"{name}: {cfg} - raw")
    assert n_comparisons == len(summary["comparisons"]) == 10
    # what the rule resolves today: three rows, all for circuits at the chance floor
    assert resolved_keys == {
        "grover_present_k4: dd - raw",
        "grover_present_k4: dd_twirl - raw",
        "grover_present_k5: dd - raw",
    }
    for key in resolved_keys:
        assert not summary["comparisons"][key]["raw_wilson_lo_above_chance"], key
    # and no gain for the circuits that carry a real signal
    for name in ("shor15_textbook", "grover_present_k2", "grover_present_k3"):
        for cfg in ("dd", "dd_twirl"):
            assert not summary["comparisons"][f"{name}: {cfg} - raw"]["gain_resolved"], name


def test_the_mitigation_statement_says_it_is_exploratory():
    summary = jload(ANALYSIS.parent / f"summary-{BATCH}.json")
    statement = summary["mitigation_statement"].lower()
    for word in (
        "exploratory",
        "set after the data",
        "10 comparisons",
        "2 repeats",
        "no multiple-comparison correction",
    ):
        assert word in statement, f"the statement must say {word!r}: rule set after the data"


def test_every_number_quoted_in_the_mitigation_statement_recomputes_from_the_raw_counts(plan, raw):
    summary = jload(ANALYSIS.parent / f"summary-{BATCH}.json")
    assert summary["comparisons_exploratory"] is True
    assert summary["n_comparisons"] == len(summary["comparisons"]) == 10
    statement = summary["mitigation_statement"]
    g = groups(plan, raw)
    quoted = {  # (name, config) -> the pieces of the statement that quote it
        ("grover_present_k4", "dd"): True,
        ("grover_present_k5", "dd"): True,
        ("grover_present_k4", "dd_twirl"): True,
    }
    for name, cfg in quoted:
        raw_hits = hits_of(raw, g[(name, "raw")], name)
        hits = hits_of(raw, g[(name, cfg)], name)
        diff = sum(hits) / (SHOTS * len(hits)) - sum(raw_hits) / (SHOTS * len(raw_hits))
        lo = ref.wilson(sum(hits), SHOTS * len(hits))[0]
        assert f"{diff:+.3f}" in statement, f"{name} {cfg}: difference {diff:+.3f}"
        assert f"lo {lo:.3f}" in statement or f"lo {lo:.4f}" in statement, f"{name} {cfg}: {lo}"
    for name in ("grover_present_k4", "grover_present_k5"):
        chance = registry.build_circuit(name).metadata["chance_baseline"]
        assert f"{chance:.4f}" in statement or f"{chance:.3f}" in statement, name
