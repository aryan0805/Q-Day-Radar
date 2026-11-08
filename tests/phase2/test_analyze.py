"""scripts/analyze_hardware.py: Hellinger values, statistics, M3 wiring, nothing dropped.

Batches are hand-built (plan.json + raw jobs/*.json) so every expected number is computed here,
independently, with tests/phase2/reference.py; the end-to-end test then runs plan -> submit (fake
service) -> analyze.
"""

import json
import math

import numpy as np
import pytest

pytest.importorskip("scripts.analyze_hardware")
from quantum.circuits import registry  # noqa: E402
from scripts.analyze_hardware import analyze_batch  # noqa: E402
from tests.phase2 import reference as ref  # noqa: E402
from tests.phase2.harness import raw_files, read_json, snapshot  # noqa: E402

NAME = "grover_present_k2"
KEY = format(registry.GROVER_DEMO_KEYS[2], "02b")  # '10': clbit 1 = 1, clbit 0 = 0
THEORY = registry.THEORY_FN[NAME]()
CHANCE = registry.build_circuit(NAME).metadata["chance_baseline"]
QUBITS = [5, 9]  # clbit 0 -> physical qubit 5, clbit 1 -> physical qubit 9
SHOTS = 1000
PRED = {"10": 900, "00": 100}
SEED_FIELDS = {
    "index", "job_id", "name", "config", "success_probability", "wilson_95", "normalized_score",
    "hellinger_vs_ideal", "hellinger_vs_prediction",
}  # fmt: skip


def raw_record(index, name, config, counts, *, status="DONE", usage=1.0):
    return {
        "index": index, "job_id": f"job-{index}", "backend": "fake_backend", "name": name,
        "config": config, "isa_sha256": f"h{index}", "shots": SHOTS, "counts": counts,
        "usage_seconds": usage, "created": "2026-11-08T12:00:01+00:00",
        "finished": "2026-11-08T12:00:09+00:00", "status": status,
        "error": None if status == "DONE" else "boom", "usage_unknown": False,
    }  # fmt: skip


def plan_job(index, name, config, kind="generic"):
    return {
        "index": index, "name": name, "kind": kind, "config": config, "pilot": index < 2,
        "shots": SHOTS, "isa_sha256": f"h{index}", "estimated_seconds": 2.0,
        "measured_qubits": QUBITS,
        "prediction": {"model": "m", "counts": PRED, "success_probability": 0.9},
    }  # fmt: skip


def build(tmp_path, jobs, raws):
    batch = tmp_path / "hw" / "ana"
    (batch / "jobs").mkdir(parents=True)
    plan = {"batch_id": "ana", "created": "x", "backend": "fake_backend",
            "total_estimated_seconds": 2.0 * len(jobs), "jobs": jobs}  # fmt: skip
    (batch / "plan.json").write_text(json.dumps(plan))
    for r in raws:
        (batch / "jobs" / f"{r['index']}.json").write_text(json.dumps(r))
    metrics = tmp_path / "metrics"
    metrics.mkdir()
    (metrics / f"{NAME}.json").write_text(
        json.dumps({"theoretical_success": THEORY, "chance_baseline": CHANCE})
    )
    return batch, metrics, tmp_path / "analysis"


@pytest.fixture
def basic(tmp_path):
    jobs = [
        plan_job(0, NAME, "raw"),
        plan_job(1, NAME, "dd"),
        plan_job(2, "m3_cal_zeros", "m3_cal", "calibration"),
        plan_job(3, "m3_cal_ones", "m3_cal", "calibration"),
        plan_job(4, NAME, "raw"),
    ]
    raws = [
        raw_record(0, NAME, "raw", {"10": 800, "00": 200}),
        raw_record(1, NAME, "dd", {"10": 700, "00": 150, "11": 150}),
        raw_record(2, "m3_cal_zeros", "m3_cal", {"00": 960, "01": 15, "10": 20, "11": 5}),
        raw_record(3, "m3_cal_ones", "m3_cal", {"11": 940, "01": 25, "10": 30, "00": 5}),
        raw_record(4, NAME, "raw", None, status="ERROR"),
    ]
    batch, metrics, out = build(tmp_path, jobs, raws)
    paths = analyze_batch(batch, out, metrics_dir=metrics)
    return batch, metrics, out, paths, {p.stem: read_json(p) for p in paths}


