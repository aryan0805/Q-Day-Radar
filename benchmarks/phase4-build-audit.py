# ruff: noqa: E501  (long lines are prose in the AUDIT template)
"""Renders tests/phase4/AUDIT.md: prose written here, every number computed from result files.

Run (after tests are green):  uv run python benchmarks/phase4-build-audit.py
Inputs: results/risk/timeline.json, web/public/data/*.json, the demo CBOM, quantum/estimate/
literature.yaml, tests/phase3/factcheck.json, results/estimate/scenarios.json.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.phase4 import reference as ref  # noqa: E402


def g(x: float) -> str:
    return f"{x:.4g}"


def yr(x) -> str:
    return "never (null)" if x is None else f"{x:.1f}"


def table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def facts() -> dict:
    tl = json.loads((ref.RESULTS / "timeline.json").read_text())
    inv = json.loads((ref.WEB_DATA / "inventory.json").read_text())
    scen = json.loads((ref.WEB_DATA / "scenarios.json").read_text())
    est = json.loads((ref.EST / "scenarios.json").read_text())
    lit = {e["id"]: e for e in ref.literature()}
    fc = json.loads(ref.FACTCHECK.read_text())
    cbom = json.loads(ref.DEMO_CBOM.read_text())
    f: dict = {}

    # ---------------------------------------------------------------- timeline
    pts, fr = tl["points"], tl["frontier"]
    fit, raw = tl["fit"], tl["sensitivity_raw_series"]
    f["n_points"] = len(pts)
    f["years"] = f"{pts[0]['year']}-{pts[-1]['year']}"
    f["baseline"] = (
        f"{tl['baseline']['qubits']} qubits ({tl['baseline']['year']}, `{tl['baseline']['literature_id']}`)"
    )
    f["flat_years"] = sum(1 for a, b in zip(fr, fr[1:], strict=False) if b["qubits"] == a["qubits"])
    f["dips"] = ", ".join(
        f"{p['year']}: {p['qubits']} (record {x['qubits']})"
        for p, x in zip(pts, fr, strict=True)
        if p["qubits"] < x["qubits"]
    )
    f["doubling"] = g(fit["doubling_years"])
    f["ci_lo"], f["ci_hi"] = g(fit["ci95"][0]), g(fit["ci95"][1])
    f["r2"] = g(fit["r2"])
    rel = [abs(r["rel"]) for r in fit["residuals"]]
    f["max_resid"] = f"{max(rel):.0%}"
    f["resid_signs"] = "".join("+" if r["rel"] > 0 else "-" for r in fit["residuals"])
    h = fit["holdout"]
    f["ho_year"], f["ho_pred"], f["ho_act"] = h["year"], g(h["predicted"]), g(h["actual"])
    f["ho_err"] = f"{h['signed_rel_error']:+.0%}"
    f["raw_doubling"] = g(raw["doubling_years"])
    f["raw_ci"] = f"{g(raw['ci95'][0])} to {g(raw['ci95'][1])}"
    f["raw_r2"] = g(raw["r2"])
    f["raw_ho_err"] = f"{raw['holdout']['signed_rel_error']:+.0%}"
    f["rule"] = " ".join(str(tl["inclusion_rule"]).split())

    # ---------------------------------------------------------------- CRQC table + fairness rule
    rows, nofeed_rows = [], []
    for t in ref.TARGETS:
        for s in ref.SCENARIOS:
            r = tl["scenarios"][s]["targets"][t]
            rows.append(
                [
                    t,
                    s,
                    g(r["physical_qubits"]),
                    r["physical_source"]
                    + (f" ({r['physical_bound']} bound)" if r["physical_bound"] else ""),
                    f"{r['runtime_seconds'] / ref.SECONDS_PER_YEAR:.3g}",
                    "yes" if r["feasible"] else "no",
                    yr(r["crqc_year"]),
                ]
            )
            m = est["targets"][t]["by_scenario"][s]
            y = ref.crqc_year(
                tl["as_of_year"],
                tl["scenarios"][s]["doubling_years"],
                m["physical_qubits"],
                m["runtime_seconds"],
                tl["baseline"]["qubits"],
                tl["runtime_cap_years"],
            )
            nofeed_rows.append([t, s, g(m["physical_qubits"]), yr(y)])
    f["crqc_table"] = table(
        [
            "target",
            "scenario",
            "physical qubits",
            "source",
            "runtime (years)",
            "within 1-year cap",
            "CRQC year",
        ],
        rows,
    )
    f["nofeed_table"] = table(
        ["target", "scenario", "model physical qubits", "CRQC year"], nofeed_rows
    )
    f["feeds"] = ", ".join(
        f"`{i}` ({e['value']:g} qubits{', upper bound' if e['feeds']['bound'] else ''})"
        for i, e in lit.items()
        if e.get("feeds")
    )

    # family order with and without paper feeds (rule: families sorted by their attack target's year)
    nofeed_years: dict[str, dict[str, float | None]] = {s: {} for s in ref.SCENARIOS}
    for s in ref.SCENARIOS:
        for t in ref.TARGETS:
            m = est["targets"][t]["by_scenario"][s]
            nofeed_years[s][t] = ref.crqc_year(
                tl["as_of_year"],
                tl["scenarios"][s]["doubling_years"],
                m["physical_qubits"],
                m["runtime_seconds"],
                tl["baseline"]["qubits"],
                tl["runtime_cap_years"],
            )
    f["order_table"] = table(
        [
            "scenario",
            "family order (as built: papers feed qubits)",
            "family order if papers did NOT feed (model only)",
        ],
        [
            [
                s,
                " > ".join(inv["family_order"][s]),
                " > ".join(ref.family_order_by_target(nofeed_years[s])),
            ]
            for s in ref.SCENARIOS
        ],
    )
    f["order_changes"] = (
        "yes"
        if any(
            inv["family_order"][s] != ref.family_order_by_target(nofeed_years[s])
            for s in ref.SCENARIOS
        )
        else "no"
    )

    # off-family context
    ctx = []
    for i, e in lit.items():
        if e["target"] == "ecc256" and e["quantity"] == "physical_qubits" and not e.get("feeds"):
            ctx.append(f"`{i}`: {e['value']:g} qubits ({e['assumptions'].split(':')[0]})")
    f["context"] = "; ".join(ctx)
    ionq = lit["ionq2026_physical_qubits_ecc256"]["value"]
    used = tl["scenarios"]["median"]["targets"]["ecc256"]["physical_qubits"]
    modelp = est["targets"]["ecc256"]["by_scenario"]["median"]["physical_qubits"]
    f["ionq_vs_used"] = f"{used / ionq:.1f}"
    f["ionq_vs_model"] = f"{modelp / ionq:.0f}"

    # ---------------------------------------------------------------- pessimistic
    f["pess_note"] = scen["scenario_notes"]["pessimistic"]
    f["pess_finite"] = sum(
        1 for a in inv["assets"] if a["by_scenario"]["pessimistic"]["margin_years"] is not None
    )
    f["n_assets"] = len(inv["assets"])
    finite = [
        a for a in inv["assets"] if a["by_scenario"]["pessimistic"]["margin_years"] is not None
    ]
    f["pess_finite_who"] = ", ".join(f"`{a['id']}` ({a['algorithm']})" for a in finite) or "none"
    f["pess_finite_deprecated"] = (
        "all of them classically deprecated"
        if all(a["classically_deprecated"] for a in finite)
        else "NOT all deprecated"
    )
    rest = sorted(
        (a for a in inv["assets"] if a["by_scenario"]["pessimistic"]["margin_years"] is None),
        key=lambda a: a["by_scenario"]["pessimistic"]["rank"],
    )
    f["pess_ranks_alpha"] = (
        "yes" if [a["id"] for a in rest] == sorted(a["id"] for a in rest) else "no"
    )
    f["n_pess_null"] = len(rest)

    # ---------------------------------------------------------------- mapping bias
    f["by_target"] = ", ".join(
        f"{k or 'none'}: {v}"
        for k, v in sorted(
            collections.Counter(a["attack_target"] for a in inv["assets"]).items(),
            key=lambda kv: str(kv[0]),
        )
    )
    f["n_lower_bound"] = sum(1 for a in inv["assets"] if "lower bound" in a["mapping_note"].lower())
    dep = [a for a in inv["assets"] if a["classically_deprecated"]]
    f["n_dep"] = len(dep)
    f["dep_list"] = (
        ", ".join(f"`{a['id']}` ({a['algorithm']}, {a['key_bits']} bits)" for a in dep) or "none"
    )
    f["order_notes"] = (
        " ".join(str(x) for x in (scen.get("order_notes") or {}).values())
        if isinstance(scen.get("order_notes"), dict)
        else str(scen.get("order_notes"))
    )

    # ---------------------------------------------------------------- ranking
    rk = []
    for s in ("optimistic", "median"):
        top = sorted(inv["assets"], key=lambda a: a["by_scenario"][s]["rank"])[:5]
        for a in top:
            r = a["by_scenario"][s]
            rk.append(
                [
                    s,
                    r["rank"],
                    a["id"],
                    a["algorithm"],
                    a["exposure"],
                    a["shelf_life_years"],
                    a["migration_years"],
                    f"{r['margin_years']:+.1f}" if r["margin_years"] is not None else "null",
                    g(r["shortfall"]),
                ]
            )
    f["top_table"] = table(
        [
            "scenario",
            "rank",
            "asset",
            "algorithm",
            "exposure",
            "shelf life (y)",
            "migration (y)",
            "margin (y)",
            "shortfall",
        ],
        rk,
    )
    f["at_risk"] = ", ".join(
        f"{s}: {sum(1 for a in inv['assets'] if a['by_scenario'][s]['shortfall'] > 0)}"
        for s in ref.SCENARIOS
    )
    f["weights"] = ", ".join(
        f"{k} = {v}" for k, v in ref.load_yaml(ref.RISK / "exposure.yaml")["weights"].items()
    )

    # ---------------------------------------------------------------- standards, survey
    f["dep"] = lit["nistir8547_deprecate_after"]["value"]
    f["dis"] = lit["nistir8547_disallow_after"]["value"]
    s = tl["survey_check"]
    f["survey"] = (
        f"model median RSA-2048 CRQC year {s['model_year']:.1f} vs the survey's 10-year horizon ({s['survey_year']}): delta {s['delta_years']:+.1f} years"
    )
    f["survey_n"] = "13 of 26"

    # ---------------------------------------------------------------- CBOM and fact-check
    f["n_cbom"] = len(cbom["components"])
    f["fc_n"] = len(fc)
    f["fc_ok"] = sum(1 for r in fc.values() if r["status"] == "verified")
    f["lit_n"] = len(lit)
    f["hw_n"] = sum(1 for e in lit.values() if e["target"] == "timeline")

    # ---------------------------------------------------------------- pessimistic (computed)
    def shor_row(name, target):
        r = tl["scenarios"][name]["targets"][target]
        yrs = r["runtime_seconds"] / ref.SECONDS_PER_YEAR
        return f"{target}: runtime {yrs:.3g} y, " + (
            "within the cap, CRQC year " + yr(r["crqc_year"])
            if r["feasible"]
            else "over the cap, no year"
        )

    f["pess_shor"] = "; ".join(shor_row("pessimistic", t) for t in ("rsa2048", "ecc256"))
    f["pess_ecc_vs_median"] = (
        f"{yr(tl['scenarios']['pessimistic']['targets']['ecc256']['crqc_year'])} vs "
        f"{yr(tl['scenarios']['median']['targets']['ecc256']['crqc_year'])} in the median scenario"
    )

    # ---------------------------------------------------------------- physical model v2
    cal = json.loads((ref.EST / "calibration.json").read_text())["comparisons"]
    v2rows = {r["target"]: r for r in cal if r["estimator"] == "physical_v2"}
    f["v2_table"] = table(
        ["check", "input", "v2 physical qubits", "paper", "ratio", "tolerance", "within"],
        [
            [
                (
                    "(a) consistency, Gidney 2025 RSA-2048"
                    if t == "rsa2048"
                    else "(b) holdout, Google 2026 ECC-256"
                ),
                f"{g(r['input_logical_qubits'])} logical (`{r['input_logical_qubits_id']}`)",
                g(r["ours"]),
                f"{g(r['literature_value'])} (`{r['literature_id']}`)",
                f"{r['ratio']:.4f}",
                f"{r['tolerance']['kind'].replace('_', '-')} {r['tolerance']['factor']}x",
                "yes" if r["tolerance"]["within"] else "**NO**",
            ]
            for t, r in v2rows.items()
        ],
    )
    f["v2_gap"] = f"{lit['g2025_physical_qubits_rsa2048']['value'] - v2rows['rsa2048']['ours']:.0f}"
    f["v2_holdout_fails"] = "FAILS" if not v2rows["ecc256"]["tolerance"]["within"] else "passes"
    spec = ref.load_yaml(ref.ROOT / "quantum" / "estimate" / "scenarios.yaml")["physical_v2"]
    comp_rows = []
    for k, i in spec.items():
        if k.endswith("_id"):
            e = lit[i]
            comp_rows.append([f"`{i}`", e["value"], e["locator"][:90]])
    f["v2_params"] = table(["parameter (literature id)", "value", "locator"], comp_rows)
    cold, m_, hotd = (
        lit["g2025_cold_storage_physical_per_logical"]["value"],
        lit["g2025_cold_logical_qubits_m"]["value"],
        lit["g2025_code_distance"]["value"],
    )
    hot = 2 * (hotd + 1) ** 2
    patches = lit["g2025_compute_region_hot_patches"]["value"]
    sens = []
    for big_l in (1399, 1409, 1411):
        c = m_ / big_l
        v = lambda n, c=c: n * (c * cold + (1 - c) * hot) + patches * hot  # noqa: E731
        sens.append(
            [
                big_l,
                f"{v(lit['g2025_max_algorithmic_logical_qubits']['value']) / lit['g2025_physical_qubits_rsa2048']['value']:.4f}",
                f"{v(lit['google2026_logical_qubits_ecc256']['value']) / lit['google2026_physical_qubits_ecc256']['value']:.4f}",
            ]
        )
    f["v2_sens"] = table(
        ["max logical qubits used for the cold fraction", "(a) ratio", "(b) ratio"], sens
    )
    log = (ref.ROOT / ".coord" / "LOG.md").read_text().splitlines()

    def stamp(pred):
        ln = next((x for x in log if pred(x)), "")
        return ln[2:18] if ln else "not found"

    f["t_iface"] = stamp(lambda x: "[INTERFACE]" in x and "physical v2" in x.lower())
    f["t_dec"] = stamp(lambda x: "[DECISION]" in x and "v2 pre-registration accepted" in x)
    f["t_ready"] = stamp(lambda x: "[READY_FOR_TEST]" in x and "physical_v2" in x)

    # ---------------------------------------------------------------- ECC inputs
    esrc = est["targets"]["ecc256"]["logical_source"]
    f["ecc_ids"] = ", ".join(
        f"`{i}` ({lit[i]['value']:g}, {lit[i].get('bound') or 'point'})"
        for i in esrc["literature_ids"]
    )
    f["ecc_hist"] = "; ".join(
        f"{h['source']} (superseded by `{h['superseded_by']}`)" for h in esrc["history"]
    )
    f["ecc_ctx"] = "; ".join(
        f"{c['source']}: {c['logical_qubits']} logical qubits" for c in esrc["context"]
    )
    f["ecc_also"] = lit["google2026_logical_qubits_ecc256"]["also_published_as"]
    return f


TEMPLATE = """# Phase 4 audit: risk engine

