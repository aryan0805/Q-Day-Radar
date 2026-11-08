# Phase 2 honesty audit

Reviewer, 2026-11-08. Batch `batch-20261108T044751Z` on `ibm_kingston`, plan sha256 `329f8b8a…`.
Every number below was recomputed by the reviewer from `results/hardware/<batch>/jobs/*.json`
(raw counts) and `plan.json`, with `tests/phase2/reference.py`, which shares no code with
`quantum/run/stats.py`. Shots and seeds are stated; each success value sits next to its chance
baseline. Items marked **not checked** were reported by another session or need the human.

Conventions: 4096 shots per job; transpile seed 1234, optimization level 3; prediction seed 1234;
Wilson 95%; `normalized = (s − chance) / (theory − chance)`; "pooled" = both repeats added.
Full table: `benchmarks/phase2-hardware-vs-prediction.{md,json}` (regenerate with
`uv run python benchmarks/phase2_hardware_report.py`).

## Verdicts

| question | answer | evidence |
|---|---|---|
| Were the predictions on file before the jobs ran? | **Yes** | `plan.json` is byte-identical to the approved plan (`approval.json` hash). Approval 06:14:54 UTC, job 0 created 06:14:59. Resume approval 09:20:10, its 29 jobs created 09:20:14–09:20:32. Both approvals `approved_by: human`, same plan hash. `test_real_batch.py::test_approval_predictions_were_on_file_before_every_job_was_created` |
| Was every job analysed? | **Yes**, 33 of 33 | 33 raw files (all DONE, none `usage_unknown`), 33 analysis files, one per planned job, `isa_sha256` equal in plan, raw and analysis |
| Raw and mitigated kept apart? | **Yes** | Top-level numbers equal the raw recomputation for all 31 experiment jobs; M3 results sit in their own `m3` block; calibration jobs have none |
| Anything tuned after seeing the data? | **One thing, labelled** | The mitigation rule and the drift flag were written after the data came in (section F3). Circuits, configs, shots, seeds, predictions and the job list were not changed. Nothing was re-run, dropped or replaced |
| Ledger | **Consistent** | 33 unique job ids, 115.0 s, each entry equal to that job's `job.usage()`; under the 540 s cap. The 28-day figure on IBM's Instances page: **not checked** (the human compares) |
| Estimates | **Conservative** | Plan 167.7 s (cap 300 s); actual 115.0 s (69%). Every job at 61–82% of its estimate; none over |

## What was run