# ---- one file per job, nothing dropped -------------------------------------------------------


def test_analyze_writes_one_file_per_planned_job_with_the_agreed_fields(basic):
    batch, _, out, paths, files = basic
    assert sorted(files) == ["0", "1", "2", "3", "4"]
    assert all(p.parent == out / "ana" for p in paths)
    for rec in files.values():
        assert SEED_FIELDS <= set(rec)


def test_analyze_raises_for_a_planned_job_without_a_raw_file(tmp_path):
    jobs = [plan_job(0, NAME, "raw"), plan_job(1, NAME, "raw")]
    batch, metrics, out = build(tmp_path, jobs, [raw_record(0, NAME, "raw", {"10": 1000})])
    with pytest.raises(FileNotFoundError):
        analyze_batch(batch, out, metrics_dir=metrics)


def test_analyze_failed_job_still_gets_a_file_with_null_values(basic):
    failed = basic[4]["4"]
    assert failed["status"] == "ERROR"
    for key in ("success_probability", "wilson_95", "normalized_score",
                "hellinger_vs_ideal", "hellinger_vs_prediction"):  # fmt: skip
        assert failed[key] is None, key
    assert "m3" not in failed


def test_analyze_does_not_touch_the_raw_batch_directory(tmp_path):
    jobs = [plan_job(0, NAME, "raw")]
    raws = [raw_record(0, NAME, "raw", {"10": 800, "00": 200})]
    batch, metrics, out = build(tmp_path, jobs, raws)
    before = snapshot(batch)
    analyze_batch(batch, out, metrics_dir=metrics)
    assert snapshot(batch) == before
    assert list(out.rglob("*.json")) and not list(batch.rglob("analysis*"))


# ---- numbers, recomputed independently --------------------------------------------------------


def test_analyze_statistics_match_the_independent_reference(basic):
    rec = basic[4]["0"]  # 800 of 1000 at the key
    assert rec["success_probability"] == pytest.approx(0.8)
    lo, hi = ref.wilson(800, SHOTS)
    assert rec["wilson_95"] == pytest.approx([lo, hi], abs=1e-9)
    assert rec["normalized_score"] == pytest.approx(ref.normalized(0.8, THEORY, CHANCE))
    assert rec["theoretical_success"] == pytest.approx(THEORY)
    assert rec["chance_baseline"] == pytest.approx(CHANCE)
    assert rec["predicted_success"] == 0.9


def test_analyze_hellinger_vs_ideal_is_the_mass_on_the_key_for_a_point_mass_ideal(basic):
    # ideal for grover k2 is all mass on the key, so fidelity = (sqrt(p_key * 1))^2 = p_key
    assert THEORY == pytest.approx(1.0)
    assert basic[4]["0"]["hellinger_vs_ideal"] == pytest.approx(0.8, abs=1e-6)
    assert basic[4]["1"]["hellinger_vs_ideal"] == pytest.approx(0.7, abs=1e-6)


def test_analyze_hellinger_vs_prediction_uses_the_pre_registered_prediction(basic):
    counts = {"10": 800, "00": 200}
    want = ref.hellinger_fidelity(ref.to_probs(counts), ref.to_probs(PRED))
    assert basic[4]["0"]["hellinger_vs_prediction"] == pytest.approx(want, abs=1e-12)
    third = {"10": 700, "00": 150, "11": 150}
    want = ref.hellinger_fidelity(ref.to_probs(third), ref.to_probs(PRED))
    assert basic[4]["1"]["hellinger_vs_prediction"] == pytest.approx(want, abs=1e-12)


def test_analyze_every_hellinger_value_is_in_the_unit_interval(basic):
    for rec in basic[4].values():
        for key in ("hellinger_vs_ideal", "hellinger_vs_prediction"):
            if rec[key] is not None:
                assert 0.0 <= rec[key] <= 1.0


def test_analyze_calibration_jobs_report_the_all_zero_or_all_one_fraction(basic):
    zeros, ones = basic[4]["2"], basic[4]["3"]
    assert zeros["success_probability"] == pytest.approx(0.96)
    assert ones["success_probability"] == pytest.approx(0.94)
    assert zeros["wilson_95"] == pytest.approx(list(ref.wilson(960, SHOTS)), abs=1e-9)
    assert zeros["normalized_score"] is None and zeros["hellinger_vs_ideal"] is None


