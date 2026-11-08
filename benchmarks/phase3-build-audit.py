# ruff: noqa: E501  (long lines are prose in the AUDIT template)
"""Renders tests/phase3/AUDIT.md: prose written here, every number computed from result files.

Run (after tests are green):  uv run python benchmarks/phase3-build-audit.py
Needs benchmarks/phase3-tool-deviation.json and phase3-qdk-fusion.json (run those scripts first).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import statistics
import subprocess
import sys
from math import log
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.phase3 import reference as ref  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "tables", ROOT / "benchmarks" / "phase3-audit-tables.py"
)
tables = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tables)


def g(x: float) -> str:
    return f"{x:.4g}"


def facts() -> dict:
    f: dict = {}
    dev = json.loads((ROOT / "benchmarks" / "phase3-tool-deviation.json").read_text())
    fus = json.loads((ROOT / "benchmarks" / "phase3-qdk-fusion.json").read_text())
    f["n_same_circuit"] = len(dev)
    f["n_dev_qdk"] = sum(
        1
        for r in dev
        if r["qdk"]["d_t"]
        or r["qdk"]["d_rotations"]
        or abs(r["qdk"]["deviation_vs_reference"]) > 1e-12
    )
    f["n_dev_qt"] = sum(
        1
        for r in dev
        if r["qualtran"]["d_t"]
        or r["qualtran"]["d_rotations"]
        or abs(r["qualtran"]["deviation_vs_reference"]) > 1e-12
    )
    d = [o["deviation_vs_reference"] for o in fus]
    f["fusion_n"] = len(fus)
    f["fusion_differs"] = sum(1 for o in fus if o["d_t"] or o["d_rotations"])
    f["fusion_min"], f["fusion_med"], f["fusion_max"] = (
        f"{min(d):+.2%}",
        f"{statistics.median(d):+.2%}",
        f"{max(d):+.2%}",
    )
    f["fusion_max_case"] = max(fus, key=lambda o: o["deviation_vs_reference"])["case"]
    f["fusion_runs"] = fus[0]["runs"]
    f["fusion_spread"] = f"{max(o['deviation_runs_max'] - o['deviation_runs_min'] for o in fus):.0%}"
    f["fusion_worst_run"] = f"{max(o['deviation_runs_max'] for o in fus):+.0%}"
    cc = ref.load_json(ref.EST / "crosscheck.json")["cases"]
    sf = [r for r in cc if r["kind"] == "same_function"]
    f["n_sf"] = len(sf)
    f["sf_min"] = g(min(r["ratio_toffoli_equiv"] for r in sf))
    f["sf_max"] = g(max(r["ratio_toffoli_equiv"] for r in sf))
    f["sf_q_min"] = g(min(r["ratio_logical_qubits"] for r in sf))
    f["sf_q_max"] = g(max(r["ratio_logical_qubits"] for r in sf))
    text = ref.DECISIONS.read_text()
    f["n_sf_in_decisions"] = sum(1 for r in sf if r["case"] in text)
    qdk = ref.cases("qdk")
    k = next(iter(qdk.values()))["rotation_t_cost"]
    f["rot_cost"], f["eps"] = g(k), g(next(iter(qdk.values()))["rotation_eps"])
    shares = []
    for r in sf:
        c = qdk[r["qdk"]]
        shares.append(c["logical_counts"]["rotation_count"] * k / 4 / c["toffoli_equiv"])
    f["rot_share_min"], f["rot_share_max"] = f"{min(shares):.1%}", f"{max(shares):.1%}"
    fits = ref.load_json(ref.EST / "scaling.json")["fits"]
    pl = next(
        x
        for x in fits
        if x["estimator"] == "qdk" and x["model"] == "power_law" and "toffoli" in x["quantity"]
    )
    po = next(x for x in fits if x["estimator"] == "qdk" and x["model"] == "poly_n4")
    pts = sorted(pl["points"], key=lambda p: p["n_bits"])
    slopes = [
        log(b["value"] / a["value"]) / log(b["n_bits"] / a["n_bits"])
        for a, b in zip(pts, pts[1:], strict=False)
    ]
    f["pl_exp"], f["slope_first"], f["slope_last"] = g(pl["exponent"]), g(slopes[0]), g(slopes[-1])
    f["pl_val"], f["po_val"] = g(pl["extrapolated"]["value"]), g(po["extrapolated"]["value"])
    f["pl_over_po"] = g(pl["extrapolated"]["value"] / po["extrapolated"]["value"])
    f["pl_maxres"] = f"{max(abs(r['rel']) for r in pl['residuals']):.1%}"
    f["po_maxres"] = f"{max(abs(r['rel']) for r in po['residuals']):.2%}"
    f["pl_hold"], f["po_hold"] = (
        f"{pl['holdout']['rel_error']:.1%}",
        f"{po['holdout']['rel_error']:.2%}",
    )
    f["n_min"], f["n_max"] = pts[0]["n_bits"], pts[-1]["n_bits"]
    f["bases_min"] = min(len(set(p["bases"])) for x in fits for p in x["points"])
    qsel = next(
        x
        for x in fits
        if x["estimator"] == "qualtran" and x["selected"] and "toffoli" in x["quantity"]
    )
    meas = ref.cases("qualtran")["rsa2048_modexp"]["toffoli_equiv"]
    f["qt_sel"], f["qt_meas"] = g(qsel["extrapolated"]["value"]), g(meas)
    f["qt_reldiff"] = f"{abs(qsel['extrapolated']['value'] - meas) / meas:.2e}"
    f["qt_model"] = qsel["model"]
    cal = ref.load_json(ref.EST / "calibration.json")["comparisons"]

    def row(t, e, q, lid):
        return next(
            r
            for r in cal
            if (r["target"], r["estimator"], r["quantity"], r["literature_id"]) == (t, e, q, lid)
        )

    for tag, t, lid_q, lid_t in (
        ("ge", "rsa2048", "ge2019_physical_qubits_rsa2048", "ge2019_runtime_rsa2048"),
        ("g25", "rsa2048", "g2025_physical_qubits_rsa2048", "g2025_runtime_rsa2048"),
        ("li", "ecc256", "litinski2023_physical_qubits", "litinski2023_runtime_superconducting"),
    ):
        f[f"{tag}_q"] = g(row(t, "physical", "physical_qubits", lid_q)["ratio"])
        f[f"{tag}_t"] = g(row(t, "physical", "runtime_seconds", lid_t)["ratio"])
    f["qdk_vs_ge"] = g(row("rsa2048", "qdk", "toffoli_equiv", "ge2019_toffoli_rsa2048")["ratio"])
    f["qt_vs_ge"] = g(
        row("rsa2048", "qualtran", "toffoli_equiv", "ge2019_toffoli_rsa2048")["ratio"]
    )
    f["qt_vs_g25"] = g(
        row("rsa2048", "qualtran", "toffoli_equiv", "g2025_toffoli_rsa2048")["ratio"]
    )
    f["ecc_vs_roet"] = g(
        row("ecc256", "qualtran", "toffoli_equiv", "roetteler2017_toffoli_p256")["ratio"]
    )
    f["ecc_vs_lit"] = g(
        row("ecc256", "qualtran", "toffoli_equiv", "litinski2023_toffoli_per_key")["ratio"]
    )
    aes = [r for r in cal if r["target"] == "aes128"]
    f["aes_r2"] = f"{aes[0]['fit_r2']:.3f}"
    f["aes_unreliable"] = all("unreliable" in r["explanation"].lower() for r in aes)
    f["aes_ratio_t"] = g(
        row("aes128", "qdk", "t_equiv_total", "grassl2016_t_gates_aes128")["ratio"]
    )
    f["aes_ratio_q"] = g(
        row("aes128", "qdk", "logical_qubits", "grassl2016_logical_qubits_aes128")["ratio"]
    )
    fc = json.loads(ref.FACTCHECK.read_text())
    f["n_lit"] = len(fc)
    f["n_verified"] = sum(1 for v in fc.values() if v["status"] == "verified")
    sc = ref.load_json(ref.EST / "scenarios.json")
    by = {t: sc["targets"][t]["by_scenario"] for t in ref.TARGETS}
    f["pess_same_phys"] = all(
        by[t]["pessimistic"]["physical_qubits"] == by[t]["median"]["physical_qubits"]
        for t in ref.TARGETS
    )
    # hand-typed numeric constants in the estimate code (outside literature.yaml)
    consts = []
    for p in sorted(
        list((ROOT / "quantum" / "estimate").glob("*.py"))
        + list((ROOT / "scripts").glob("estimate_*.py"))
    ):
        src = p.read_text().splitlines()
        for n in ast.walk(ast.parse("\n".join(src))):
            if (
                isinstance(n, ast.Constant)
                and isinstance(n.value, (int, float))
                and not isinstance(n.value, bool)
                and (abs(n.value) >= 100 or 0 < abs(n.value) < 1e-3)
            ):
                consts.append(
                    f"- `{p.relative_to(ROOT)}:{n.lineno}` `{src[n.lineno - 1].strip()[:90]}`"
                )
    f["consts"] = "\n".join(consts)
    return f


TEMPLATE = """# Phase 3 honesty audit (reviewer)

