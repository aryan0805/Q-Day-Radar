# ruff: noqa: E501  (long lines are prose in the AUDIT template)
"""Renders tests/phase5/AUDIT.md: prose written here, every figure computed from files or live pages.

Nothing numeric is typed in the prose below: counts come from the built site (web/out), the data
files, the benchmark JSONs, pytest's collection and live Chromium runs made by this script.

    PYTHONPATH=. uv run python benchmarks/phase5-build-audit.py

Run it AFTER the benchmarks (benchmarks/phase5-bundle.py, phase5-lighthouse.py) and on a fresh
`cd web && npm run build`; it reads their output. The live step opens the built site in Chromium.
"""

from __future__ import annotations

import collections
import functools
import importlib.util
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
OUT = WEB / "out"
FIVE = ["hardware", "simulated", "trend extrapolation", "published estimate", "design choice"]


def table(header: list[str], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(header) + " |\n| " + " | ".join("---" for _ in header) + " |\n"
    return head + "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in rows)


def b(n: float) -> str:
    return f"{int(n):,} B"


def jload(p: Path):  # noqa: ANN201
    return json.loads(p.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------ static facts


def static_facts() -> dict:
    f: dict = {}
    build = jload(OUT / "build.json")["commit"]
    f["build_commit"] = build[:7]

    # provenance markup in the built HTML (server-rendered part: the hero text is a lazy chunk)
    per_page = []
    labels: collections.Counter[str] = collections.Counter()
    for rel in ("index.html", "lab/index.html", "scaling/index.html", "inventory/index.html"):
        t = (OUT / rel).read_text(encoding="utf-8")
        per_page.append(
            [
                "/" + rel.removesuffix("index.html"),
                len(re.findall(r'data-src="', t)),
                len(re.findall(r"data-axis", t)),
                len(re.findall(r'data-literal="', t)),
            ]
        )
        labels.update(re.findall(r'data-label="([^"]*)"', t))
    f["static_pages"] = table(
        ["screen", "traced values (data-src)", "chart ticks (data-axis)", "data-literal"], per_page
    )
    f["static_traced"] = sum(r[1] for r in per_page)
    f["static_literals"] = sum(r[3] for r in per_page)
    f["labels_table"] = table(
        [
            "label shown in the tooltip",
            "elements (server-rendered HTML)",
            "one of the brief's five?",
        ],
        [[k, v, "yes" if k in FIVE else "no"] for k, v in labels.most_common()],
    )
    f["static_label_set"] = set(labels)
    f["labels_outside_five"] = ", ".join(sorted(k for k in labels if k not in FIVE)) or "none"
    f["five_unused"] = ", ".join(k for k in FIVE if k not in labels) or "none"

    # literals that exist only in code that runs in the browser (the eggs): each has a reason
    egg = (WEB / "src" / "components" / "eggs" / "Eggs.tsx").read_text(encoding="utf-8")
    f["egg_literal_sites"] = len(re.findall(r"data-literal=", egg))
    f["egg_literal_reason"] = re.search(r'const LIT = "([^"]+)"', egg).group(1)

    # CSP mode
    cfg = jload(WEB / ".vercel" / "output" / "config.json")
    headers = cfg["routes"][0]["headers"]
    csp = {
        d.split()[0]: d.split()[1:]
        for d in headers["Content-Security-Policy"].split(";")
        if d.strip()
    }
    scr = csp["script-src"]
    f["csp_hashes"] = sum(1 for s in scr if s.startswith("'sha256-"))
    f["csp_script_unsafe"] = "yes" if "'unsafe-inline'" in scr or "'unsafe-eval'" in scr else "no"
    f["csp_style_unsafe_inline"] = "yes" if "'unsafe-inline'" in csp.get("style-src", []) else "no"
    f["header_names"] = ", ".join(sorted(headers))
    f["csp_directives"] = len(csp)

    # dependencies (the Motion-library deviation)
    pkg = jload(WEB / "package.json")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    f["has_motion_lib"] = "yes" if any(k in deps for k in ("motion", "framer-motion")) else "no"
    f["has_gsap"] = "yes" if "gsap" in deps else "no"
    f["tweak_libs"] = ", ".join(k for k in ("leva", "tweakpane") if k in deps) or "none"

    # security.txt contact scheme (the human chose to publish their own address)
    sec = (OUT / ".well-known" / "security.txt").read_text()
    f["contact_scheme"] = re.search(r"Contact:\s*(\w+):", sec).group(1)

    # Konami palette follows the tokens
    css = (WEB / "src" / "styles" / "globals.css").read_text()
    f["konami_follows_tokens"] = (
        "yes" if re.search(r"data-qday=\"on\"\]\s*\{[^}]*--q:\s*var\(--threat\)", css) else "no"
    )

    # the Lab verdict rule, recomputed from the Phase 2 analysis file
    summ = jload(ROOT / "results" / "analysis" / "phase2" / "summary-batch-20261108T044751Z.json")
    entries = summ["entries"]
    lab = jload(WEB / "public" / "data" / "lab.json")
    rows = []
    for c in lab["circuits"]:
        raw = entries.get(f"{c['name']}/raw")
        if not raw:
            continue
        lo, hi = raw["wilson_95"]
        above = lo > raw["chance_baseline"]
        others = [
            (entries[k]["success_probability"], k.split("/")[1])
            for k in entries
            if k.startswith(c["name"] + "/") and not k.endswith("/raw")
        ]
        best_other = max(others) if others else None
        rows.append(
            [
                c["name"],
                f"{raw['success_probability']:.4f}",
                f"[{lo:.4f}, {hi:.4f}]",
                f"{raw['chance_baseline']:.4f}",
                "above random guessing" if above else "no better than random guessing",
                f"{best_other[1]} {best_other[0]:.4f}" if best_other else "none (raw only)",
            ]
        )
    f["lab_table"] = table(
        [
            "circuit",
            "raw success",
            "raw 95% Wilson",
            "chance",
            "headline verdict",
            "best exploratory",
        ],
        rows,
    )
    f["lab_above"] = sum(1 for r in rows if r[4].startswith("above"))
    f["lab_ran"] = len(rows)
    f["lab_shipped"] = json.dumps(lab["hardware_summary"], sort_keys=True)

    # benchmarks
    bd = jload(ROOT / "benchmarks" / "phase5-bundle.json")
    brow = []
    for label, d in bd["builds"].items():
        for mode in ("normal_motion", "reduced_motion"):
            m = d[mode]
            brow.append(
                [
                    f"{label} ({d['commit'][:7]})",
                    mode.replace("_", " "),
                    b(d["static_index_html_gz_bytes"]),
                    b(m["before_interaction_gz_bytes"]),
                    "yes" if m["gsap_before_interaction"] else "no",
                    b(m["after_one_scroll_gz_bytes"]),
                    b(m["gsap_chunk_gz_bytes"]),
                    "yes" if m["before_interaction_gz_bytes"] <= bd["budget_gz_bytes"] else "NO",
                ]
            )
    f["bundle_table"] = table(
        ["build", "motion", "static count (scripts index.html names)", "fetched before any interaction",
         "GSAP before", "after one scroll", "GSAP chunk", f"within {bd['budget_gz_bytes']:,} B"],
        brow,
    )  # fmt: skip
    f["budget"] = f"{bd['budget_gz_bytes']:,} B"
    last = list(bd["builds"].values())[-1]
    f["final_margin_reduced"] = b(
        bd["budget_gz_bytes"] - last["reduced_motion"]["before_interaction_gz_bytes"]
    )
    f["final_margin_normal"] = b(
        bd["budget_gz_bytes"] - last["normal_motion"]["before_interaction_gz_bytes"]
    )

    lh = jload(ROOT / "benchmarks" / "phase5-lighthouse.json")
    lrow = []
    for label, d in lh["builds"].items():
        for screen, s in d["screens"].items():
            m = s["median"]
            lrow.append([f"{label} ({d['commit'][:7]})", screen, f"{m['performance']:.2f}",
                         f"{m['accessibility']:.2f}", f"{m['lcp_ms']:.0f} ms", f"{m['cls']:.3f}",
                         f"{m['tbt_ms']:.0f} ms"])  # fmt: skip
    f["lh_table"] = table(
        ["build", "screen", "performance", "accessibility", "LCP", "CLS", "TBT"], lrow
    )

    # readability, with the gate's own scorer
    spec = importlib.util.spec_from_file_location("qday_gate", ROOT / "scripts" / "gate.py")
    gate = importlib.util.module_from_spec(spec)
    sys.modules["qday_gate"] = gate
    spec.loader.exec_module(gate)
    ok, detail = gate.p5_readability()
    f["readability_ok"] = "pass" if ok else "FAIL"
    f["readability_rows"] = "; ".join(
        x.strip() for x in detail.split(";") if "grade" in x and "words" in x
    )
    f["fk_max"] = gate.P5_FK_MAX_GRADE
    f["wps_max"] = gate.P5_MAX_WORDS_PER_SENTENCE

    # what the tests are
    col = subprocess.run(
        ["uv", "run", "pytest", "tests/phase5", "--collect-only", "-o", "addopts=", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )  # fmt: skip
    per = collections.Counter(
        line.split("::")[0].removeprefix("tests/phase5/")
        for line in col.stdout.splitlines()
        if line.startswith("tests/phase5/")
    )
    f["tests_total"] = sum(per.values())
    f["tests_table"] = table(["test file", "tests"], [[k, v] for k, v in sorted(per.items())])
    return f


# -------------------------------------------------------------------------------- live facts


def live_facts(facts_static: set[str]) -> dict:
    from playwright.sync_api import sync_playwright

    from tests.phase5.conftest import _Handler, _Server
    from tests.phase5.helpers import ROUTES, SCENARIOS
    from tests.phase5.pagetools import figure_audit, settle, wake_hero

    f: dict = {}
    server = _Server(("127.0.0.1", 0), functools.partial(_Handler, directory=str(OUT)))
    _Handler.out_dir = OUT
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    live_rows, caveat_text, label_live = [], {}, collections.Counter()
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for route in ROUTES:
            row = [route]
            for sc in SCENARIOS:
                ctx = br.new_context(viewport={"width": 1440, "height": 900})
                page = ctx.new_page()
                page.qday = type("L", (), {"responses": [], "requests": []})()
                page.goto(f"{base}{route}?s={sc}", wait_until="networkidle")
                settle(page, sc)
                if route == "/":
                    wake_hero(page)
                    settle(page, sc)
                audit = figure_audit(page)
                bad = len(audit["mismatches"]) + len(audit["unresolved"]) + len(audit["untraced"])
                row.append(
                    f"{audit['n_traced']} traced, {len(audit['literals'])} literal, {bad} problems"
                )
                if sc == "median":
                    label_live.update(
                        page.eval_on_selector_all(
                            "[data-label]", "e => e.map(x => x.dataset.label)"
                        )
                    )
                caveat_text.setdefault(sc, "")
                caveat_text[sc] += page.locator("body").text_content().lower() + " "
                if sc == "median" and route == "/inventory/":
                    from tests.phase5.test_provenance_design_choice import _FIGURES, label_problems

                    lp = label_problems(page.evaluate(_FIGURES))
                    f["dc_dependent"] = lp["n_dependent"][0]
                    f["dc_independent"] = lp["n_independent"][0]
                    f["dc_missing"] = len(lp["missing"])
                    f["dc_forbidden"] = len(lp["forbidden"])
                    inv = jload(WEB / "public" / "data" / "inventory.json")
                    top = min(inv["assets"], key=lambda a: a["by_scenario"]["median"]["rank"])
                    page.locator(f"tr[data-asset-id='{top['id']}']").get_by_role(
                        "button"
                    ).first.click()
                    page.get_by_role("dialog").wait_for(state="visible", timeout=5000)
                    page.wait_for_timeout(300)
                    drawer = set(
                        page.eval_on_selector_all(
                            "[role=dialog] [data-label]", "e => e.map(x => x.dataset.label)"
                        )
                    )
                    f["drawer_labels"] = ", ".join(sorted(drawer)) or "none"
                    f["labels_outside_five"] = ", ".join(
                        sorted((set(facts_static) | drawer) - set(FIVE))
                    )
                    f["five_unused"] = (
                        ", ".join(k for k in FIVE if k not in set(facts_static) | drawer) or "none"
                    )
                if sc == "median" and route == "/":
                    f["holdout_figures"] = page.locator(
                        "[data-src='scenarios:timeline.fit.holdout.rel_error']"
                    ).count()
                    f["deadline_figures"] = page.locator(
                        "[data-src^='inventory:deadlines']"
                    ).count()
                ctx.close()
            live_rows.append(row)
        # the throttle calibration behind the long-task tests
        work = (
            "() => { const t = performance.now(); let x = 0;"
            " for (let i = 0; i < 4e6; i += 1) x += Math.sqrt(i); return performance.now() - t; }"
        )
        ratios = []
        for _ in range(5):
            res = {}
            for label, rate in (("fast", None), ("slow", 4)):
                ctx = br.new_context()
                page = ctx.new_page()
                if rate:
                    ctx.new_cdp_session(page).send("Emulation.setCPUThrottlingRate", {"rate": rate})
                page.goto(base + "/?s=median", wait_until="networkidle")
                res[label] = min(page.evaluate(work) for _ in range(9))
                ctx.close()
            ratios.append(res["slow"] / res["fast"])
        br.close()
    server.shutdown()
    f["live_table"] = table(["screen", *SCENARIOS], live_rows)
    f["labels_live"] = ", ".join(f"{k} ({v})" for k, v in label_live.most_common())
    f["throttle_min"], f["throttle_max"] = f"{min(ratios):.1f}", f"{max(ratios):.1f}"
    allt = " ".join(caveat_text.values())
    checks = [
        ("every CRQC year is labelled a trend extrapolation", "trend extrapolation" in allt),
        ("the trend's own holdout error is shown beside it", f.get("holdout_figures", 0) > 0),
        ("the model-only family order is shown next to the computed one", "cost model alone" in allt),
        ("the ECC-first order's dependence on an upper bound is stated", "upper bound" in allt),
        ("'pessimistic' differs from median in cycle time (and growth), said in words",
         "chips that run slower" in caveat_text.get("pessimistic", "")),
        ("NIST's deadlines are shown beside the 2035 date", f.get("deadline_figures", 0) >= 3),
    ]  # fmt: skip
    f["caveats_table"] = table(
        ["Phase 4 caveat", "present on screen"], [[c, "yes" if ok else "NO"] for c, ok in checks]
    )
    return f


# ------------------------------------------------------------------------------- the document

TEMPLATE = """# Phase 5 audit (front end)

Reviewer, build `{build_commit}`. Written by `benchmarks/phase5-build-audit.py`: the prose is here, every
figure below is computed from files, benchmark output or live Chromium runs when the script runs.
Labels: **measured** (a number read from a run), **extrapolated** (a trend carried forward),
**literature** (a published figure), **design choice** (a number someone picked), **fictional**
(the demo company). {tests_total} tests in `tests/phase5` (table in section 9).

## 1. Provenance: every figure traces to a data file

Rule: a number a person can read sits in an element with `data-src="<file>:<path>"`, is a chart tick
(`data-axis`) or carries `data-literal` with a reason. Checked three ways: the gate parses
`out/*.html`; `test_provenance_figures.py` walks the live DOM in all three scenarios on all four
screens and compares each figure with the data to the digits shown; mutation tests plant a wrong
figure, an untraced figure, a dead path and a dropped `data-scale`, and each is caught.

Live DOM, per screen and scenario (home is audited again after the hero has loaded):

{live_table}

Server-rendered HTML (the hero text is a lazy chunk, so it is not here):

{static_pages}

- Literals on the screens: **{static_literals}** in the server-rendered HTML. The only literals are the
  easter eggs' own computed values (shor and grover rows, the coin's bit and outcome, the "768" in
  the Shift hint): {egg_literal_sites} sites in `Eggs.tsx`, each declared with the reason
  "{egg_literal_reason}". They are not project results.
- Tooltip labels in use (server-rendered HTML): see below. The live median pages show: {labels_live}.

{labels_table}

  **Label vocabulary (lead's decision, resolved).** The brief names five labels; the build uses
  more. Outside the five: {labels_outside_five}. Not shown anywhere (server-rendered HTML and the
  Inventory drawer): {five_unused}; the drawer carries: {drawer_labels}. The one decision that
  mattered: every figure that depends on the exposure weights (rank, shortfall, the weight itself;
  found by recomputing with perturbed weights, not from a typed list) says it uses design-choice
  weights, and margins and CRQC years, which the weights cannot change, do not. Checked on the
  Inventory page (median): {dc_dependent} dependent figures with {dc_missing} missing the label;
  {dc_independent} margin and CRQC-year figures with {dc_forbidden} wrongly carrying it; the drawer
  and the visible tooltip are checked too, and a flipped copy (a label removed, a margin relabelled)
  fails. The label is the compound "computed from data, using design-choice exposure weights";
  the test accepts "design choice" with a space or a hyphen.
- The Phase 4 caveats as shown on screen (checked in the live DOM):

{caveats_table}

## 2. Security

- **CSP mode: hash-based `script-src`.** The build writes `.vercel/output/config.json`; its
  `Content-Security-Policy` has {csp_hashes} `sha256` hashes, one per distinct inline script found in
  `out/**/*.html`; `script-src` allows `'unsafe-inline'` / `'unsafe-eval'`: **{csp_script_unsafe}**.
  The tests recompute every hash from the HTML and require the header's set to be exactly that set,
  and a planted inline script is caught. `style-src` allows `'unsafe-inline'`: **{csp_style_unsafe_inline}**
  (the spec's choice; inline styles are used by the components). Headers: {header_names}
  ({csp_directives} CSP directives, no wildcards, no remote origin).
- Secrets: the build scans `out/` and the data for the values in the local `.env` and for secret
  patterns, and the tests plant a canary in a temp copy (script, binary font, bare pattern) and
  require it to be found. A scan that scanned nothing now fails (found by these tests). `.env` was
  never committed on any branch; gitleaks runs as a pre-commit hook and in an Action. In a clean
  clone with no `.env` there is no real value to scan for; the test then only checks that no
  `.env` is tracked, and the planted-canary tests prove the scanner works.
- `security.txt` Contact scheme: `{contact_scheme}:`. It is the human's own address, published on
  purpose (a decision by the human); RFC 9116 needs a reachable contact.
- Not measured here: the live checks on the deployed site (headers, Observatory, SSL Labs) are the
  lead's `[live]` gate checks. Preview protection is checked by the gate with the bypass secret.

## 3. Performance (lab data, local server)

Lighthouse is **lab data on a local static server**, mobile defaults, median of 3 per screen, the
gate's own invocation. It is not field data, not a real network, not a real phone.

{lh_table}

Home-page JavaScript, both ways, gzip -9 (the budget is {budget} fetched before the first interaction):

{bundle_table}

- The gate's static count only names the scripts `index.html` loads. A visitor also fetches chunks
  after hydration. The before-fix build fetched GSAP at load and went over the budget in both
  motion modes; the current build fetches it only on an interaction and never under reduced motion.
- Margins on the current build: **{final_margin_normal}** in normal motion, **{final_margin_reduced}**
  under reduced motion (the tighter mode).

## 4. Motion

- Reduced motion: no animation is running on any screen, GSAP is never requested, the hero is a static
  strip of the four end states (nothing inert or faded, no Replay), the background is the SVG lattice
  and no WebGL context is created, the duration tokens are zero, and the eggs do not animate. Each
  "none" has a positive control in normal motion.
- Motion scale: the duration tokens are base x `--motion-scale`; every computed animation and
  transition duration and delay on every screen doubles when the scale doubles; the hero's Replay
  takes twice as long at twice the scale; the slider exists only under `next dev` (the tests run the
  real dev server from a private copy and use `localhost`, because Next 16 blocks dev resources for
  the IP origin).
- **Deviation from the spec: no Motion library** (library in dependencies: {has_motion_lib}; GSAP: {has_gsap};
  tweak library: {tweak_libs}). Spec section 6 asks for Motion for UI motion; the build uses CSS
  transitions and keyframes and GSAP only for the hero. UI motion is therefore CSS-only.
- Long tasks: Chromium with a CPU throttle setting of 4, a `PerformanceObserver` for `longtask`, from
  the hero's first interaction to the end of its Replay: none. **The setting is not the slowdown:**
  the same JavaScript workload took {throttle_min} to {throttle_max} times as long throttled
  (5 trials), so the claim is "no long task at about that slowdown", not "at 4x". The observer is
  proven by a deliberate busy loop scheduled as a page task (work run through the DevTools protocol is
  not attributed as a long task, which the first version of the control missed).

## 5. Accessibility

- **Automated plus keyboard testing only. No screen reader was used.** Lighthouse accessibility is an
  automated subset of WCAG; the keyboard tests drive Tab, Shift+Tab, Enter, Escape and arrow keys in
  Chromium. Nothing here shows how the site reads aloud.
- Checked: Tab reaches every control; every stop shows a focus ring and is actually visible (no stop in
  an invisible layer); no keyboard trap; the skip link; the Inventory drawer is a dialog that holds
  focus, closes on Escape and returns focus to its row; the glossary tooltip opens on focus, hover and
  tap, is tied to its term (`aria-describedby`) and Escape closes it without moving focus.
- Touch: one tap test (glossary) in an emulated touch context. No real device was used. Only Chromium
  was tested: not Firefox, not Safari.

## 6. Text

- **Justified prose goes against WCAG 1.4.8** (a AAA criterion, outside our AA target). It was the
  human's choice (tweak round 1). It is justified from 480 px up and left-aligned below, with
  hyphenation; the contexts left-aligned on purpose stay left; headings, navigation, buttons, labels,
  table cells and code are never justified. Checked on the computed style of every element.
- **Flesch-Kincaid is a rough proxy** (textstat's syllable heuristic). The gate requires grade <= {fk_max}
  and <= {wps_max} words per sentence on the plain layer of each screen: **{readability_ok}**
  ({readability_rows}). It measures sentence and word length, not whether a sentence is true or clear.
  The scorer is the gate's own; a mutation test shows it fails hard prose, one overlong sentence, too
  little prose, a missing technical layer and a missing page.
- The hero's plain text says "simplified demo version" for the compiled circuit; the exact term and
  its explanation are in the technical layer and the glossary (the plain-language tweak round). `hero.json`
  says `compiled`, checked against the circuit registry.

## 7. The Lab verdict rule

The headline verdict of a hardware result is the **raw** configuration's, because the raw
configuration was fixed before the data. "Above random guessing" only if its 95% Wilson lower bound is
above the chance baseline; otherwise "no better than random guessing". The error-suppression
settings (dd, dd_twirl) are shown beside it, labelled exploratory, and cannot change the headline
(a copy where dd beats raw is tested). Recomputed here from `results/analysis/phase2`, not from `lab.json`:

{lab_table}

{lab_above} of {lab_ran} circuits that ran on hardware are above random guessing; `lab.json` ships
`{lab_shipped}`. The verdict uses the interval only and has no size threshold, so a result can be
"above" while closing a small part of the gap to a perfect score; the card prints both.

## 8. The easter eggs (the light set, a human decision)

Each of the seven triggers and reverts with no console error and no network request; nothing egg
related is fetched before the first interaction; the Konami listener swallows no key and traps no
focus; `shor` factors multiply to N with the true period; the coin's outcome is a key of the cited
job's measured counts. Limits stated on screen or here:
- The coin **replays stored counts**; it says so ("Replayed from stored counts, not a live measurement").
- `shor` and `grover` are **classical simulations in the browser**, and say so.
- The Shift arrow is a **fixed illustration** beside the pointer, not a vector computed from the
  rendered lattice; the visible text claims only "Easy in 2D".
- The console CTF is a deliberately tiny key, solvable in a line; it is a toy, not a security claim.
- Q-Day mode follows `--threat` (tokens: **{konami_follows_tokens}**), so a tweak to the token carries over.

## 9. The tests

{tests_table}

## 10. Defects these tests found (all fixed by the builder, each re-verified)

- The canary scanner passed after scanning nothing (a missing or empty directory).
- The tweak panel's sentinel lived in a comment, which the production build strips, so "absent from
  `out/`" would have passed with the panel shipped; the panel's own strings and a runtime attribute are
  checked now.
- The scenario was dropped from the URL when navigating, so the address bar disagreed with the page.
- Closing the Inventory drawer dropped keyboard focus to the page; hidden hero layers took Tab focus.
- A single-family sentence lowercased an acronym; a constant sentence about history was typed by hand.
- Under reduced motion the background still created a WebGL context, the Konami shatter still moved and
  Grover still stepped through its animation.
- The hero's start had a long task right on the 50 ms line, intermittently; it is now split into
  yielded steps.
- `textstat` ships its own top-level `tests` package, which shadowed ours and broke every shared
  import; `tests/__init__.py` fixes it.

## 11. What is not covered

Real devices and touch beyond one tap test; Firefox and Safari; a screen reader; field performance;
the deployed site (the lead's `[live]` checks); any claim about whether the plain-language copy is
correct beyond sentence and word length.
"""


def main() -> int:
    facts = static_facts()
    facts.update(live_facts(facts["static_label_set"]))
    (ROOT / "tests" / "phase5" / "AUDIT.md").write_text(
        TEMPLATE.format_map(facts), encoding="utf-8"
    )
    print("wrote tests/phase5/AUDIT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