# ---- raw and mitigated are kept apart ------------------------------------------------------------


def test_analyze_m3_block_comes_from_the_batch_calibration_and_only_for_experiment_jobs(basic):
    files = basic[4]
    for i in ("0", "1"):
        m3 = files[i]["m3"]
        assert 0.0 <= m3["success_probability"] <= 1.0 and "normalized_score" in m3
        assert "hellinger_vs_ideal" in m3
    assert "m3" not in files["2"] and "m3" not in files["3"]


def test_analyze_top_level_numbers_are_raw_whether_or_not_matrices_are_given(tmp_path):
    jobs = [plan_job(0, NAME, "raw")]
    raws = [raw_record(0, NAME, "raw", {"10": 800, "00": 200})]
    batch, metrics, out = build(tmp_path, jobs, raws)
    plain = read_json(analyze_batch(batch, out / "a", metrics_dir=metrics)[0])
    mats = {5: np.array([[0.98, 0.02], [0.02, 0.98]]), 9: np.array([[0.9, 0.1], [0.1, 0.9]])}
    mitigated = read_json(analyze_batch(batch, out / "b", metrics_dir=metrics, m3_matrices=mats)[0])
    for key in ("success_probability", "wilson_95", "normalized_score", "hellinger_vs_ideal"):
        assert mitigated[key] == plain[key], f"{key} must stay the RAW value"
    assert "m3" not in plain or plain["m3"] != mitigated["m3"]
    assert mitigated["m3"]["success_probability"] != plain["success_probability"]


def test_analyze_m3_correction_recovers_a_known_state_with_asymmetric_qubit_errors(tmp_path):
    # True state: clbit0 (qubit 5) = 0 and clbit1 (qubit 9) = 1, i.e. the key '10'. Qubit 5 reads
    # wrong 2% of the time, qubit 9 reads wrong 10% of the time. Exact expected counts, 1e6 shots.
    e5, e9, n = 0.02, 0.10, 1_000_000
    counts = {}
    for b1 in (0, 1):
        for b0 in (0, 1):
            p9 = 1 - e9 if b1 == 1 else e9
            p5 = 1 - e5 if b0 == 0 else e5
            counts[f"{b1}{b0}"] = round(n * p9 * p5)
    raw_success = counts[KEY] / n
    assert raw_success == pytest.approx(0.882)

    def run(matrices, label):
        jobs = [plan_job(0, NAME, "raw")]
        jobs[0]["shots"] = n
        rec = raw_record(0, NAME, "raw", counts)
        rec["shots"] = n
        batch, metrics, out = build(tmp_path / label, jobs, [rec])
        return read_json(analyze_batch(batch, out, metrics_dir=metrics, m3_matrices=matrices)[0])

    right = {5: np.array([[1 - e5, e5], [e5, 1 - e5]]), 9: np.array([[1 - e9, e9], [e9, 1 - e9]])}
    swapped = {5: right[9], 9: right[5]}  # the qubits crossed over
    good, bad = run(right, "right"), run(swapped, "swapped")
    assert good["success_probability"] == pytest.approx(raw_success, abs=1e-6), "raw untouched"
    assert good["m3"]["success_probability"] == pytest.approx(1.0, abs=2e-3)
    assert bad["m3"]["success_probability"] < 0.995, "crossed qubits must not look corrected"
    assert good["m3"]["success_probability"] > bad["m3"]["success_probability"]


def test_analyze_has_no_m3_block_when_the_matrices_do_not_cover_the_measured_qubits(tmp_path):
    jobs = [plan_job(0, NAME, "raw")]
    raws = [raw_record(0, NAME, "raw", {"10": 800, "00": 200})]
    batch, metrics, out = build(tmp_path, jobs, raws)
    other = {100: np.eye(2), 101: np.eye(2)}
    rec = read_json(analyze_batch(batch, out, metrics_dir=metrics, m3_matrices=other)[0])
    assert rec["m3"] is None, "a correction for the wrong qubits must not be reported"
    assert rec["m3_reason"] == "measured qubits not calibrated"
    assert rec["success_probability"] == pytest.approx(0.8), "raw numbers are untouched"