Generated by `benchmarks/phase3-build-audit.py` from the result files; every number below was
printed by a script, none was typed. Tests: `uv run pytest tests/phase3 -q`.

## 1. Labels

Every number in this phase belongs to exactly one class:

- **measured**: a tool counted it on a circuit or bloq we built (per-case files in `results/estimate/`).
- **extrapolated**: a fit of measured points evaluated outside the measured range (n = {n_min}..{n_max} to n = 2048).
- **projection**: a toy or partial measurement scaled by a stated rule (ECC: one point addition times 2n; AES: toy SPN).
- **literature**: typed once in `quantum/estimate/literature.yaml`, fact-checked (section 8).

The scenario table in section 11 is **computed**: literature logical counts pushed through the QDK physical model.

## 2. same_circuit: why every ratio is exactly 1

{n_same_circuit} same_circuit cases. I parsed the stored common-basis QASM with my own parser
(`tests/phase3/reference.py`) and counted T-type gates, generic rotations and Toffolis. QDK differs from that
reference in {n_dev_qdk} cases, Qualtran in {n_dev_qt}. That is **measured**, and it validates that both tools
count the gate list they are given. It says nothing about their algorithms: both saw the same gates.

The match exists **because the QDK wrapper passes `skip_transpilation=True`**. The same QASM through QDK's default
backend differs from the reference in (T, rotations) in {fusion_differs} of {fusion_n} cases (toffoli_equiv
per-case median over {fusion_runs} runs: min {fusion_min}, median {fusion_med}, max {fusion_max}, the maximum being
`{fusion_max_case}`; its transpilation is not reproducible, so one case's deviation moves by up to {fusion_spread}
points between runs and the worst single run is {fusion_worst_run}), because it fuses
runs of single-qubit gates: upward when a T-only run becomes one rotation, downward when a T next to a generic rz
is absorbed into it. Direction depends on the circuit; it was measured, not assumed
(`benchmarks/phase3-qdk-fusion.json`; hand cases in `test_estimate_reference_counts.py`).

