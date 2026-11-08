"""Calibration, scenarios and projections: every reported number is traced to a file or recomputed.

Nothing here trusts a number that appears only in calibration.json or scenarios.json: each is
rebuilt from the per-case files, the literature file or the physical model, so a typed or stale
value fails. Labels (measured / extrapolated / projection / literature) must also be honest.
"""

from __future__ import annotations

import math
import re

import pytest

from tests.phase3 import reference as ref


def lit_value(entry) -> float:
    """A literature value as a float; understands '1.19*2^86'."""
    v = entry["value"]
    if isinstance(v, (int, float)):
        return float(v)
    m = re.fullmatch(r"\s*([0-9.eE+-]+)\s*\*\s*2\^(\d+)\s*", str(v))
    if m:
        return float(m[1]) * 2 ** int(m[2])
    return float(v)


@pytest.fixture(scope="module")
def lit() -> dict:
    return {e["id"]: e for e in ref.literature()}


@pytest.fixture(scope="module")
def comps() -> list[dict]:
    return ref.load_json(ref.EST / "calibration.json")["comparisons"]


def _row(comps, target, estimator, quantity, lit_id=None):
    hits = [
        r
        for r in comps
        if r["target"] == target
        and r["estimator"] == estimator
        and r["quantity"] == quantity
        and (lit_id is None or r["literature_id"] == lit_id)
    ]
    assert hits, f"no calibration row {target}/{estimator}/{quantity}/{lit_id}"
    return hits[0]


# ---- calibration is traced ------------------------------------------------------------------
TIME_UNITS = {"days": 86400.0, "hours": 3600.0, "seconds": 1.0}


def lit_base(entry) -> float:
    """Literature value in base units: times are converted to seconds."""
    unit = str(entry["units"]).split()[0]
    return lit_value(entry) * TIME_UNITS.get(unit, 1.0)


def test_estimate_calibration_literature_values_and_ratios_are_recomputed(comps, lit):
    for r in comps:
        tag = f"{r['target']}/{r['estimator']}/{r['quantity']}/{r['literature_id']}"
        want = lit_base(lit[r["literature_id"]])
        assert r["literature_value"] == pytest.approx(want, rel=1e-9), tag
        assert r["ratio"] == pytest.approx(r["ours"] / want, rel=1e-9), f"{tag}: ratio is ours/lit"
        assert r["method"].split(":")[0] in {"measured", "extrapolated", "projection"}, tag
        if ref.ratio(r["ours"], want) > 3:
            assert len(str(r["explanation"]).strip()) > 40, f"{tag}: over 3x, no explanation"


def test_estimate_calibration_rsa_rows_equal_the_files_they_cite(comps):
    sc = ref.load_json(ref.EST / "scaling.json")["fits"]
    sel = next(
        f for f in sc if f["estimator"] == "qdk" and f["selected"] and "toffoli" in f["quantity"]
    )
    rows = [
        r
        for r in comps
        if r["target"] == "rsa2048"
        and r["estimator"] == "qdk"
        and r["literature_id"] == "ge2019_toffoli_rsa2048"
    ]
    assert rows, "no QDK RSA-2048 calibration row"
    assert any(r["ours"] == pytest.approx(sel["extrapolated"]["value"], rel=1e-9) for r in rows), (
        "no QDK row equals the selected fit's n=2048 value"
    )
    assert all(r["method"].startswith("extrapolated") for r in rows)
    modexp = ref.cases("qualtran")["rsa2048_modexp"]
    row = _row(comps, "rsa2048", "qualtran", "toffoli_equiv", "g2025_toffoli_rsa2048")
    assert row["ours"] == pytest.approx(modexp["toffoli_equiv"], rel=1e-9)
    assert row["method"].startswith("measured")
    assert _row(comps, "rsa2048", "qualtran", "logical_qubits")["ours"] == modexp["logical_qubits"]