def test_analyze_never_applies_a_partial_m3_correction(tmp_path):
    """Only physical qubit 5 of the measured [5, 9] is calibrated: no block, with a reason."""
    jobs = [plan_job(0, NAME, "raw"), plan_job(1, NAME, "dd_twirl")]
    raws = [
        raw_record(0, NAME, "raw", {"10": 800, "00": 200}),
        raw_record(1, NAME, "dd_twirl", {"10": 800, "00": 200}),
    ]
    batch, metrics, out = build(tmp_path, jobs, raws)
    half = {5: np.array([[0.9, 0.1], [0.1, 0.9]])}
    for path in analyze_batch(batch, out, metrics_dir=metrics, m3_matrices=half):
        rec = read_json(path)
        assert rec["m3"] is None and rec["m3_reason"] == "measured qubits not calibrated"


def test_analyze_has_no_m3_key_at_all_when_there_is_no_calibration_data(tmp_path):
    jobs = [plan_job(0, NAME, "raw")]
    raws = [raw_record(0, NAME, "raw", {"10": 800, "00": 200})]
    batch, metrics, out = build(tmp_path, jobs, raws)
    rec = read_json(analyze_batch(batch, out, metrics_dir=metrics)[0])
    assert "m3" not in rec and "m3_reason" not in rec


def test_analyze_covered_job_has_an_m3_block_and_no_reason(basic):
    _, _, _, paths, recs = basic
    assert isinstance(recs["0"]["m3"], dict)
    assert "m3_reason" not in recs["0"]


@pytest.mark.parametrize(
    ("pred_counts", "expected"),
    [({"10": 260, "00": 740}, "at chance"), ({"10": 900, "00": 100}, "signal")],
)
def test_analyze_reports_the_prediction_interval_and_whether_it_was_at_chance(
    tmp_path, pred_counts, expected
):
    job = plan_job(0, NAME, "raw")
    n = sum(pred_counts.values())
    job["prediction"] = {
        "model": "m", "counts": pred_counts, "success_probability": pred_counts["10"] / n,
    }  # fmt: skip
    raws = [raw_record(0, NAME, "raw", {"10": 800, "00": 200})]
    batch, metrics, out = build(tmp_path, [job], raws)
    rec = read_json(analyze_batch(batch, out, metrics_dir=metrics)[0])
    lo, hi = ref.wilson(pred_counts["10"], n)
    assert rec["prediction_wilson_95"] == pytest.approx([lo, hi])
    assert rec["predicted_success"] == pytest.approx(pred_counts["10"] / n)
    assert rec["predicted_vs_chance"] == expected
    assert (expected == "at chance") == (lo <= CHANCE), "the label is the Wilson-vs-chance rule"


# ---- end to end: plan -> (fake) submit -> analyze ------------------------------------------


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    pytest.importorskip("scripts.plan_hardware")
    pytest.importorskip("scripts.submit_hardware")
    from quantum.backends import get_fake_backend
    from scripts.plan_hardware import build_plan
    from tests.phase2.fakes import FakeService, JobScript
    from tests.phase2.harness import run_submit, write_ledger

    tmp = tmp_path_factory.mktemp("pipeline")
    noisy = tmp / "noisy"
    noisy.mkdir()
    (noisy / f"{NAME}.json").write_text(json.dumps({"signal": True}))
    batch = build_plan(
        {NAME: registry.build_circuit(NAME)},
        get_fake_backend(),
        shots=1024,
        out_root=tmp / "hardware",
        batch_id="e2e",
        noisy_dir=noisy,
        repeats=1,
    )
    plan = json.loads((batch / "plan.json").read_text())
    # the "hardware" returns exactly the pre-registered prediction and uses half its estimate
    service = FakeService(
        [
            JobScript(counts=j["prediction"]["counts"], usage=[j["estimated_seconds"] / 2])
            for j in plan["jobs"]
        ]
    )
    led = write_ledger(tmp / "budget.json")
    out = run_submit(batch, service, budget_path=led)
    metrics = tmp / "metrics"
    metrics.mkdir()
    (metrics / f"{NAME}.json").write_text(
        json.dumps({"theoretical_success": THEORY, "chance_baseline": CHANCE})
    )
    before = snapshot(batch)
    paths = analyze_batch(batch, tmp / "analysis", metrics_dir=metrics)
    return batch, plan, out, paths, before, tmp


