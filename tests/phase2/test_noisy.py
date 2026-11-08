"""Phase 2 noisy simulation: quantum/run/noisy.py and results/noisy/*.json."""

import json
import math
from pathlib import Path

import pytest

from quantum.circuits import registry
from quantum.run import noisy
from tests.phase1.reference import qpe_outcome_probs
from tests.phase2 import reference as ref
from tests.phase2.guards import ROOT

SCHEMA = {
    "name", "kind", "noise_model", "shots", "seed_simulator", "success_probability", "wilson_95",
    "theoretical_success", "chance_baseline", "normalized_score", "hellinger_vs_ideal", "signal",
}  # fmt: skip
NAMES = list(registry.REQUIRED_NAMES)


# ---- exact ideal distributions, recomputed independently ---------------------------------


@pytest.mark.parametrize(
    ("name", "n", "a", "t"),
    [
        ("shor15_textbook", 15, 7, 8),
        ("shor15_beauregard", 15, 7, 8),
        ("shor21_beauregard", 21, 2, 10),
    ],
)
def test_noisy_ideal_distribution_shor_is_the_analytic_qpe_distribution(name, n, a, t):
    from tests.phase1.reference import mult_order

    r = mult_order(a, n)
    want = sum(qpe_outcome_probs(t, s / r) for s in range(r)) / r
    got = noisy.ideal_distribution(name)
    assert math.isclose(sum(got.values()), 1.0, abs_tol=1e-9)
    for m, p in enumerate(want):
        assert math.isclose(got.get(format(m, f"0{t}b"), 0.0), p, abs_tol=1e-9), m
    assert all(len(k) == t for k in got)


@pytest.mark.parametrize("k", [2, 3, 4, 5])
def test_noisy_ideal_distribution_grover_peaks_on_the_key_and_is_flat_elsewhere(k):
    name = f"grover_present_k{k}"
    qc = registry.build_circuit(name)
    got = noisy.ideal_distribution(name, qc)
    assert math.isclose(sum(got.values()), 1.0, abs_tol=1e-9)
    theory = qc.metadata["theoretical_success"]
    top = max(got, key=got.get)
    assert math.isclose(got[top], theory, abs_tol=1e-9)
    rest = [p for key, p in got.items() if key != top]
    if rest:
        assert all(math.isclose(p, (1 - theory) / (2**k - 1), abs_tol=1e-9) for p in rest)


# ---- run_noisy: one cheap circuit, recomputed from its own numbers ----------------------


@pytest.fixture(scope="module")
def grover2_record(tmp_path_factory):
    out = tmp_path_factory.mktemp("noisy")
    qc = registry.build_circuit("grover_present_k2")
    rec = noisy.run_noisy("grover_present_k2", qc, out_dir=out)
    return rec, out, qc


def test_noisy_record_has_the_agreed_schema(grover2_record):
    rec, out, _ = grover2_record
    assert SCHEMA <= set(rec)
    assert json.loads((out / "grover_present_k2.json").read_text()) == rec
    assert rec["noise_model"] == "fake_kingston" and rec["shots"] >= 8192
    assert rec["name"] == "grover_present_k2" and rec["kind"] == "generic"


def test_noisy_record_statistics_recompute_independently(grover2_record):
    rec, _, qc = grover2_record
    lo, hi = rec["wilson_95"]
    hits = round(rec["success_probability"] * rec["shots"])
    want_lo, want_hi = ref.wilson(hits, rec["shots"])
    assert math.isclose(lo, want_lo, abs_tol=1e-9) and math.isclose(hi, want_hi, abs_tol=1e-9)
    assert lo <= rec["success_probability"] <= hi
    assert math.isclose(
        rec["normalized_score"],
        ref.normalized(
            rec["success_probability"], rec["theoretical_success"], rec["chance_baseline"]
        ),
        abs_tol=1e-9,
    )
    assert rec["signal"] is (lo > rec["chance_baseline"])
    assert rec["theoretical_success"] == qc.metadata["theoretical_success"]
    assert rec["chance_baseline"] == qc.metadata["chance_baseline"]


def test_noisy_record_is_noisy_but_not_garbage(grover2_record):
    rec, _, _ = grover2_record
    assert 0.0 < rec["hellinger_vs_ideal"] < 1.0  # noise moves it off the ideal distribution
    assert rec["success_probability"] < rec["theoretical_success"]  # k=2 ideal success is 1.0
    assert rec["success_probability"] > rec["chance_baseline"]


def test_noisy_run_is_deterministic_for_fixed_seeds(grover2_record, tmp_path):
    rec, _, qc = grover2_record
    again = noisy.run_noisy("grover_present_k2", qc, out_dir=tmp_path)
    for key in SCHEMA - {"timestamp"}:
        assert again[key] == rec[key], key


def test_noisy_run_refuses_fewer_than_8192_shots(tmp_path):
    qc = registry.build_circuit("grover_present_k2")
    with pytest.raises(ValueError):
        noisy.run_noisy("grover_present_k2", qc, shots=4096, out_dir=tmp_path)


# ---- the shot-count rule for the committed files (lead, 2026-11-08) ---------------------------