def test_estimate_rsa2048_modexp_is_really_a_2048_bit_register_with_a_coprime_base():
    m = ref.cases("qualtran")["rsa2048_modexp"]
    n = int(m["N"])
    assert n.bit_length() == m["n_bits"] == 2048 and n % 2 == 1
    from math import gcd

    assert gcd(m["base_a"], n) == 1
    assert m["logical_qubits"] == 3 * 2048  # x register, 2n exponent bits: caveat C


def test_estimate_calibration_ecc_projection_is_the_measured_ecadd_times_2n(comps):
    e = ref.cases("qualtran")["ecc256_ecadd"]
    row = _row(comps, "ecc256", "qualtran", "toffoli_equiv", "roetteler2017_toffoli_p256")
    assert row["ours"] == pytest.approx(e["toffoli_equiv"] * 2 * 256, rel=1e-9)
    assert row["method"].startswith("projection") and e["projection"]["point_additions"] == 512


def _grover_iterations(k: int) -> int:
    """Grover iterations for a k-bit key with one marked item: floor(pi/4 * 2^(k/2))."""
    return math.floor(math.pi / 4 * 2 ** (k / 2))


def test_estimate_calibration_aes_projection_uses_peel_false_circuits_and_reports_its_fit(comps):
    """P1 audit F5: toy-SPN costs enter an AES projection only with peel_last_sbox=False.
    Rule tested (not a particular r2): the row reports fit_r2 and residuals, and says
    'unreliable' whenever r2 < 0.9."""
    from quantum.estimate import scaling

    q = ref.cases("qdk")
    ks = [2, 3, 4, 5]
    for k in ks:
        assert f"grover_present_k{k}_nopeel" in q, f"no peel_last_sbox=False case for k={k}"
    per_iter = [
        q[f"grover_present_k{k}_nopeel"]["toffoli_equiv"] / _grover_iterations(k) for k in ks
    ]
    f = scaling.fit_power_law(ks, per_iter)
    rows = [r for r in comps if r["target"] == "aes128" and r["estimator"] == "qdk"]
    assert rows, "no AES projection rows"
    for r in rows:
        assert r["label"] == "projection" and r["peel_last_sbox"] is False
        assert r["method"].startswith("projection")
        assert r["fit_r2"] == pytest.approx(f["r2"], abs=1e-6), "state the fit's r2"
        assert len(r["fit_residuals"]) == len(ks)
        assert [x["rel"] for x in r["fit_residuals"]] == pytest.approx(
            [x["rel"] for x in f["residuals"]], abs=1e-6
        )
        if f["r2"] < 0.9:
            assert "unreliable" in str(r["explanation"]).lower(), f"r2 = {f['r2']:.3f}"
    t_row = _row(comps, "aes128", "qdk", "t_equiv_total")
    iterations = math.floor(math.pi / 4 * 2**64)
    assert t_row["ours"] == pytest.approx(scaling.predict(f, 128) * iterations * 4, rel=1e-6)


def test_estimate_grover_toy_costs_are_monotone_in_the_key_size():
    """Per-iteration cost of the peel_last_sbox=False toys must not collapse as k grows."""
    q = ref.cases("qdk")
    per = [
        q[f"grover_present_k{k}_nopeel"]["toffoli_equiv"] / _grover_iterations(k)
        for k in (2, 3, 4, 5)
    ]
    assert all(b >= a / 2 for a, b in zip(per, per[1:], strict=False)), f"per-iteration {per}"


# ---- physical rows: our model fed each paper's OWN logical counts, next to the paper's numbers ---
PHYSICAL = [
    ("rsa2048", "physical_qubits", "ge2019_physical_qubits_rsa2048"),
    ("rsa2048", "runtime_seconds", "ge2019_runtime_rsa2048"),
    ("rsa2048", "physical_qubits", "g2025_physical_qubits_rsa2048"),
    ("rsa2048", "runtime_seconds", "g2025_runtime_rsa2048"),
    ("ecc256", "physical_qubits", "litinski2023_physical_qubits"),
    ("ecc256", "runtime_seconds", "litinski2023_runtime_superconducting"),
]