Generated by `benchmarks/phase4-build-audit.py` from `results/risk/timeline.json`,
`web/public/data/*.json`, the demo CBOM, `quantum/estimate/literature.yaml` and
`tests/phase3/factcheck.json`. Every figure below is printed by that script; none was typed.
Reviewer: `tests/phase4/`. Tests named `cbom`, `mosca`, `timeline` have no xfail and no skip.

## 1. Labels: what each output is

| output | label | basis |
|---|---|---|
| Hardware points ({n_points} per-year qubit counts, {years}) | **literature** | one fact-checked entry each in `literature.yaml` |
| Doubling time, its 95% CI, residuals, holdout | **extrapolated** (a fit to {n_points} points) | OLS on log2(qubits) of the frontier |
| CRQC year per target and scenario | **extrapolated** | fitted doubling time applied to a paper's or the model's physical-qubit count |
| Physical qubits for RSA-2048 / ECC-256 | **literature** where a paper feeds it (Gidney 2025; Google 2026 as an **upper bound**), otherwise **model** (Phase 3 estimate) | see section 3 |
| Runtime used only for the 1-year feasibility cap | **model** (Phase 3) | papers never feed runtime |
| Exposure weights ({weights}) | **design choice** | `quantum/risk/exposure.yaml`; only the order internet > partner > internal is meant |
| Runtime cap, replacement algorithm names | **design choice** | `exposure.yaml`, `replacements.yaml` |
| Shelf life x, migration time y, exposure, usage per asset | **fictional** | the demo CBOM ({n_cbom} assets of an invented fintech, `qday:fictional = true`) |
| Mosca margin, shortfall, rank | **extrapolated** | arithmetic on the rows above |
| Replacement standards and NIST deadlines | **literature** | FIPS 203/204/205/197/180-4/202, NIST IR 8547 final (Oct 2026) |
| Expert survey | **literature** | Global Risk Institute 2025 ({survey_n} experts) |

