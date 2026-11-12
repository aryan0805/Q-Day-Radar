# Phase 5 audit (front end)

Reviewer, build `0586995`. Written by `benchmarks/phase5-build-audit.py`: the prose is here, every
figure below is computed from files, benchmark output or live Chromium runs when the script runs.
Labels: **measured** (a number read from a run), **extrapolated** (a trend carried forward),
**literature** (a published figure), **design choice** (a number someone picked), **fictional**
(the demo company). 452 tests in `tests/phase5` (table in section 9).

## 1. Provenance: every figure traces to a data file

Rule: a number a person can read sits in an element with `data-src="<file>:<path>"`, is a chart tick
(`data-axis`) or carries `data-literal` with a reason. Checked three ways: the gate parses
`out/*.html`; `test_provenance_figures.py` walks the live DOM in all three scenarios on all four
screens and compares each figure with the data to the digits shown; mutation tests plant a wrong
figure, an untraced figure, a dead path and a dropped `data-scale`, and each is caught.

Live DOM, per screen and scenario (home is audited again after the hero has loaded):

| screen | optimistic | median | pessimistic |
| --- | --- | --- | --- |
| / | 51 traced, 0 literal, 0 problems | 47 traced, 0 literal, 0 problems | 49 traced, 0 literal, 0 problems |
| /lab/ | 85 traced, 0 literal, 0 problems | 85 traced, 0 literal, 0 problems | 85 traced, 0 literal, 0 problems |
| /scaling/ | 37 traced, 0 literal, 0 problems | 33 traced, 0 literal, 0 problems | 36 traced, 0 literal, 0 problems |
| /inventory/ | 302 traced, 0 literal, 0 problems | 298 traced, 0 literal, 0 problems | 302 traced, 0 literal, 0 problems |

Server-rendered HTML (the hero text is a lazy chunk, so it is not here):

| screen | traced values (data-src) | chart ticks (data-axis) | data-literal |
| --- | --- | --- | --- |
| / | 26 | 0 | 0 |
| /lab/ | 85 | 21 | 0 |
| /scaling/ | 33 | 2 | 0 |
| /inventory/ | 298 | 0 | 0 |

- Literals on the screens: **0** in the server-rendered HTML. The only literals are the
  easter eggs' own computed values (shor and grover rows, the coin's bit and outcome, the "768" in
  the Shift hint): 12 sites in `Eggs.tsx`, each declared with the reason
  "easter egg value, computed in the browser". They are not project results.
- Tooltip labels in use (server-rendered HTML): see below. The live median pages show: computed from data (66), trend extrapolation (50), hardware (45), computed from data, using design-choice exposure weights (42), simulated (14), published standard (10), published estimate (7), model estimate (4).

