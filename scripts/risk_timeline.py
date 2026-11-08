"""Hardware timeline fit, CRQC years per scenario and target, survey check -> timeline.json.

Inputs: quantum/estimate/literature.yaml (timeline points; entries with a `feeds` block, which
may feed physical qubits only), quantum/risk/exposure.yaml (as_of, runtime cap, inclusion rule:
design choices) and Phase 3's results/estimate/scenarios.json. The fit runs on the frontier
(running maximum of the per-year points) and the baseline is the record.
P = min(model, every applicable paper feed); R is always the Phase 3 model's.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantum.estimate import cases, common  # noqa: E402
from quantum.risk import timeline as tl  # noqa: E402

OUT = ROOT / "results" / "risk" / "timeline.json"
QEC_FAMILY = "surface_code_planar"
SCENARIOS = ("optimistic", "median", "pessimistic")
TARGETS = ("rsa2048", "ecc256", "aes128")


def _seconds(entry: dict) -> float:
    unit = str(entry["units"]).split()[0].lower()
    return float(entry["value"]) * tl.UNIT_SECONDS[unit]


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(abs(a), abs(b))


def applicable_feeds(
    lit: dict, target: str, scenario: dict
) -> tuple[float, str, str | None] | None:
    """The smallest applicable paper feed of physical qubits for one target in one scenario.

    A feed (literature entry with a `feeds` block, kind physical_qubits) applies in every scenario
    with the same qec family and a physical error rate <= its own. Runtime is never fed: it always
    comes from the Phase 3 model (a paper's own runtime is context, `paper_runtime_note`).
    Returns (qubits, source id, bound) or None.
    """
    best = None
    for eid, e in sorted(lit.items()):
        f = e.get("feeds")
        if not f or f["target"] != target or f["qec_family"] != QEC_FAMILY:
            continue
        if f["kind"] != "physical_qubits":
            raise ValueError(f"{eid}: only physical_qubits may be fed (got {f['kind']})")
        if scenario["physical_error_rate"] <= f["physical_error_rate"]:
            val = float(e["value"])
            if best is None or val < best[0]:
                best = (val, eid, f.get("bound"))
    return best


def build() -> dict:
    lit = common.literature()
    design = yaml.safe_load((ROOT / "quantum" / "risk" / "exposure.yaml").read_text())
    est = json.loads((cases.OUT / "scenarios.json").read_text())
    as_of = str(design["as_of"])
    as_of_year = int(as_of[:4])
    cap = float(design["runtime_cap_years"])

    entries = sorted(
        (e for e in lit.values() if e.get("target") == "timeline" and e["year"] <= as_of_year),
        key=lambda e: (e["year"], e["value"]),
    )
    points = [
        {"literature_id": e["id"], "year": int(e["year"]), "qubits": int(e["value"])}
        for e in entries
    ]
    front = tl.frontier(points)
    fit = tl.fit_timeline([p["year"] for p in front], [p["qubits"] for p in front])
    record = front[-1]
    record_point = min(
        (p for p in points if p["qubits"] == record["qubits"]), key=lambda p: p["year"]
    )
    baseline = {
        "year": record_point["year"],
        "qubits": record["qubits"],
        "literature_id": record_point["literature_id"],
    }
    raw_years, raw_qubits = [p["year"] for p in points], [p["qubits"] for p in points]
    raw = tl.fit_timeline(raw_years, raw_qubits)
    doubling = {
        "optimistic": fit["ci95"][0],
        "median": fit["doubling_years"],
        "pessimistic": fit["ci95"][1],
    }

    scenarios: dict = {}
    for sc in SCENARIOS:
        sc_spec = est["scenarios"][sc]
        targets = {}
        for t in TARGETS:
            model = est["targets"][t]["by_scenario"][sc]
            p, r = float(model["physical_qubits"]), float(model["runtime_seconds"])
            p_src = r_src = "model"
            bound = None
            feed = applicable_feeds(lit, t, sc_spec)
            if feed and feed[0] < p:
                p, p_src, bound = feed
            targets[t] = {
                "physical_qubits": p,
                "physical_source": p_src,
                "physical_bound": bound,
                "runtime_seconds": r,
                "runtime_source": r_src,
                "feasible": r / tl.SECONDS_PER_YEAR <= cap,
                "crqc_year": tl.crqc_year(p, r, record["qubits"], doubling[sc], as_of_year, cap),
            }
        scenarios[sc] = {"doubling_years": doubling[sc], "targets": targets}

    survey = lit["gri2025_half_of_experts_horizon"]
    model_year = scenarios["median"]["targets"]["rsa2048"]["crqc_year"]
    survey_year = int(survey["year"]) + int(survey["value"])
    clean = lambda xs: [None if x is None else float(x) for x in xs]  # noqa: E731
    return {
        "as_of": as_of,
        "as_of_year": as_of_year,
        "runtime_cap_years": cap,
        "points": points,
        "inclusion_rule": " ".join(str(design["timeline_inclusion_rule"]).split()),
        "frontier": front,
        "fit": {
            "doubling_years": fit["doubling_years"],
            "ci95": clean(fit["ci95"]),
            "r2": fit["r2"],
            "slope": fit["slope"],
            "intercept": fit["intercept"],
            "residuals": fit["residuals"],
            "holdout": tl.holdout([p["year"] for p in front], [p["qubits"] for p in front]),
        },
        "baseline": baseline,
        "scenarios": scenarios,
        "survey_check": {
            "literature_id": survey["id"],
            "survey_year": survey_year,
            "model_year": model_year,
            "delta_years": None if model_year is None else model_year - survey_year,
        },
        "sensitivity_raw_series": {
            "note": "Not used downstream. Fit on the raw per-year points; they are not monotone "
            "(IBM moved from size to quality after 2023), so this fit and its holdout are "
            "shown only to bound the choice of the frontier.",
            "doubling_years": raw["doubling_years"],
            "ci95": clean(raw["ci95"]),
            "r2": raw["r2"],
            "holdout": tl.holdout(raw_years, raw_qubits),
        },
    }


def main() -> int:
    res = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    f = res["fit"]
    print(
        f"points={len(res['points'])} doubling={f['doubling_years']:.4g} ci95={f['ci95']} "
        f"r2={f['r2']:.3f} holdout_rel_error={f['holdout']['rel_error']:.3g}"
    )
    for sc, s in res["scenarios"].items():
        for t, r in s["targets"].items():
            cy = r["crqc_year"]
            print(
                f"{sc:12s} {t:8s} P={r['physical_qubits']:.4g} ({r['physical_source']}) "
                f"R={r['runtime_seconds']:.4g}s ({r['runtime_source']}) "
                f"crqc={'null' if cy is None else f'{cy:.1f}'}"
            )
    sv = res["survey_check"]
    print(
        f"survey_year={sv['survey_year']} model_year={sv['model_year']} delta={sv['delta_years']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