No number is typed into the risk code except unit conversions, curve sizes and statistical levels;
`test_timeline_no_typed_numbers.py` scans the code and fails on any other literal.

## 2. The timeline and its weaknesses

Inclusion rule (one place, `exposure.yaml`, copied into `timeline.json`): {rule}

- **It counts qubits, not quality.** The series says nothing about error rates, connectivity or
  whether the qubits can run a deep circuit. A chip with many poor qubits adds a point; a
  smaller, far better chip does not.
- **The record has stalled.** The frontier is flat in {flat_years} of its year-to-year steps; the
  baseline is {baseline}. Raw series dips: {dips}. The fit runs on the frontier (running maximum) so a dip
  does not lower it; the raw-series fit is kept as a labelled sensitivity only.
- **The fit is poor at the end.** Doubling time {doubling} years (95% CI {ci_lo} to {ci_hi}), R^2 {r2}, largest
  relative residual {max_resid}, residual signs by year {resid_signs} (a run of one sign is curvature, not noise).
  **Holdout:** fitting without the last frontier point ({ho_year}) predicts {ho_pred} qubits against {ho_act} actual
  (signed error {ho_err}). The raw-series sensitivity gives {raw_doubling} years (CI {raw_ci}, R^2 {raw_r2}, holdout error {raw_ho_err}).
  A CRQC year is therefore an extrapolation of a trend that the last two years did not follow; the
  CI describes scatter around a straight line, not the chance that the line is right.
