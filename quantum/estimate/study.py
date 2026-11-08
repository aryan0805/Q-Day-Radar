"""Cross-check, scaling fits and literature calibration, computed from the per-case files only."""

from __future__ import annotations

import json
import math
import statistics

from quantum.estimate import common, physical, scaling
from quantum.estimate.cases import OUT

TARGET_N = 2048


def load(dirname: str) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted((OUT / dirname).glob("*.json"))}


def ratio(a: float, b: float) -> float:
    return max(a, b) / min(a, b)


def _qubits_qdk(rec: dict) -> int:
    return rec["logical_counts"]["num_qubits"]


def crosscheck(qdk: dict[str, dict], qt: dict[str, dict]) -> dict:
    rows = []
    for case, q in qdk.items():
        t = qt.get(case)
        if t and t["method"] == "same_circuit":
            if t["circuit_sha256"] != q["circuit_sha256"]:
                raise RuntimeError(f"{case}: tools were given different circuits")
            rows.append(
                {
                    "case": case,
                    "kind": "same_circuit",
                    "qdk": case,
                    "qualtran": case,
                    "ratio_logical_qubits": ratio(_qubits_qdk(q), t["logical_qubits"]),
                    "ratio_toffoli_equiv": ratio(q["toffoli_equiv"], t["toffoli_equiv"]),
                }
            )
        if q["N"] and q["base_a"] and case.startswith("beauregard_"):
            fid = f"modexp_N{q['N']}_a{q['base_a']}"
            if fid in qt:
                rows.append(
                    {
                        "case": f"{case}__vs__{fid}",
                        "kind": "same_function",
                        "qdk": case,
                        "qualtran": fid,
                        "ratio_logical_qubits": ratio(_qubits_qdk(q), qt[fid]["logical_qubits"]),
                        "ratio_toffoli_equiv": ratio(q["toffoli_equiv"], qt[fid]["toffoli_equiv"]),
                    }
                )
    return {"cases": rows}


def _points(recs: list[dict], value) -> list[dict]:
    by_n: dict[int, list[dict]] = {}
    for r in recs:
        by_n.setdefault(r["n_bits"], []).append(r)
    pts = []
    for n in sorted(by_n):
        vals = [value(r) for r in by_n[n]]
        med = statistics.median(vals)
        pts.append(
            {
                "n_bits": n,
                "N": by_n[n][0]["N"] if len({r["N"] for r in by_n[n]}) == 1 else None,
                "bases": [r["base_a"] for r in by_n[n]],
                "value": med,
                "spread": (max(vals) - min(vals)) / med if med else 0.0,
            }
        )
    return pts


FIT_FNS = {
    "power_law": scaling.fit_power_law,
    "linear": scaling.fit_linear,
    "poly_n4": scaling.fit_poly,
}


def _fit(estimator: str, quantity: str, model: str, pts: list[dict]) -> dict:
    xs = [p["n_bits"] for p in pts]
    ys = [p["value"] for p in pts]
    fn = FIT_FNS[model]
    fit = fn(xs, ys)
    return {
        "estimator": estimator,
        "quantity": quantity,
        "model": model,
        "points": pts,
        "params": fit["params"],
        "exponent": fit["exponent"] if model != "linear" else 1.0,
        "r2": fit["r2"],
        "residuals": [{"n_bits": int(r["x"]), "rel": r["rel"]} for r in fit["residuals"]],
        "holdout": scaling.holdout(xs, ys, fn),
        "extrapolated": {"n_bits": TARGET_N, "value": scaling.predict(fit, TARGET_N)},
    }