def test_pipeline_runs_to_completion_and_analyses_every_job(pipeline):
    batch, plan, out, paths, before, _ = pipeline
    assert out.code == 0
    assert len(paths) == len(plan["jobs"]) == len(raw_files(batch))
    assert snapshot(batch) == before, "analysis must not change the raw batch"


def test_pipeline_hardware_equal_to_prediction_gives_a_hellinger_of_one(pipeline):
    _, plan, _, paths, _, _ = pipeline
    for p in paths:
        rec = read_json(p)
        job = plan["jobs"][rec["index"]]
        assert rec["hellinger_vs_prediction"] == pytest.approx(1.0, abs=1e-9), job["config"]
        if job["kind"] != "calibration":
            want = job["prediction"]["success_probability"]
            assert rec["success_probability"] == pytest.approx(want)
            assert 0.0 <= rec["hellinger_vs_ideal"] <= 1.0


def test_pipeline_experiment_jobs_get_an_m3_block_from_the_batch_own_calibration(pipeline):
    _, plan, _, paths, _, _ = pipeline
    for p in paths:
        rec = read_json(p)
        job = plan["jobs"][rec["index"]]
        if job["config"] in ("raw", "dd", "dd_twirl"):
            assert "m3" in rec, f"job {rec['index']} ({job['config']}) has no m3 block"
            assert math.isfinite(rec["m3"]["success_probability"])


def test_pipeline_approval_precedes_every_job_and_matches_the_plan_hash(pipeline):
    from datetime import datetime

    from tests.phase2.fakes import sha

    batch, _, _, _, _, _ = pipeline
    approval = read_json(batch / "approval.json")
    assert approval["plan_sha256"] == sha((batch / "plan.json").read_bytes())
    for raw in raw_files(batch).values():
        created = datetime.fromisoformat(raw["created"])
        assert created > datetime.fromisoformat(approval["approved_at"])


# ---- integrity: the plan the predictions came from must be the plan that was approved ---------


def _approved(tmp_path, jobs, raws, plan_text=None):
    from tests.phase2.fakes import sha

    batch, metrics, out = build(tmp_path, jobs, raws)
    approval = {
        "batch_id": "ana",
        "plan_sha256": sha((batch / "plan.json").read_bytes()),
        "approved_at": "2026-11-08T11:59:00+00:00",
        "approved_by": "human",
    }
    (batch / "approval.json").write_text(json.dumps(approval))
    return batch, metrics, out


def test_analyze_accepts_a_plan_that_matches_its_approval(tmp_path):
    jobs = [plan_job(0, NAME, "raw")]
    raws = [raw_record(0, NAME, "raw", {"10": 800, "00": 200})]
    batch, metrics, out = _approved(tmp_path, jobs, raws)
    assert len(analyze_batch(batch, out, metrics_dir=metrics)) == 1


def test_analyze_refuses_a_plan_edited_after_approval(tmp_path):
    # editing the pre-registered prediction after seeing the data is the tuning we must prevent
    jobs = [plan_job(0, NAME, "raw")]
    raws = [raw_record(0, NAME, "raw", {"10": 800, "00": 200})]
    batch, metrics, out = _approved(tmp_path, jobs, raws)
    plan = json.loads((batch / "plan.json").read_text())
    plan["jobs"][0]["prediction"]["counts"] = {"10": 800, "00": 200}  # "predict" what happened
    (batch / "plan.json").write_text(json.dumps(plan))
    before = snapshot(batch)
    with pytest.raises(ValueError):
        analyze_batch(batch, out, metrics_dir=metrics)
    assert not list(out.rglob("*.json")), "nothing may be written from an edited plan"
    assert snapshot(batch) == before


def test_analyze_refuses_a_raw_file_that_is_not_the_planned_circuit(tmp_path):
    jobs = [plan_job(0, NAME, "raw")]
    rec = raw_record(0, NAME, "raw", {"10": 800, "00": 200})
    rec["isa_sha256"] = "deadbeef"  # hardware ran something other than what was planned
    batch, metrics, out = _approved(tmp_path, jobs, [rec])
    with pytest.raises(ValueError):
        analyze_batch(batch, out, metrics_dir=metrics)