33 jobs: 11 raw, 10 dd (XY4), 10 dd_twirl (XY4 + gate and measurement twirling, 32 × 128), 2 M3
calibration. Pilot 0 was `shor15_beauregard` raw (the human's choice), then `shor15_textbook`
raw / dd / dd_twirl, then `m3_cal_zeros`; `m3_cal_ones` last. `shor21_beauregard` was excluded by
the human (its noisy simulation was at chance anyway: 0.077 against a chance of 0.078, 8192 shots,
seed 1234). No control job.

Two approvals. Jobs 0–3 ran under the first (one at a time; 86, 7, 1.5 and 1 minutes in the
queue). Submitting job 4 failed with IBM error 1217, "Session has been closed", a 400 on create
with no job id. The submit stopped as designed (`stopped.json`, `submit_failed`, code 6) with four
jobs done and ledgered. The human re-approved the same plan hash for `--resume`, which sent the 29
never-submitted jobs inside one new Batch in 18 seconds; they finished by 09:29:22. The gate
checks the resume record. I did not establish which Batch limit applied (idle time or maximum
time): the first Batch had been open for about 95 minutes when job 4 was submitted.

## Results (pooled, with the pre-registered prediction)

| circuit | label | chance | theory | prediction | hardware raw | normalized | reading |
|---|---|---|---|---|---|---|---|
| `shor15_beauregard` (1 job) | generic | 0.1719 | 0.500 | 0.1755 (at chance) | 0.1750 [0.164, 0.187] | +0.010 | at chance, as predicted |
| `shor15_textbook` | **compiled** | 0.1719 | 0.500 | 0.4287 | 0.3575 [0.347, 0.368] | +0.57 | clear signal |
| `grover_present_k2` | generic | 0.2500 | 1.000 | 0.6511 | 0.5051 [0.494, 0.516] | +0.34 | clear signal |
| `grover_present_k3` | generic | 0.1250 | 0.945 | 0.3413 | 0.1469 [0.139, 0.155] | +0.027 | marginal: lower bound just above chance |
| `grover_present_k4` | generic | 0.0625 | 0.961 | 0.1416 | 0.0537 [0.049, 0.059] | −0.010 | at the chance floor (3.3 sd below it) |
| `grover_present_k5` | generic | 0.0312 | 0.999 | 0.0476 | 0.0277 [0.024, 0.032] | −0.004 | at the chance floor |

The intervals are pooled over two repeats and understate the uncertainty for the raw rows (F2).

## Findings, ranked

### F1. The noisy-simulation predictions were too optimistic for every circuit that has depth · verified
Every circuit came in below its prediction: observed − predicted is −0.07 (textbook), −0.15 (k2),
−0.19 (k3), −0.09 (k4), −0.02 (k5), and +0.00 for Beauregard, which was predicted at chance. The
pre-registration worked as intended: predictions were on file, they were wrong in a known
direction, and the result is reported as it came. The model (Aer with the device's gate and
readout errors, no crosstalk, no drift, dd and twirling not modelled) overestimates what Kingston
does at these depths. Consequences for later phases: do not use this noisy simulation to choose
which circuits to run on hardware beyond "which are not already at chance", and do not quote a
simulator success as a hardware expectation.

### F2. Raw repeats drift beyond shot noise, so pooled intervals understate the uncertainty · verified
Two raw pairs have non-overlapping Wilson intervals: `grover_present_k2` raw 0.4651 and 0.5452
(a difference of 7.2 standard errors) and `shor15_textbook` raw 0.3765 and 0.3386 (3.6). The other
13 pairs agree within noise (largest |z| 1.4). The k2 raw pair was created 10 s apart in the same
Batch, so this is not slow calibration drift between sessions; I do not know the cause (a different
physical execution time, a calibration refresh, or a bad run), and **two repeats are too few to
estimate the drift itself**. Statements about k2 and textbook raw must carry the repeat spread
(0.080 and 0.038), not the pooled interval. `drift_beyond_shot_noise` in the summary equals
"some pair of repeat Wilson intervals does not overlap", recomputed from raw counts; it flags
exactly these two rows. It is conservative: a pair with |z| between 2 and 2.8 can overlap and
not be flagged.

### F3. Mitigation: three of ten comparisons resolve by the rule, all at the chance floor; exploratory · verified
Rule: a gain (dd or dd_twirl over raw) is resolved only if it exceeds both pooled Wilson
half-widths and the larger repeat spread of the two configs. Recomputed from raw counts, 10
comparisons:

| comparison | difference | half-width | repeat spread | resolved |
|---|---|---|---|---|
| `grover_present_k4`: dd − raw | +0.0231 | 0.0058 | 0.0039 | yes |
| `grover_present_k4`: dd_twirl − raw | +0.0133 | 0.0054 | 0.0039 | yes |
| `grover_present_k5`: dd − raw | +0.0077 | 0.0040 | 0.0010 | yes |
| `grover_present_k5`: dd_twirl − raw | +0.0012 | 0.0036 | 0.0007 | no |
| textbook dd / dd_twirl | +0.0107 / +0.0117 | 0.0104 | 0.0378 | no / no |
| k2 dd / dd_twirl | −0.0160 / −0.0228 | 0.0108 | 0.0801 | no / no |
| k3 dd / dd_twirl | −0.0061 / +0.0049 | 0.0077 | 0.0051 | no / no |

For the circuits that carry a real signal (textbook, k2, k3) no gain is resolved. The three
resolved rows are for k4 and k5, whose raw result is at or below chance; with dd, k4 moves from
0.0537 to 0.0768 (Wilson lower bound 0.071 against a chance of 0.0625). That is a normalized
change of about +0.026 of the way to the noiseless value: statistically resolved, not
practically meaningful, and not evidence that dd makes Grover work. These are **exploratory**: the rule
was set after the data came in, there are 10 comparisons, 2 repeats per config, and no
multiple-comparison correction. The summary statement says so, and a test checks it.

Process note: lead's first message said "today no gain qualifies". That was stated before anyone
had computed the rule's result; builder found it was wrong by applying the rule literally, and lead
corrected it. The rule was not changed to fit the outcome.

### F4. M3 readout mitigation changes little, and pilot 0 cannot have it · verified
`m3_cal_zeros` / `m3_cal_ones` measure exactly the 14 physical qubits the static experiments
measure. Their mean error is P(1|0) = 0.8% and P(0|1) = 1.5% per qubit (reviewer, from the raw
calibration counts). The analysis uses the `mthree` package; the reviewer's independent
tensor-product matrix inverse agrees with its success values to within 0.01 for all 30 jobs that have an M3 block, and each reviewer-built matrix undoes its own calibration data. A uniform output passed
through those readout errors would give 0.0618 for k4 (chance 0.0625), so readout bias does not
explain the below-chance raw rows. They are most plausibly gate noise that is not uniform
(not investigated). Pilot 0 measures physical qubits [53, 55, 59, 75], of which only 53 is
calibrated, so its analysis has `m3: null` with reason "measured qubits not calibrated" and its raw and "mitigated" values
are the same thing. A partial correction is never applied (tested).

### F5. The live-calibration predictions cannot be reproduced exactly offline · verified, known limitation
The plan simulated the saved ISA with the live Kingston calibration. The reviewer re-simulated the
same saved circuits on the FakeKingston snapshot (same seed, 4096 shots):

| circuit | plan (live Kingston) | FakeKingston | difference (sd) |
|---|---|---|---|
| `shor15_textbook` | 0.4287 | 0.4146 | −0.014 (−1.8) |
| `grover_present_k2` | 0.6511 | 0.6824 | +0.031 (+4.2) |
| `grover_present_k3` | 0.3413 | 0.3237 | −0.018 (−2.4) |
| `grover_present_k4` | 0.1416 | 0.1631 | +0.022 (+3.9) |
| `grover_present_k5` | 0.0476 | 0.0493 | +0.002 (+0.5) |

That is a calibration difference, not a plan error, and the pre-registration rule asks for the live
device model, which is what the plan used. The differences (up to 0.031) are far smaller than
the observed-minus-predicted gaps in F1 (up to 0.19), so calibration does not explain F1. The
pilot-0 dynamic circuit was not re-simulated.

### F6. Pilot 0 is a null check, not a result · verified
`shor15_beauregard` (generic, 2n+3 qubits, dynamic circuit, raw only because dynamic circuits do
not allow dynamical decoupling) was predicted at chance: prediction 0.1755, Wilson lower bound
0.164 ≤ chance 0.1719. Observed 0.1750 [0.164, 0.187], one job, 4096 shots. It confirms that the
dynamic circuit runs on Kingston (feed-forward, mid-circuit measurement and reset) and that the
cost estimate for it held (5.0 s used against 7.3 s estimated). It shows no Shor signal and must
not be described as a demonstration of factoring. Hellinger fidelity to the ideal distribution is
0.026.

### F7. What the hardware results can and cannot support · verified
- `shor15_textbook` is `compiled` (hand-built for a = 7, skips blocks because the order divides 4).
  Its 0.36 hardware success shows the machine can run a 183-two-qubit-gate order-finding circuit
  above chance; it is not evidence about generic Shor.
- Grover k = 2 is a clear signal, k = 3 is marginal, k = 4 and 5 are at the chance floor, on the
  toy SPN. This is a measurement of Kingston's noise, not of Grover's cost for AES (Phase 1 F5
  still applies).
- No hardware result exists for N = 21.

### F8. Items I did not verify
- IBM's recorded job options (raw none, dd XY4, dd_twirl XY4 plus twirling 32 × 128) were reported
  by lead from IBM's job metadata; the raw job files in the repo do not store options, so I could
  not check them.
- Jobs 1, 2 and 3 have equal `content_sha256` and equal loaded circuits (checked: `test_repeats_and_configs_of_one_circuit_have_equal_content`). Their saved
  `.qpy` bytes differ or coincide by QPY serialization; the identity that counts is the circuit.
- The 28-day figure on IBM's Instances page against the ledger's 115.0 s.
- Whether the closed Batch (1217) was a time limit or an idle limit.

## Tests (reviewer)

`tests/phase2`: 415 tests, 0 skips, 0 xfail. Full non-hardware suite green, `ruff check .` clean.
Gate selections: `approval` and `immutable` under `tests/phase2` and `budget` across all tests pass.
- Safety net: no test can reach the network, a token, a real service, or change `results/budget.json`
  or `results/hardware` (an autouse fixture compares them byte for byte; do not run the suite
  while a real submit is running).
- Submit: approval guards, immutability, budget (including 4317, overrun, usage unknown),
  reconcile, and `--resume` (42 tests, 8 of 8 deliberate bugs caught).
- Plan: invariants, `first_pilot` (including refusing a control job), refusals, estimates.
- Analysis: independent statistics, the M3 truth table with asymmetric errors, the null rule,
  prediction fields, the per-repeat summary (16 tests) and the drift and mitigation rules.
- Gate: superseded-batch rule and resume record.
- `test_real_batch.py` (16 tests) recomputes the real batch from raw counts and fails, not skips,
  if the data are missing.

## Carried forward

- Phase 1: F5 (Grover costs do not carry over to AES) and F10 (success is not factoring) remain
  with lead (docs).
- Phase 3 and the deck: quote the baseline, the shots and the repeat spread with every hardware
  number; label `shor15_textbook` as compiled; do not present `shor15_beauregard` hardware as
  signal; do not quote a simulator success as a hardware expectation.
- If hardware is used again: more than two repeats, interleaved so a drifting device shows up
  in the order, and the dynamic circuit's measured qubits included in the calibration.
