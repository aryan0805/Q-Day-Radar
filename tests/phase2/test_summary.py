"""analyze_hardware.summarize_batch: per-repeat results, the drift flag and the mitigation rule.

The rule (lead): a repeat pair has drifted beyond shot noise when its Wilson intervals do not
overlap; a mitigation gain is resolved only if it exceeds BOTH the larger pooled Wilson half-width
AND the larger repeat spread of the two configs. Expected values are computed here from the
per-repeat counts with tests/phase2/reference.py, never read back from the summary.
"""

import json

import pytest

pytest.importorskip("scripts.analyze_hardware")
from scripts.analyze_hardware import summarize_batch  # noqa: E402
from tests.phase2 import reference as ref  # noqa: E402

SHOTS = 4096
NAME = "grover_present_k2"


def write(tmp_path, spec):
    """spec: list of (index, config, hits). One per-job analysis file each, like analyze_batch."""
    d = tmp_path / "analysis"
    d.mkdir(exist_ok=True)
    for index, config, hits in spec:
        lo, hi = ref.wilson(hits, SHOTS)
        (d / f"{index}.json").write_text(
            json.dumps(
                {
                    "index": index, "name": NAME, "config": config, "status": "DONE",
                    "shots": SHOTS, "success_probability": hits / SHOTS, "wilson_95": [lo, hi],
                    "theoretical_success": 1.0, "chance_baseline": 0.25,
                    "predicted_success": 0.65, "predicted_vs_chance": "signal",
                    "hellinger_vs_ideal": 0.4, "hellinger_vs_prediction": 0.9, "m3": None,
                }
            )
        )  # fmt: skip
    return d


def comparison(summary, cfg):
    return summary["comparisons"][f"{NAME}: {cfg} - raw"]


def test_summary_lists_every_repeat_with_its_own_success_and_interval(tmp_path):
    d = write(tmp_path, [(0, "raw", 1000), (1, "raw", 1100), (2, "dd", 1500), (3, "dd", 1520)])
    s = summarize_batch(d)
    raw = s["entries"][f"{NAME}/raw"]
    assert [r["index"] for r in raw["repeats"]] == [0, 1]
    assert [r["success"] for r in raw["repeats"]] == [1000 / SHOTS, 1100 / SHOTS]
    assert raw["repeats"][1]["wilson_95"] == pytest.approx(ref.wilson(1100, SHOTS))
    assert raw["repeat_spread"] == pytest.approx(100 / SHOTS)
    assert raw["shots_pooled"] == 2 * SHOTS
    assert raw["success_probability"] == pytest.approx(2100 / (2 * SHOTS))
    assert raw["wilson_95"] == pytest.approx(ref.wilson(2100, 2 * SHOTS))


@pytest.mark.parametrize(
    ("hits_a", "hits_b"),
    [(1000, 1001), (1000, 1100), (1000, 1160), (1000, 1170), (1000, 1400), (2000, 2000)],
)
def test_summary_drift_flag_is_exactly_non_overlapping_wilson_intervals(tmp_path, hits_a, hits_b):
    d = write(tmp_path, [(0, "raw", hits_a), (1, "raw", hits_b)])
    la, ha = ref.wilson(hits_a, SHOTS)
    lb, hb = ref.wilson(hits_b, SHOTS)
    overlap = la <= hb and lb <= ha
    entry = summarize_batch(d)["entries"][f"{NAME}/raw"]
    assert entry["drift_beyond_shot_noise"] is (not overlap)


def test_summary_drift_is_per_config_and_a_single_run_never_drifts(tmp_path):
    d = write(tmp_path, [(0, "raw", 1000), (1, "raw", 1500), (2, "dd", 1200), (3, "dd", 1210)])
    s = summarize_batch(d)["entries"]
    assert s[f"{NAME}/raw"]["drift_beyond_shot_noise"] is True
    assert s[f"{NAME}/dd"]["drift_beyond_shot_noise"] is False
    lone = tmp_path / "lone"
    lone.mkdir()
    only = summarize_batch(write(lone, [(0, "raw", 1000)]))
    assert only["entries"][f"{NAME}/raw"]["drift_beyond_shot_noise"] is False