def _budget_eps_extrapolation(recs: list[dict]) -> dict:
    """Extrapolate rotation count and the rest separately, then price rotations at the eps that
    fits the error budget (eps = budget / rotation_count(2048)). Separate field: the per-case
    files keep the one shared eps."""
    rot = _points(recs, lambda r: r["logical_counts"]["rotation_count"])
    rest = _points(
        recs,
        lambda r: (
            r["logical_counts"]["ccz_count"]
            + r["logical_counts"]["ccix_count"]
            + r["logical_counts"]["t_count"] / 4
        ),
    )
    fit_r = scaling.fit_poly([p["n_bits"] for p in rot], [p["value"] for p in rot])
    fit_o = scaling.fit_poly([p["n_bits"] for p in rest], [p["value"] for p in rest])
    rot_n = scaling.predict(fit_r, TARGET_N)
    rest_n = scaling.predict(fit_o, TARGET_N)
    budget = float(physical.load_spec()["error_budget"])
    eps = budget / rot_n
    cost = common.rotation_t_cost(eps)
    return {
        "n_bits": TARGET_N,
        "model": "poly_n4 on rotation_count and on (ccz + ccix + t/4) separately",
        "rotation_count": rot_n,
        "non_rotation_toffoli_equiv": rest_n,
        "error_budget": budget,
        "eps": eps,
        "rotation_t_cost": cost,
        "value": rest_n + rot_n * cost / 4,
    }


POOR_FIT = 0.05  # |signed residual| or holdout error above this needs a caveat and a range


def _is_poor(f: dict) -> bool:
    return (
        f["holdout"]["rel_error"] > POOR_FIT
        or max(abs(r["rel"]) for r in f["residuals"]) > POOR_FIT
    )


def _last_slope_continuation(pts: list[dict]) -> float:
    """Value at n=2048 if the local log-log slope between the two largest sizes persisted."""
    a, b = pts[-2], pts[-1]
    slope = math.log(b["value"] / a["value"]) / math.log(b["n_bits"] / a["n_bits"])
    return b["value"] * (TARGET_N / b["n_bits"]) ** slope


def _annotate_group(group: list[dict], pts: list[dict], budget_eps: dict | None) -> None:
    """Add caveat, low/high and eps-consistent fields to the toffoli_equiv fits of one estimator."""
    cont = _last_slope_continuation(pts)
    values = [f["extrapolated"]["value"] for f in group] + [cont]
    for f in group:
        ext = f["extrapolated"]
        ext["low"], ext["high"] = min(values), max(values)
        own = ext["value"]
        f["extrapolated_range"] = {"low": min(own, cont), "high": max(own, cont)}
        f["last_slope_continuation"] = cont
        if budget_eps:
            f["extrapolated_budget_eps"] = budget_eps
            # same fit, rotations re-priced: scale by the repricing factor of the rotation part
            shared = budget_eps["non_rotation_toffoli_equiv"] + (
                budget_eps["rotation_count"] * common.rotation_t_cost(common.ROTATION_EPS) / 4
            )
            ext["eps_consistent_value"] = own * budget_eps["value"] / shared
            ext["eps_consistent_rotation_t_cost"] = budget_eps["rotation_t_cost"]
        else:  # no rotations in this tool's circuits: nothing to re-price
            ext["eps_consistent_value"] = own
            ext["eps_consistent_rotation_t_cost"] = common.rotation_t_cost(common.ROTATION_EPS)
        if _is_poor(f):
            worst = max(abs(r["rel"]) for r in f["residuals"])
            text = (
                f"{f['model']} fitted to n = {pts[0]['n_bits']}..{pts[-1]['n_bits']} and evaluated "
                f"at n = {TARGET_N}; worst signed residual {worst:.3f}, holdout error "
                f"{f['holdout']['rel_error']:.3f}. The extrapolation spans far beyond the data: "
                f"models and the last local slope disagree from {min(values):.3g} to "
                f"{max(values):.3g}."
            )
            f["caveat"] = text
            f["extrapolation_caveat"] = text