@pytest.mark.parametrize(("target", "quantity", "lit_id"), PHYSICAL)
def test_estimate_calibration_has_a_physical_row_per_paper_figure(comps, target, quantity, lit_id):
    r = _row(comps, target, "physical", quantity, lit_id)
    assert r["method"].startswith("measured") and r.get("input_logical_counts"), lit_id
    if ref.ratio(r["ours"], r["literature_value"]) > 3:
        assert len(str(r["explanation"]).strip()) > 40, f"{lit_id}: over 3x, no explanation"


def test_estimate_calibration_gidney_2025_physical_rows_equal_the_scenario_median(comps):
    """Only that paper's logical counts are the scenario's counts, so only those rows must agree."""
    sc = ref.load_json(ref.EST / "scenarios.json")["targets"]["rsa2048"]["by_scenario"]["median"]
    for quantity in ("physical_qubits", "runtime_seconds"):
        lid = {
            "physical_qubits": "g2025_physical_qubits_rsa2048",
            "runtime_seconds": "g2025_runtime_rsa2048",
        }[quantity]
        r = _row(comps, "rsa2048", "physical", quantity, lid)
        assert r["ours"] == pytest.approx(sc[quantity], rel=1e-9), quantity


@pytest.mark.parametrize(("target", "quantity", "lit_id"), PHYSICAL)
def test_estimate_calibration_physical_rows_are_reproduced_by_the_physical_model(
    comps, lit, target, quantity, lit_id
):
    """Recompute each row from its recorded logical counts and the paper's error rate and cycle."""
    from quantum.estimate import physical

    r = _row(comps, target, "physical", quantity, lit_id)
    spec = r.get("input_hardware") or {}
    assert {"physical_error_rate", "cycle_time_seconds"} <= set(spec), (
        f"{lit_id}: no input_hardware"
    )
    scen = {
        "physical_error_rate": spec["physical_error_rate"],
        "cycle_time_seconds": spec["cycle_time_seconds"],
        "qec_scheme": spec.get("qec_scheme", "surface_code"),
        "error_budget": spec.get("error_budget", 0.01),
    }
    got = physical.physical_estimate(r["input_logical_counts"], scen)
    assert got[quantity] == pytest.approx(r["ours"], rel=1e-9), lit_id


# ---- scenarios are recomputed from their logical counts and traced to the literature -----------
@pytest.fixture(scope="module")
def scen() -> dict:
    return ref.load_json(ref.EST / "scenarios.json")


def test_estimate_scenarios_physical_parameters_are_the_cited_literature_values(scen, lit):
    for name, sc in scen["scenarios"].items():
        cited = {lit_value(lit[i]) for i in sc["source_ids"]}
        assert sc["physical_error_rate"] in cited, f"{name}: error rate not in {sc['source_ids']}"
        assert sc["qec_scheme"]["cycle_time_seconds"] in cited, f"{name}: cycle time not cited"


def test_estimate_scenarios_logical_counts_are_the_cited_literature_values(scen, lit):
    rsa = scen["targets"]["rsa2048"]["logical_source"]["logical_counts"]
    assert rsa["numQubits"] == lit_value(lit["g2025_logical_qubits_rsa2048"])
    assert rsa["cczCount"] == lit_value(lit["g2025_toffoli_rsa2048"])
    ecc = scen["targets"]["ecc256"]["logical_source"]["logical_counts"]
    assert ecc["numQubits"] == lit_value(lit["roetteler2017_logical_qubits_p256"])
    assert ecc["cczCount"] == lit_value(lit["roetteler2017_toffoli_p256"])
    aes = scen["targets"]["aes128"]["logical_source"]
    assert aes["logical_counts"]["numQubits"] == lit_value(lit["grassl2016_logical_qubits_aes128"])
    total_t = aes["logical_counts"]["tCount"] * aes["repetitions"]
    assert total_t == pytest.approx(lit_value(lit["grassl2016_t_gates_aes128"]), rel=1e-3)