def test_summary_gain_is_not_resolved_when_it_is_inside_the_repeat_spread(tmp_path):
    # dd is ~0.04 above raw (more than a pooled half-width of ~0.011) but raw repeats differ 0.08
    d = write(tmp_path, [(0, "raw", 1000), (1, "raw", 1330), (2, "dd", 1330), (3, "dd", 1340)])
    s = summarize_batch(d)
    c = comparison(s, "dd")
    pooled_dd = (1330 + 1340) / (2 * SHOTS)
    pooled_raw = (1000 + 1330) / (2 * SHOTS)
    assert c["difference"] == pytest.approx(pooled_dd - pooled_raw)
    assert c["difference"] > c["wilson_half_width_max"], "bigger than shot noise alone"
    assert c["repeat_spread_max"] == pytest.approx(330 / SHOTS)
    assert c["gain_resolved"] is False
    assert ": none." in s["mitigation_statement"], "the statement lists no resolved gain"


def test_summary_gain_is_resolved_only_above_both_the_half_width_and_the_spread(tmp_path):
    d = write(tmp_path, [(0, "raw", 1000), (1, "raw", 1020), (2, "dd", 1500), (3, "dd", 1520)])
    s = summarize_batch(d)
    c = comparison(s, "dd")
    expected = (
        c["difference"] > c["wilson_half_width_max"] and c["difference"] > c["repeat_spread_max"]
    )
    assert expected and c["gain_resolved"] is True
    assert f"{NAME}: dd - raw" in s["mitigation_statement"]


def test_summary_gain_inside_shot_noise_is_not_resolved_even_with_a_tiny_spread(tmp_path):
    d = write(tmp_path, [(0, "raw", 1000), (1, "raw", 1000), (2, "dd", 1010), (3, "dd", 1010)])
    c = comparison(summarize_batch(d), "dd")
    assert c["repeat_spread_max"] == 0
    assert c["difference"] < c["wilson_half_width_max"]
    assert c["gain_resolved"] is False


def test_summary_a_worse_mitigated_config_is_never_a_gain(tmp_path):
    d = write(tmp_path, [(0, "raw", 2000), (1, "raw", 2010), (2, "dd", 1000), (3, "dd", 1010)])
    c = comparison(summarize_batch(d), "dd")
    assert c["difference"] < 0 and c["gain_resolved"] is False


def test_summary_gain_rows_carry_the_chance_floor_flags(tmp_path):
    # raw sits below chance (0.25), dd just above it: resolved gain, but only dd clears chance
    d = write(tmp_path, [(0, "raw", 900), (1, "raw", 905), (2, "dd", 1100), (3, "dd", 1105)])
    c = comparison(summarize_batch(d), "dd")
    assert c["gain_resolved"] is True
    lo_raw = ref.wilson(900 + 905, 2 * SHOTS)[0]
    lo_dd = ref.wilson(1100 + 1105, 2 * SHOTS)[0]
    assert c["raw_wilson_lo_above_chance"] is (lo_raw > 0.25)
    assert c["mitigated_wilson_lo_above_chance"] is (lo_dd > 0.25)
    assert (
        c["raw_wilson_lo_above_chance"] is False and c["mitigated_wilson_lo_above_chance"] is True
    )


def test_summary_statement_labels_a_resolved_gain_as_exploratory(tmp_path):
    d = write(tmp_path, [(0, "raw", 900), (1, "raw", 905), (2, "dd", 1100), (3, "dd", 1105)])
    statement = summarize_batch(d)["mitigation_statement"].lower()
    for word in ("exploratory", "no multiple-comparison correction"):
        assert word in statement, word
    assert "grover_present_k2: dd - raw" in statement


def test_summary_skips_jobs_without_a_result_and_reads_nothing_but_analysis_files(tmp_path):
    d = write(tmp_path, [(0, "raw", 1000), (1, "raw", 1010)])
    (d / "2.json").write_text(
        json.dumps({"index": 2, "name": NAME, "config": "raw", "status": "ERROR",
                    "shots": SHOTS, "success_probability": None, "wilson_95": None})
    )  # fmt: skip
    entry = summarize_batch(d)["entries"][f"{NAME}/raw"]
    assert [r["index"] for r in entry["repeats"]] == [0, 1]


def test_summary_counts_its_comparisons_and_marks_them_exploratory(tmp_path):
    d = write(tmp_path, [(0, "raw", 900), (1, "raw", 905), (2, "dd", 1100), (3, "dd", 1105)])
    s = summarize_batch(d)
    assert s["comparisons_exploratory"] is True
    assert s["n_comparisons"] == len(s["comparisons"]) == 1