def fits(qdk: dict[str, dict], qt: dict[str, dict]) -> dict:
    qdk_recs = [r for c, r in qdk.items() if c.startswith("beauregard_")]
    fams = {
        "qdk": (qdk_recs, _qubits_qdk),
        "qualtran": (
            [r for c, r in qt.items() if c.startswith("modexp_")],
            lambda r: r["logical_qubits"],
        ),
    }
    out = []
    for name, (recs, qubits) in fams.items():
        pts = _points(recs, lambda r: r["toffoli_equiv"])
        group = [_fit(name, "toffoli_equiv", m, pts) for m in ("power_law", "poly_n4")]
        best = min(group, key=lambda f: f["holdout"]["rel_error"])
        for f in group:
            f["selected"] = f is best
        _annotate_group(group, pts, _budget_eps_extrapolation(recs) if name == "qdk" else None)
        out += group
        lin = _fit(name, "logical_qubits", "linear", _points(recs, qubits))
        lin["selected"] = True
        if _is_poor(lin):
            lin["caveat"] = lin["extrapolation_caveat"] = "linear fit with large residuals"
            lin["extrapolated"]["low"] = lin["extrapolated"]["high"] = lin["extrapolated"]["value"]
        out.append(lin)
    return {"fits": out}


def parse_power(text: str | float) -> float:
    return common.parse_power(text)


_DAY, _HOUR = 86400.0, 3600.0
_UNIT_SECONDS = {"days": _DAY, "hours": _HOUR, "seconds": 1.0}


def calibration(qdk, qt, scal: dict) -> dict:
    lit = common.literature()
    sel = {(f["estimator"], f["quantity"]): f for f in scal["fits"] if f["selected"]}
    comps: list[dict] = []

    def add(target, estimator, quantity, ours, lit_id, label, explanation, method="", **extra):
        theirs = parse_power(lit[lit_id]["value"])
        comps.append(
            {
                "target": target,
                "estimator": estimator,
                "method": method,
                "label": label,
                "quantity": quantity,
                "ours": ours,
                "literature_id": lit_id,
                "literature_value": theirs,
                "ratio": ours / theirs,
                "explanation": explanation,
                **extra,
            }
        )

    q_sel = sel[("qdk", "toffoli_equiv")]
    q_beau = q_sel["extrapolated"]["value"]
    add(
        "rsa2048",
        "qdk",
        "toffoli_equiv",
        q_beau,
        "ge2019_toffoli_rsa2048",
        "extrapolated",
        "Beauregard Fourier-adder circuit, rotations priced at the shared eps (1e-10); "
        "Gidney-Ekera use windowed arithmetic and Toffoli-based adders. Extrapolated far beyond "
        f"the fitted range (n = 4..14); model chosen by holdout: {q_sel['model']}.",
        method=f"extrapolated: {q_sel['model']} fit of the Beauregard family at n=2048",
    )
    b = q_sel["extrapolated_budget_eps"]
    add(
        "rsa2048",
        "qdk",
        "toffoli_equiv",
        b["value"],
        "ge2019_toffoli_rsa2048",
        "extrapolated",
        "Same extrapolation with rotations priced at eps = error_budget / rotation_count(2048) "
        "(the shared eps would exceed the budget at this size). Its rotation_t_cost is in the "
        "field extrapolated_budget_eps.",
        method="extrapolated: poly_n4 on rotation_count and non-rotation part, budget eps",
        extrapolated_budget_eps=b,
    )
    rsa = qt["rsa2048_modexp"]
    meas = "measured: ModExp bloq at a 2048-bit N"
    add(
        "rsa2048",
        "qualtran",
        "toffoli_equiv",
        rsa["toffoli_equiv"],
        "ge2019_toffoli_rsa2048",
        "measured",
        "Qualtran ModExp is schoolbook (no windowing or coset representation), so it costs more "
        "Toffolis than the optimised constructions in the literature. Cross-check: the selected "
        f"{sel[('qualtran', 'toffoli_equiv')]['model']} fit of the ModExp family gives "
        f"{sel[('qualtran', 'toffoli_equiv')]['extrapolated']['value']:.4g} at n=2048, the "
        f"directly measured bloq gives {rsa['toffoli_equiv']:.4g}.",
        method=meas,
    )
    add(
        "rsa2048",
        "qualtran",
        "toffoli_equiv",
        rsa["toffoli_equiv"],
        "g2025_toffoli_rsa2048",
        "measured",
        "Same, against Gidney 2025 (approximate modular exponentiation).",
        method=meas,
    )
    add(
        "rsa2048",
        "qualtran",
        "logical_qubits",
        rsa["logical_qubits"],
        "g2025_logical_qubits_rsa2048",
        "measured",
        "Literature value is an upper bound (<1600). Qualtran ModExp holds three n-bit registers.",
        method=meas,
    )
    ecc = qt["ecc256_ecadd"]
    proj = "projection: measured ECAdd at n=256 times 2n point additions"
    add(
        "ecc256",
        "qualtran",
        "toffoli_equiv",
        ecc["projection"]["toffoli_equiv"],
        "roetteler2017_toffoli_p256",
        "projection",
        "One measured Qualtran ECAdd at n=256 times 2n additions; Roetteler counts the whole "
        "algorithm with its own point-addition circuit.",
        method=proj,
    )
    add(
        "ecc256",
        "qualtran",
        "toffoli_equiv",
        ecc["projection"]["toffoli_equiv"],
        "litinski2023_toffoli_per_key",
        "projection",
        "Litinski's 109 million Toffolis use windowed point additions and a different circuit.",
        method=proj,
    )
    add(
        "ecc256",
        "qualtran",
        "logical_qubits",
        ecc["logical_qubits"],
        "roetteler2017_logical_qubits_p256",
        "measured",
        "Single-addition register width against the whole algorithm.",
        method="measured: ECAdd bloq, symbolic n evaluated at 256",
    )
    comps += _physical_rows(lit)
    comps += _v2_rows(lit)
    comps += _aes_projection(qdk, lit)
    return {"comparisons": comps}