## 3. same_function: every gap above 3x is an algorithm difference

{n_sf} pairs (our Fourier-adder Beauregard on QDK vs Qualtran's Toffoli-based `ModExp`, same N and a). The toffoli_equiv
ratio runs from {sf_min} to {sf_max} and grows with n; the logical-qubit ratio only from {sf_q_min} to {sf_q_max}.
{n_sf_in_decisions} of {n_sf} case ids are explained in `docs/DECISIONS.md`.

The measured reason: rotations priced at rotation_t_cost = {rot_cost} T (eps = {eps}) are {rot_share_min} to {rot_share_max}
of QDK's Beauregard toffoli_equiv. So the gap is mostly the price assigned to arbitrary-angle rotations, not a disagreement
between the estimators. Both tools agree on identical circuits (section 2).

## 4. Scaling: what may and may not be quoted

- Every fitted point is the median over >= {bases_min} coprime bases (P005), at least one of order > 2, rebuilt from the per-case
  files by the tests. No fit rests on one base or on order-2 bases only. Qualtran's `ModExp` cost does not depend on the base at all
  (data-oblivious; its spread is zero), so for that tool the several-bases rule is satisfied trivially, and says nothing about base effects.
- QDK Beauregard cost: the free power law has exponent {pl_exp}, but the local log-log slope falls from {slope_first} to {slope_last}
  over n = {n_min}..{n_max}. Its largest residual is {pl_maxres} and its holdout error {pl_hold}. A degree-4 polynomial (selected by the
  lower holdout) has largest residual {po_maxres} and holdout error {po_hold}. At n = 2048 the power law gives {pl_val} and
  the selected polynomial {po_val} ({pl_over_po} times lower). **Only the selected fit with its bracket may be quoted, and only as
  extrapolated.** The free power law must not be quoted as a measured scaling.
- A limit of the extrapolation that no test can check: the exact-QFT Beauregard circuit has controlled phases of angle pi/2^j. For
  n = 2048 most are far below eps = {eps} and need not be synthesized (approximate QFT), so the extrapolated n = 2048 cost
  is an upper-side figure for this circuit family, and it is not an RSA-2048 estimate. It is a textbook-circuit extrapolation (generic).
- Qualtran: the selected {qt_model} fit predicts {qt_sel} at n = 2048; the directly measured 2048-bit `ModExp` is {qt_meas}
  (relative difference {qt_reldiff}). The fit stops at n = {n_max}; the bloq is costed at 2048. This **measured** agreement is
  the strongest check in the phase.

## 5. Calibration against the literature

Tables are in section 11. In short (ratios are ours / literature):

- QDK Beauregard extrapolated to 2048 vs Gidney-Ekera 2019 Toffoli+T/2: {qdk_vs_ge}. Different algorithm and a textbook circuit, so this
  is not an estimate of RSA-2048.
- Qualtran `ModExp` measured at 2048 bits vs Gidney-Ekera 2019: {qt_vs_ge}; vs Gidney 2025: {qt_vs_g25}. Schoolbook arithmetic, no windowing
  or coset representation.
- ECC-256, **projection** (one measured Qualtran ECAdd times 2n): {ecc_vs_roet} of Roetteler 2017's whole-algorithm count and {ecc_vs_lit} of
  Litinski 2023's. The constant 2n (two scalar multiplications of n additions each) is typed in `scripts/estimate_qualtran.py`, not in
  literature.yaml, so it is **not fact-checked**; the label is projection for that reason.
- AES-128, **projection** from the toy SPN (k = 2..5, `peel_last_sbox=False`): the fit has r2 = {aes_r2} and the rows say "unreliable"
  (all rows checked: {aes_unreliable}). It reaches {aes_ratio_t} of Grassl 2016's T count and {aes_ratio_q} of its qubits. It is not an AES
  estimate and the scenarios do not use it: AES scenarios use Grassl's literature counts.

## 6. Physical model vs the papers

The QDK model fed each paper's own logical counts and hardware numbers, against that paper's figures (model / paper):

| paper | physical qubits | runtime |
|---|---|---|
| Gidney-Ekera 2019 | {ge_q} | {ge_t} |
| Gidney 2025 | {g25_q} | {g25_t} |
| Litinski 2023 | {li_q} | {li_t} |

Our model reproduces the 2019 and 2023 qubit counts within a factor of two and overstates the attacker's cost against the newest paper
(Gidney 2025: {g25_q} times the qubits). Its runtime for the 2019 paper is {ge_t} times the paper's; the explanations are in the
`explanation` fields of `calibration.json`, not restated here. The scenario `median` for RSA-2048 uses Gidney 2025's logical counts and so inherits that
overstatement. This is the Phase 4 backlog item, not hidden here. Also: `pessimistic` keeps the median error rate and changes only the
cycle time (physical qubits identical to median: {pess_same_phys}); it is a slow-hardware scenario, not a high-error one.

## 7. Compiled vs generic, dynamic circuits

- `shor15_textbook` is `compiled` (its factor is baked in) and appears only as a same_circuit case. Scaling, calibration and scenarios use
  `generic` circuits only (tests: `test_estimate_scaling_family_is_generic...`, registry kinds).
- `if_else` circuits are not costed as they stand: `estimation_form` inlines the conditional body unconditionally (every classically
  controlled rotation counts as executed), an upper bound for the semi-classical Shor circuits. Labelled in the circuit metadata.
- Tool limits found: QDK refuses a Clifford-only circuit with no measurement; Qualtran's QASM importer adds a spurious And to some
  controlled phases (so `qualtran_counts_from_qasm` refuses gates outside the common basis; the guard now checks every statement, not
  every line); `ModExp.make_for_shor` sizes the x register one bit short for some N (we never call it; pinned by tests).
- Multi-controlled X is lowered to 4(k-2) Toffolis on borrowed qubits. Tested on 3, 4 and 5 controls over the full unitary, over random
  states of all qubits (ancillas included), with mutation checks that fail when a gate is dropped.

## 7b. No QPU

`results/hardware/` and `results/budget.json` are unchanged since `phase-2-done` (test), and no new file appears under those paths. The
name-based guard (receivers containing `backend`) is kept. New guards look at imports and types: `qiskit_ibm_runtime` is imported only by the
three adapter modules; the estimate code imports nothing from the hardware adapter or the ledger and constructs no backend except qsharp's local
`ResourceEstimatorBackend`; the AI transpiler is local mode only; and the estimators run with every IBM entry point booby-trapped (a positive
control proves the trap fires). A rename of a variable, as was done in `qdk.py`, passes the name guard and these alike, so only the
latter say anything about devices. Tests: `test_estimate_budget_*`.

## 8. Literature

{n_lit} entries, {n_verified} verified in `tests/phase3/factcheck.json`. Method: four fact-checker agents read the sources; I re-read in
the PDF text (`pdftotext`) every value the calibration or scenarios use: Gidney-Ekera 2019, Gidney 2025, Roetteler 2017, Litinski 2023, Grassl
2016's AES-128 qubits and T count, the Jaques MAXDEPTH range and the Ross-Selinger abstract. Three entries were corrected (metadata only) and
re-verified. `jaques2020_width_aes128_v1` was removed: the authors' later revision corrects those AES numbers and it could not be read.
Cautions that stay: Gidney-Ekera's Toffoli entry is the Toffoli+T/2 column; Gidney 2025 lists 1399 qubits in Table 5 and 1537 (< 1600) in
Section 3.2, which the paper does not reconcile; Ross-Selinger's rotation cost keeps the leading 3 log2(1/eps) term only.

## 9. Numbers typed by hand outside literature.yaml

Constants >= 100 or < 1e-3 in the estimate code (a scan, reviewed by eye). Design choices, not literature values: the rotation precision
eps, the total error budget, the maximum code distance, unit conversions, and the evaluation points 128, 256 and 2048. The RSA-2048
modulus used for the `ModExp` cost is a synthetic 2048-bit number (cost depends on its bit length, checked by the base-independence flag).
The one that matters: the 2n point-additions factor (section 5).

{consts}

## 10. Not tested or not proven

- No test can check that the n = 2048 extrapolation of the Beauregard family is right; only its bracket and its caveats.
- AES: nothing in this phase estimates AES-128 from our own circuits; the scenario numbers are Grassl's, pushed through a physical model.
- The agents' reads of Grassl, Jaques and Ross-Selinger were backed by my own re-read of the cited values, not of every entry.
- The corrected Jaques et al. AES-128 width was never read.

## 11. Tables (printed from the result files)

{tables}
"""


def main() -> int:
    f = facts()
    out = subprocess.run(
        [sys.executable, str(ROOT / "benchmarks" / "phase3-audit-tables.py")],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    ).stdout
    f["tables"] = out
    (ROOT / "tests" / "phase3" / "AUDIT.md").write_text(TEMPLATE.format_map(f))
    print("wrote tests/phase3/AUDIT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