| label shown in the tooltip | elements (server-rendered HTML) | one of the brief's five? |
| --- | --- | --- |
| computed from data | 59 | no |
| trend extrapolation | 50 | yes |
| hardware | 44 | yes |
| computed from data, using design-choice exposure weights | 42 | no |
| simulated | 14 | yes |
| published standard | 10 | no |
| published estimate | 7 | yes |
| model estimate | 4 | no |

  **Label vocabulary (lead's decision, resolved).** The brief names five labels; the build uses
  more. Outside the five: computed from data, computed from data, using design-choice exposure weights, fictional demo input, model estimate, published standard. Not shown anywhere (server-rendered HTML and the
  Inventory drawer): none; the drawer carries: computed from data, computed from data, using design-choice exposure weights, design choice, fictional demo input, model estimate, published standard, trend extrapolation. The one decision that
  mattered: every figure that depends on the exposure weights (rank, shortfall, the weight itself;
  found by recomputing with perturbed weights, not from a typed list) says it uses design-choice
  weights, and margins and CRQC years, which the weights cannot change, do not. Checked on the
  Inventory page (median): 42 dependent figures with 0 missing the label;
  84 margin and CRQC-year figures with 0 wrongly carrying it; the drawer
  and the visible tooltip are checked too, and a flipped copy (a label removed, a margin relabelled)
  fails. The label is the compound "computed from data, using design-choice exposure weights";
  the test accepts "design choice" with a space or a hyphen.
- The Phase 4 caveats as shown on screen (checked in the live DOM):

| Phase 4 caveat | present on screen |
| --- | --- |
| every CRQC year is labelled a trend extrapolation | yes |
| the trend's own holdout error is shown beside it | yes |
| the model-only family order is shown next to the computed one | yes |
| the ECC-first order's dependence on an upper bound is stated | yes |
| 'pessimistic' differs from median in cycle time (and growth), said in words | yes |
| NIST's deadlines are shown beside the 2035 date | yes |

## 2. Security

- **CSP mode: hash-based `script-src`.** The build writes `.vercel/output/config.json`; its
  `Content-Security-Policy` has 7 `sha256` hashes, one per distinct inline script found in
  `out/**/*.html`; `script-src` allows `'unsafe-inline'` / `'unsafe-eval'`: **no**.
  The tests recompute every hash from the HTML and require the header's set to be exactly that set,
  and a planted inline script is caught. `style-src` allows `'unsafe-inline'`: **yes**
  (the spec's choice; inline styles are used by the components). Headers: Content-Security-Policy, Cross-Origin-Opener-Policy, Permissions-Policy, Referrer-Policy, Strict-Transport-Security, X-Content-Type-Options
  (10 CSP directives, no wildcards, no remote origin).
- Secrets: the build scans `out/` and the data for the values in the local `.env` and for secret
  patterns, and the tests plant a canary in a temp copy (script, binary font, bare pattern) and
  require it to be found. A scan that scanned nothing now fails (found by these tests). `.env` was
  never committed on any branch; gitleaks runs as a pre-commit hook and in an Action.
- `security.txt` Contact scheme: `mailto:`. It is the human's own address, published on
  purpose (a decision by the human); RFC 9116 needs a reachable contact.
- Not measured here: the live checks on the deployed site (headers, Observatory, SSL Labs) are the
  lead's `[live]` gate checks. Preview protection is checked by the gate with the bypass secret.

## 3. Performance (lab data, local server)

Lighthouse is **lab data on a local static server**, mobile defaults, median of 3 per screen, the
gate's own invocation. It is not field data, not a real network, not a real phone.

| build | screen | performance | accessibility | LCP | CLS | TBT |
| --- | --- | --- | --- | --- | --- | --- |
| pre-8c-dc77fde (dc77fde) | / | 1.00 | 1.00 | 901 ms | 0.000 | 11 ms |
| pre-8c-dc77fde (dc77fde) | /lab/ | 1.00 | 1.00 | 902 ms | 0.036 | 1 ms |
| pre-8c-dc77fde (dc77fde) | /scaling/ | 1.00 | 1.00 | 902 ms | 0.000 | 0 ms |
| pre-8c-dc77fde (dc77fde) | /inventory/ | 1.00 | 1.00 | 1051 ms | 0.002 | 0 ms |
| final-head (76feff1) | / | 1.00 | 1.00 | 901 ms | 0.000 | 0 ms |
| final-head (76feff1) | /lab/ | 1.00 | 1.00 | 1051 ms | 0.003 | 1 ms |
| final-head (76feff1) | /scaling/ | 1.00 | 1.00 | 901 ms | 0.001 | 0 ms |
| final-head (76feff1) | /inventory/ | 1.00 | 1.00 | 1201 ms | 0.005 | 0 ms |

Home-page JavaScript, both ways, gzip -9 (the budget is 200,000 B fetched before the first interaction):

| build | motion | static count (scripts index.html names) | fetched before any interaction | GSAP before | after one scroll | GSAP chunk | within 200,000 B |
| --- | --- | --- | --- | --- | --- | --- | --- |
| before-dc77fde (dc77fde) | normal motion | 193,188 B | 249,789 B | yes | 249,789 B | 27,327 B | NO |
| before-dc77fde (dc77fde) | reduced motion | 193,188 B | 205,020 B | no | 205,020 B | 0 B | NO |
| final-head (0586995) | normal motion | 194,755 B | 189,958 B | no | 249,387 B | 27,327 B | yes |
| final-head (0586995) | reduced motion | 194,755 B | 196,100 B | no | 204,618 B | 0 B | yes |

- The gate's static count only names the scripts `index.html` loads. A visitor also fetches chunks
  after hydration. The before-fix build fetched GSAP at load and went over the budget in both
  motion modes; the current build fetches it only on an interaction and never under reduced motion.
- Margins on the current build: **10,042 B** in normal motion, **3,900 B**
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
- **Deviation from the spec: no Motion library** (library in dependencies: no; GSAP: yes;
  tweak library: none). Spec section 6 asks for Motion for UI motion; the build uses CSS
  transitions and keyframes and GSAP only for the hero. UI motion is therefore CSS-only.
- Long tasks: Chromium with a CPU throttle setting of 4, a `PerformanceObserver` for `longtask`, from
  the hero's first interaction to the end of its Replay: none. **The setting is not the slowdown:**
  the same JavaScript workload took 3.0 to 3.6 times as long throttled
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
- **Flesch-Kincaid is a rough proxy** (textstat's syllable heuristic). The gate requires grade <= 9.0
  and <= 20.0 words per sentence on the plain layer of each screen: **pass**
  (/ grade 6.0, 10.6 w/s, 234 words, 2 tech; /lab/ grade 4.2, 6.5 w/s, 360 words, 1 tech; /scaling/ grade 4.2, 11.2 w/s, 257 words, 2 tech; /inventory/ grade 5.4, 10.9 w/s, 109 words, 1 tech). It measures sentence and word length, not whether a sentence is true or clear.
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

| circuit | raw success | raw 95% Wilson | chance | headline verdict | best exploratory |
| --- | --- | --- | --- | --- | --- |
| grover_present_k2 | 0.5051 | [0.4943, 0.5159] | 0.2500 | above random guessing | dd 0.4891 |
| grover_present_k3 | 0.1469 | [0.1394, 0.1547] | 0.1250 | above random guessing | dd_twirl 0.1517 |
| grover_present_k4 | 0.0537 | [0.0490, 0.0588] | 0.0625 | no better than random guessing | dd 0.0768 |
| grover_present_k5 | 0.0277 | [0.0244, 0.0315] | 0.0312 | no better than random guessing | dd 0.0354 |
| shor15_beauregard | 0.1750 | [0.1637, 0.1870] | 0.1719 | no better than random guessing | none (raw only) |
| shor15_textbook | 0.3575 | [0.3472, 0.3680] | 0.1719 | above random guessing | dd_twirl 0.3693 |

3 of 6 circuits that ran on hardware are above random guessing; `lab.json` ships
`{"above": 3, "no_better": 3, "ran": 6}`. The verdict uses the interval only and has no size threshold, so a result can be
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
- Q-Day mode follows `--threat` (tokens: **yes**), so a tweak to the token carries over.

## 9. The tests

| test file | tests |
| --- | --- |
| test_bundle_size.py | 16 |
| test_copy_no_hackathon_wording.py | 10 |
| test_easteregg.py | 20 |
| test_glossary_terms.py | 21 |
| test_helpers_selftest.py | 20 |
| test_justify_prose.py | 35 |
| test_keyboard_access.py | 22 |
| test_keyboard_defects.py | 1 |
| test_longtask.py | 6 |
| test_motionscale.py | 22 |
| test_provenance_design_choice.py | 14 |
| test_provenance_figures.py | 46 |
| test_provenance_hero_data.py | 15 |
| test_provenance_lab_verdict.py | 22 |
| test_readability_gate.py | 11 |
| test_reducedmotion.py | 19 |
| test_scenario_navigation.py | 4 |
| test_scenario_order_notes.py | 11 |
| test_scenario_plain_sentences.py | 21 |
| test_scenario_switch.py | 15 |
| test_security_headers_csp.py | 18 |
| test_security_source_hygiene.py | 19 |
| test_security_static_output.py | 25 |
| test_smoke_routes.py | 23 |
| test_tweak_panel_browser.py | 8 |
| test_tweak_panel_static.py | 8 |

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