def _physical_rows(lit: dict) -> list[dict]:
    """Our physical model fed each paper's own logical counts and hardware assumptions, against
    that paper's physical figures. Differences come from what the QDK model lacks."""
    budget = float(physical.load_spec()["error_budget"])
    common_why = (
        "QDK built-in surface_code scheme: every algorithmic logical qubit is a 2*d^2 patch "
        "(its layout also adds logical qubits), CCZ = 4 T states, T factories from QDK's default "
        "distillation units, error budget set by us (0.01), not by the paper."
    )
    specs = [
        {
            "target": "rsa2048",
            "paper": "ge2019",
            "qubits": common.eval_formula(lit["ge2019_logical_qubits_formula"]["value"], 2048),
            "ccz": "ge2019_toffoli_rsa2048",
            "err": "ge2019_physical_error_rate",
            "cyc": "ge2019_cycle_time",
            "phys": "ge2019_physical_qubits_rsa2048",
            "time": "ge2019_runtime_rsa2048",
            "why": "Gidney-Ekera 2019 report 20 million qubits using CCZ factories and "
            "lookup/runway layouts (Table 2); the Toffoli+T/2 count is used here as CCZ count. "
            + common_why,
        },
        {
            "target": "rsa2048",
            "paper": "g2025",
            "qubits": common.parse_power(lit["g2025_logical_qubits_rsa2048"]["value"]),
            "ccz": "g2025_toffoli_rsa2048",
            "err": "ge2019_physical_error_rate",
            "cyc": "ge2019_cycle_time",
            "phys": "g2025_physical_qubits_rsa2048",
            "time": "g2025_runtime_rsa2048",
            "why": "Gidney 2025 stores idle logical qubits in yoked surface codes (cold storage, "
            "denser than 2*d^2 per qubit) and uses magic state cultivation with fewer factories "
            "(abstract; Section 3.2); QDK has neither. " + common_why,
        },
        {
            "target": "ecc256",
            "paper": "litinski2023",
            "qubits": common.parse_power(lit["litinski2023_logical_qubits"]["value"]),
            "ccz": "litinski2023_toffoli_per_key",
            "err": "ge2019_physical_error_rate",
            "cyc": "ge2019_cycle_time",
            "phys": "litinski2023_physical_qubits",
            "time": "litinski2023_runtime_superconducting",
            "why": "Litinski 2023 states the error rate as 10% of the surface-code threshold; with "
            "a 1% threshold that is the 1e-3 used here (threshold not in literature.yaml). Cycle "
            "1 us as in its superconducting case (litinski2023_runtime_superconducting). Its "
            "architecture (6000 logical qubits, parallel modules, non-local connections, d = 28 "
            "patches) is not what QDK models. " + common_why,
        },
    ]
    rows = []
    for sp in specs:
        ccz = int(common.parse_power(lit[sp["ccz"]]["value"]))
        counts = {
            "numQubits": int(sp["qubits"]),
            "tCount": 0,
            "rotationCount": 0,
            "rotationDepth": 0,
            "cczCount": ccz,
            "ccixCount": 0,
            "measurementCount": ccz,
        }
        scen = {
            "physical_error_rate": float(lit[sp["err"]]["value"]),
            "cycle_time_seconds": float(lit[sp["cyc"]]["value"]),
            "qec_scheme": "surface_code",
            "error_budget": budget,
        }
        est = physical.physical_estimate(counts, scen)
        unit = _UNIT_SECONDS[lit[sp["time"]]["units"]]
        for quantity, ours, lit_id, scale in (
            ("physical_qubits", est["physical_qubits"], sp["phys"], 1.0),
            ("runtime_seconds", est["runtime_seconds"], sp["time"], unit),
        ):
            theirs = float(lit[lit_id]["value"]) * scale
            rows.append(
                {
                    "target": sp["target"],
                    "estimator": "physical",
                    "method": f"measured: QDK physical model fed {sp['paper']}'s logical counts",
                    "label": "measured",
                    "quantity": quantity,
                    "ours": ours,
                    "literature_id": lit_id,
                    "literature_value": theirs,
                    "literature_unit_note": f"{lit[lit_id]['units']} x {scale:g} = seconds"
                    if scale != 1.0
                    else lit[lit_id]["units"],
                    "ratio": ours / theirs,
                    "explanation": sp["why"],
                    "input_logical_counts": counts,
                    "input_hardware": {
                        "physical_error_rate": scen["physical_error_rate"],
                        "cycle_time_seconds": scen["cycle_time_seconds"],
                        "qec_scheme": scen["qec_scheme"],
                        "error_budget": scen["error_budget"],
                    },
                    "code_distance": est["code_distance"],
                }
            )
    return rows