def shots_rule_ok(rec: dict) -> bool:
    """>= 8192 shots, or >= 1024 only when the file carries a non-empty reduced_shots_reason."""
    reason = rec.get("reduced_shots_reason")
    floor = 1024 if isinstance(reason, str) and reason.strip() else 8192
    return rec["shots"] >= floor


def test_noisy_shots_rule_itself():
    assert shots_rule_ok({"shots": 8192})
    assert shots_rule_ok({"shots": 100000})
    assert not shots_rule_ok({"shots": 1024})
    assert not shots_rule_ok({"shots": 1024, "reduced_shots_reason": ""})
    assert not shots_rule_ok({"shots": 1024, "reduced_shots_reason": "   "})
    assert shots_rule_ok({"shots": 1024, "reduced_shots_reason": "deadline: sim too slow"})
    assert not shots_rule_ok({"shots": 512, "reduced_shots_reason": "deadline"})
    assert not shots_rule_ok({"shots": 8191})


# ---- the committed results/noisy/*.json (appear once builder has run scripts/run_noisy.py) ----

RESULTS = ROOT / "results" / "noisy"


def test_noisy_results_cover_every_registry_circuit():
    missing = [n for n in NAMES if not (RESULTS / f"{n}.json").is_file()]
    assert not missing, f"results/noisy is missing {missing}"


@pytest.mark.parametrize("name", NAMES)
def test_noisy_results_file_schema_and_signal_rule(name):
    path = Path(RESULTS / f"{name}.json")
    if not path.is_file():
        pytest.skip(f"{path.name} not produced yet (the coverage test above is the strict one)")
    rec = json.loads(path.read_text())
    assert SCHEMA <= set(rec) and rec["name"] == name
    assert rec["noise_model"] == "fake_kingston"
    assert shots_rule_ok(rec), f"{name}: {rec['shots']} shots without a reduced_shots_reason"
    lo, hi = rec["wilson_95"]
    assert 0 <= lo <= rec["success_probability"] <= hi <= 1
    if rec.get("reduced_shots_reason"):
        # a reduced-shot file must say what its (weaker) result means: at chance, or not
        assert "prediction" in rec
        at_chance = lo <= rec["chance_baseline"]
        assert (rec["prediction"] == "at chance") is at_chance, rec["prediction"]
    else:
        assert rec["shots"] >= 8192
    assert rec["signal"] is (lo > rec["chance_baseline"])
    assert 0.0 <= rec["hellinger_vs_ideal"] <= 1.0
    expected = registry.build_circuit(name).metadata
    assert math.isclose(rec["theoretical_success"], expected["theoretical_success"], abs_tol=1e-9)
    assert math.isclose(rec["chance_baseline"], expected["chance_baseline"], abs_tol=1e-9)
    assert math.isclose(
        rec["normalized_score"],
        ref.normalized(
            rec["success_probability"], rec["theoretical_success"], rec["chance_baseline"]
        ),
        abs_tol=1e-9,
    )


# ---- reduced-shot runs (lead, 2026-11-08): allowed only with a stated reason --------------------


def test_noisy_reduced_shots_need_a_reason_and_carry_a_prediction(tmp_path):
    qc = registry.build_circuit("grover_present_k2")
    with pytest.raises(ValueError):
        noisy.run_noisy("grover_present_k2", qc, shots=1024, out_dir=tmp_path)
    with pytest.raises(ValueError):
        noisy.run_noisy("grover_present_k2", qc, shots=512, out_dir=tmp_path, reduced_reason="x")
    rec = noisy.run_noisy(
        "grover_present_k2", qc, shots=1024, out_dir=tmp_path, reduced_reason="test: short run"
    )
    assert rec["shots"] == 1024 and rec["reduced_shots_reason"] == "test: short run"
    assert shots_rule_ok(rec)
    assert rec["signal"] is True and rec["prediction"] == "signal"
    assert json.loads((tmp_path / "grover_present_k2.json").read_text()) == rec


def test_noisy_reduced_shot_run_of_a_circuit_at_chance_is_labelled_at_chance(tmp_path):
    from quantum.circuits.grover_present import build_grover

    # zero Grover iterations = a uniform guess: success sits at the chance baseline
    base = registry.build_circuit("grover_present_k2")
    qc = build_grover(2, base.metadata["pairs"], iterations=0)
    qc.metadata = {**base.metadata, **qc.metadata, "theoretical_success": 1.0}
    rec = noisy.run_noisy(
        "grover_present_k2", qc, shots=1024, out_dir=tmp_path, reduced_reason="test: at chance"
    )
    lo, _ = rec["wilson_95"]
    assert lo <= rec["chance_baseline"] and rec["signal"] is False
    assert rec["prediction"] == "at chance"
    assert ref.wilson(round(rec["success_probability"] * 1024), 1024)[0] == pytest.approx(lo)


def test_noisy_full_shot_run_has_no_reduced_marker(grover2_record):
    rec, _, _ = grover2_record
    assert "reduced_shots_reason" not in rec or not rec["reduced_shots_reason"]
    assert rec["shots"] >= 8192