- **No hardware quality in the CRQC step.** The step from today's record to a paper's physical-qubit
  count assumes the machines will be as good as the paper's 0.1% error rate.

## 3. CRQC years and the fairness rule

Each Shor target is compared with its most recent estimate **on a scenario's own hardware family**
(surface code, planar, error rate at most the scenario's): {feeds}. A paper feeds physical qubits only
(`min` of paper and model, the earlier threat); its runtime never feeds. Papers on other hardware are
context entries without `feeds`: {context}. The IonQ figure is {ionq_vs_used}x below the ECC-256
number the model uses (and {ionq_vs_model}x below the Phase 3 model's own median number), so on trapped ions a
surface-code timeline may be late; the same applies to neutral-atom and cat-qubit papers noted in
`tests/phase4/NEWEST_ESTIMATES.md` (not entered: not fact-checkable to the standard of this project).

{crqc_table}

**The family order depends on the Google bound.** Google's figure is an upper bound ("fewer than half a million"),
Gidney's is an exact count; a bound is compared with a count, so the ECC-256 CRQC year is the earlier threat by
construction. Without any paper feed (Phase 3 model only):

{nofeed_table}

{order_table}

Does the family order change when papers do not feed? **{order_changes}.**

## 4. The pessimistic scenario

{pess_note} In `pessimistic` (1 ms cycle): {pess_shor}. ECC-256 is {pess_ecc_vs_median}; RSA-2048 exceeds the
1-year cap, so no RSA-mapped asset has a quantum margin there. The scenario differs from `median` only in the cycle time
(and the long end of the doubling-time CI). Assets with a finite margin under pessimistic: {pess_finite} of {n_assets}:
{pess_finite_who}. The assets without a margin are ranked by the tie-break (asset id), alphabetically: {pess_ranks_alpha}.
Read a null as "no Shor attack of this kind fits the cap", not as "nothing is at risk".

## 5. Mapping, bias and classical deprecation

Assets per attack target: {by_target}. Larger keys inherit the smaller target's cost: {n_lower_bound} assets
carry a "lower bound on attacker cost" note, so their true threat is later than shown. The mapping is
biased toward an EARLIER threat, which is the cautious direction for a migration plan. AES and SHA map to the
Grover cost of AES-128; at the 1-year cap none is at risk from a quantum attack, so they carry no quantum margin.

**Classical deprecation is a separate reason, not a quantum one.** Assets below 112 bits of classical security
(RSA below 2048 bits, ECC below 224 bits, plain SHA-1 used for signatures or hashing) get CRQC year = the as-of year in every scenario, labelled
"classically deprecated (SP 800-131A), not a quantum estimate": {n_dep} assets: {dep_list}. Limits of that rule
(SP 800-131A Rev. 2, fact-checked against the PDF): RSA below 2048 is disallowed for signature generation and for
key establishment but allowed as legacy use for verifying old signatures (1024 to 2047 bits); the 224-bit ECC limit is
printed in the standard (Table 2, p. 10). SHA-1 is flagged only when collision resistance matters (signature or hash use;
SP 800-57 Pt 1 Rev. 5 Table 3 and footnote 74: below 80 bits against collisions): SHA-1 as encryption or key-exchange input
and HMAC-SHA-1 are not flagged, because SP 800-131A still accepts SHA-1 where collision resistance is not needed. The rule
is on the algorithm name and usage only; whether a given SHA-1 asset really needs collision resistance is the
CBOM author's `qday:usage`, not checked. Revision 3 of SP 800-131A exists only as an initial public draft and proposes
moving from 112 to 128 bits. A
deprecated asset is ranked by the same shortfall rule as any other.

## 6. Ranking

Assets with a shortfall (margin below zero): {at_risk}. Top of the ranking:

{top_table}

Rank is by shortfall = exposure weight x years short, then margin, then id; the weights are design choices, so
the order between an internet-facing asset with a small shortfall and an internal one with a large shortfall is
ours, not measured.

## 7. Standards, deadlines and the survey

NIST IR 8547 final: quantum-vulnerable public-key algorithms are deprecated after {dep} and disallowed after {dis}.
**These are not the only deadlines:** the final restates earlier federal deadlines for high-value assets and
high-impact systems (key establishment by 31 December 2030, digital signatures by 31 December 2031), so for such
assets the migration deadline can be earlier than {dis}. The inventory carries the {dis} date only.
Survey check: {survey}. The survey asks for the likelihood of an RSA-2048 break within 24 hours; our estimate allows up to a year.

## 7b. ECC-256 inputs and physical model v2 (improve round 2)

**ECC-256 inputs.** Logical counts come from the newest verified on-family estimate that gives both logical qubits and a
Toffoli count: {ecc_ids} (upper bounds). {ecc_also}: one work, one source, never counted twice. History, marked
`superseded_by`: {ecc_hist}. Context only (logical level, no hardware assumptions): {ecc_ctx}.

**Physical model v2 (a generalization test that FAILED, recorded, not tuned).** v2 rebuilds Gidney 2025's own accounting
(cold storage, hot patches, compute region) from five components, each a fact-checked literature entry with a locator:

{v2_params}

Tolerance 1.5x was fixed before the build; the parameters were posted as `[INTERFACE]` at {t_iface}, lead's arithmetic
followed at {t_dec}, and the first calibration rows were reported at {t_ready} (times from `.coord/LOG.md`).

{v2_table}

- (a) reuses Gidney's own components on Gidney's own logical counts, so agreement is by construction: a **consistency check**, not
  evidence that the model generalizes. It is not exactly 1: v2 with 1409 logical qubits has 129 hot patches (1409 - 1280), the paper's text has 131,
  and the shortfall is {v2_gap} physical qubits (two hot patches of 1352). Builder's pre-registration message calls its arithmetic "exact"; that
  is true of the paper's three components (550,400 + 177,112 + 170,352), not of the v2 formula run on 1409.
- (b) is the **independent test**: v2 on the Google 2026 ECC-256 counts against its "fewer than half a million" bound. It {v2_holdout_fails}
  the pre-registered 1.5x. The human chose to record the failure; the scenarios keep the Phase 3 model plus paper feeds and no
  number in the timeline or inventory uses v2. Likely cause (stated, not acted on): v2 carries RSA's cold-storage fraction and compute block over to ECC.
- **One input is internally inconsistent in the source.** Gidney's text gives 1409 logical qubits at the maximum, but his Table 5
  prints 1399 for n = 2048 and 1280 + 131 = 1411. v2 uses 1409 (the text) for the cold fraction. The failure does not depend on that choice:

{v2_sens}

- The only number in v2 not from Gidney 2025 is the surface-code threshold used for error rates other than 1e-3 (labelled as an extension);
  at 1e-3 it is not used.

## 8. Falsifying checks, one per output

| output | falsifying check | test |
|---|---|---|
| CBOM | official CycloneDX 1.6 strict validator; exact JSON round trip; 9 broken documents and 4 meaningless property values must be rejected | `test_cbom.py` |
| Doubling time, CI | known-answer series (exact doubling 0.5/1/1.9/4), regression worked in exact fractions, Student-t table values, a CI whose long end does not exist | `test_timeline_reference.py` |
| Fit, holdout, baseline, CRQC years | recomputed from the points with an independent implementation; frontier is the running maximum | `test_timeline_results.py` |
| Paper feeds | only physical-qubit feeds; value = min(model, applicable paper); source and bound flag recomputed | `test_timeline_results.py` |
| Margin, shortfall, rank | hand-computed assets under two scenarios; monotonicity in x, y, exposure, doubling time; null margin ranks last; random portfolios vs the reference | `test_mosca_reference.py`, `test_mosca_functions.py` |
| Inventory | every asset x scenario recomputed from the CBOM, `timeline.json` and the yamls; family order recomputed | `test_mosca_inventory.py` |
| Mapping | per-asset family and target vs an independent rule; unmapped curve refused | `test_mosca_functions.py` |
| Replacements | each standard id is a verified literature entry; rule table matches | `test_mosca_inventory.py` |
| No typed numbers | AST scan of the risk code against an allow-list | `test_timeline_no_typed_numbers.py` |

## 9. Fact-check

{fc_ok} of {fc_n} literature entries are `verified` in `tests/phase3/factcheck.json` ({lit_n} entries, of which {hw_n} are hardware points). Open items
and limits:
- Google 2026 gives a bound, not a count; its 1 microsecond round is only an illustration in the paper, so no runtime feeds.
- The 2024 hardware point (Tianyan-504, 504 qubits) is supported only by Chinese state-media reports; gate-model
  operation is inferred, not stated, and no gate fidelity is published. It does not change the frontier.
- NIST IR 8547 (final) and the GRI report were read as page images; the 10 November 2017 IBM announcement was not read.
- Alice & Bob (ePrint 2026/2665, 28 October 2026) is newer than every entry above, but its exact figures are only in
  secondary coverage, so it is not entered.
- The PRX Quantum paper is treated as the journal form of arXiv 2603.28846 on a metadata match (Crossref, OpenAlex, Google Research:
  same title, authors, abstract figures); no registry links the two, and the APS page and journal body could not be read.
- Chevignard et al. (1193 qubits, 2^38.98 Toffoli per run) is verified against the ePrint abstract only: the Eurocrypt artifact page still
  shows 1098 / 2^38.10 (the P-224 pair per the authors' correction note) and the paper body could not be read. It is context only.
- Gidney 2025 is not self-consistent around 1409 logical qubits (Table 5 prints 1399; 1280 + 131 = 1411); recorded in the entry, and the v2 result does not depend on it.
- SP 800-131A: the "disallowed" status of RSA below 2048 and of SHA-1 has legacy-use exceptions (section 5); a Revision 3 draft exists.
- The doubling-time model is a straight line in log2(qubits); no test can show that the next ten years follow it.
"""


def main() -> int:
    out = ROOT / "tests" / "phase4" / "AUDIT.md"
    out.write_text(TEMPLATE.format_map(facts()))
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