def _aes_projection(qdk: dict[str, dict], lit: dict) -> list[dict]:
    """Toy-SPN Grover (k = 2..5, peel_last_sbox=False) projected to k = 128. A projection, not
    an AES estimate."""
    import math

    from quantum.circuits.grover_present import default_iterations

    ks = [2, 3, 4, 5]
    recs = [qdk[f"grover_present_k{k}_nopeel"] for k in ks]
    assert all(r["peel_last_sbox"] is False for r in recs)
    per_iter = [r["toffoli_equiv"] / default_iterations(k) for k, r in zip(ks, recs, strict=True)]
    qfit = scaling.fit_linear(ks, [_qubits_qdk(r) for r in recs])
    cfit = scaling.fit_power_law(ks, per_iter)
    iters = math.floor(math.pi / 4 * 2**64)
    q128 = scaling.predict(qfit, 128)
    r2 = cfit["r2"]
    resid = [{"k": int(r["x"]), "rel": r["rel"]} for r in cfit["residuals"]]
    unreliable = (
        f"unreliable (r2={r2:.3f}; signed residuals "
        + ", ".join(f"k={r['k']}: {r['rel']:+.2f}" for r in resid)
        + "). "
        if r2 < 0.9
        else ""
    )
    t128 = scaling.predict(cfit, 128) * iters * 4  # T-equivalent (toffoli_equiv * 4)
    base = {
        "target": "aes128",
        "estimator": "qdk",
        "method": "projection: toy-SPN k=2..5 (peel_last_sbox=False) fit evaluated at k=128",
        "label": "projection",
        "peel_last_sbox": False,
        "fit_r2": r2,
        "fit_residuals": resid,
    }
    why = unreliable + (
        "Toy 4-round SPN with a k-bit key, 4 data points (k = 2..5), costed with "
        "peel_last_sbox=False; not an AES estimate and no error bar. "
    )
    q_lit = common.parse_power(lit["grassl2016_logical_qubits_aes128"]["value"])
    t_lit = common.parse_power(lit["grassl2016_t_gates_aes128"]["value"])
    return [
        {
            **base,
            "quantity": "logical_qubits",
            "ours": q128,
            "literature_id": "grassl2016_logical_qubits_aes128",
            "literature_value": q_lit,
            "ratio": q128 / q_lit,
            "explanation": why
            + "The qubit count is a straight-line fit of the toy circuits' qubits against k, "
            "evaluated at k = 128, so it is not an integer (a fit value, not a circuit).",
        },
        {
            **base,
            "quantity": "t_equiv_total",
            "ours": t128,
            "literature_id": "grassl2016_t_gates_aes128",
            "literature_value": t_lit,
            "ratio": t128 / t_lit,
            "explanation": why
            + "Per-iteration toffoli_equiv fitted as a power law in k, times floor(pi/4*2^64) "
            "iterations, times 4 to give T-equivalents (Grassl's column is T gates).",
        },
    ]