def test_estimate_scenarios_assumptions_not_in_the_source_are_stated(scen):
    for t in ("rsa2048", "ecc256"):
        src = scen["targets"][t]["logical_source"]
        if src["logical_counts"]["measurementCount"]:
            assert "not in the source" in src["measurement_count_assumption"], t


@pytest.mark.parametrize("target", ref.TARGETS)
def test_estimate_scenarios_are_reproduced_by_the_physical_model(scen, target):
    """Recompute from logical counts + scenario parameters; a hand-edited number fails."""
    from quantum.estimate import physical

    src = scen["targets"][target]["logical_source"]
    for name in ("optimistic", "median"):
        sc = scen["scenarios"][name]
        params = {
            "physical_error_rate": sc["physical_error_rate"],
            "cycle_time_seconds": sc["qec_scheme"]["cycle_time_seconds"],
            "qec_scheme": sc["qec_scheme"]["name"],
            "error_budget": sc["error_budget"],
        }
        got = physical.physical_estimate(
            src["logical_counts"], params, repetitions=src.get("repetitions", 1)
        )
        want = scen["targets"][target]["by_scenario"][name]
        for key in ("logical_qubits", "physical_qubits", "code_distance"):
            assert got[key] == want[key], f"{target}/{name}/{key}"
        assert got["runtime_seconds"] == pytest.approx(want["runtime_seconds"], rel=1e-9)


def test_estimate_physical_model_lower_error_rate_gives_fewer_qubits_and_smaller_distance():
    from quantum.estimate import physical

    counts = {
        "numQubits": 100,
        "tCount": 0,
        "rotationCount": 0,
        "cczCount": 10**7,
        "ccixCount": 0,
        "measurementCount": 10**7,
    }
    base = {"cycle_time_seconds": 1e-6, "qec_scheme": "surface_code", "error_budget": 0.01}
    out = [
        physical.physical_estimate(counts, {**base, "physical_error_rate": e})
        for e in (1e-5, 1e-4, 1e-3)
    ]
    assert [o["code_distance"] for o in out] == sorted(o["code_distance"] for o in out)
    assert [o["physical_qubits"] for o in out] == sorted(o["physical_qubits"] for o in out)
    assert out[0]["physical_qubits"] < out[-1]["physical_qubits"]


def test_estimate_physical_model_scales_with_the_logical_problem():
    from quantum.estimate import physical

    base = {
        "physical_error_rate": 1e-3,
        "cycle_time_seconds": 1e-6,
        "qec_scheme": "surface_code",
        "error_budget": 0.01,
    }
    small = {
        "numQubits": 100,
        "tCount": 0,
        "rotationCount": 0,
        "cczCount": 10**6,
        "ccixCount": 0,
        "measurementCount": 10**6,
    }
    more_qubits = {**small, "numQubits": 400}
    more_gates = {**small, "cczCount": 10**9, "measurementCount": 10**9}
    a, b, c = (physical.physical_estimate(x, base) for x in (small, more_qubits, more_gates))
    assert b["physical_qubits"] > 2 * a["physical_qubits"]
    assert c["runtime_seconds"] > 100 * a["runtime_seconds"]


def test_estimate_scenario_pessimistic_differs_from_median_only_in_cycle_time_if_so_stated(scen):
    """Not an error, but it must be visible: here 'pessimistic' keeps the median error rate."""
    med, pes = scen["scenarios"]["median"], scen["scenarios"]["pessimistic"]
    if med["physical_error_rate"] == pes["physical_error_rate"]:
        by = {t: scen["targets"][t]["by_scenario"] for t in ref.TARGETS}
        for t in ref.TARGETS:
            assert by[t]["pessimistic"]["physical_qubits"] == by[t]["median"]["physical_qubits"]
            ratio = by[t]["pessimistic"]["runtime_seconds"] / by[t]["median"]["runtime_seconds"]
            assert ratio == pytest.approx(
                pes["qec_scheme"]["cycle_time_seconds"] / med["qec_scheme"]["cycle_time_seconds"],
                rel=1e-6,
            )