def _v2_rows(lit: dict) -> list[dict]:
    """Physical model v2 fed each paper's own logical qubits at that paper's error rate, against the
    paper's own physical-qubit figure. Pre-registered tolerance (lead): RSA two-sided within the
    factor, ECC one-sided (v2 must not exceed the factor times the paper's bound)."""
    spec = physical.load_spec()["physical_v2"]
    factor = float(spec["tolerance_factor"])
    rows = []
    for target, lit_id, qubits_id, err_id, kind in (
        (
            "rsa2048",
            "g2025_physical_qubits_rsa2048",
            "g2025_max_algorithmic_logical_qubits",
            "g2025_physical_error_rate",
            "two_sided",
        ),
        (
            "ecc256",
            "google2026_physical_qubits_ecc256",
            "google2026_logical_qubits_ecc256",
            "google2026_physical_error_rate",
            "one_sided",
        ),
    ):
        logical = float(lit[qubits_id]["value"])
        err = float(lit[err_id]["value"])
        v2 = physical.physical_estimate_v2(logical, err)
        theirs = float(lit[lit_id]["value"])
        ratio = v2["physical_qubits"] / theirs
        within = (1 / factor <= ratio <= factor) if kind == "two_sided" else ratio <= factor
        rows.append(
            {
                "target": target,
                "estimator": "physical_v2",
                "method": "measured: physical model v2 fed the paper's own logical qubits",
                "label": "measured",
                "quantity": "physical_qubits",
                "ours": v2["physical_qubits"],
                "literature_id": lit_id,
                "literature_value": theirs,
                "ratio": ratio,
                "tolerance": {"kind": kind, "factor": factor, "within": within},
                "input_logical_qubits": logical,
                "input_logical_qubits_id": qubits_id,
                "v2": v2,
                "explanation": (
                    "Pre-registered check (components from Gidney 2025 only). "
                    + (
                        "Consistency check on the paper's own numbers (two-sided): v2 rebuilds the "
                        "paper's accounting, so agreement is expected, not independent evidence."
                        if kind == "two_sided"
                        else "Holdout (one-sided): v2 must not exceed the factor times the paper's "
                        "upper bound. "
                        + (
                            "It passes."
                            if within
                            else "It FAILS the tolerance. Not tuned. Likely cause, not acted on: "
                            "v2 carries RSA's cold-storage fraction and compute block over to ECC."
                        )
                    )
                ),
            }
        )
    return rows
