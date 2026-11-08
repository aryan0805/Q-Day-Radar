# Phase 1 honesty audit

Reviewer + `quantum-architect` (read-only second read, given the code and the project rules but
not the reviewer's conclusions). Date 2026-11-07. Audited the code as it stood after P003.
Every finding below is marked **verified** (the reviewer re-ran it) or **reported** (the
architect's measurement, not re-run; where the reasoning could be checked by reading the code
this is said).

Questions asked of each circuit: (1) does it read, receive or derive the answer, directly or
through structure; (2) is the `kind` label right; (3) is `theoretical_success` analytic and on
the same rule as the scorer; (4) can the scoring count a wrong answer as a hit; (5) can a reader
be misled in any other way.

## Verdicts

| circuit | answer read? | label | theory | scoring | open items |
|---|---|---|---|---|---|
| `shor15_textbook` | by design (hand-built for a=7, drops U^(2^j) for j>=2 because r divides 4) | `compiled`: correct | OK 0.500 | OK | **F1 blocker**, F7 |
| `shor15_beauregard` | no: 28 cswaps for every coprime a (verified) | `generic`: correct | OK 0.500 | OK | F4 |
| `shor21_beauregard` | no: 45 cswaps for every coprime a (verified) | `generic`: correct | OK 0.3307 | OK | F4 |
| `grover_present_k2..k5` | no: gate structure identical for every key apart from the X gates that set the ciphertext target (verified) | `generic`: correct | OK 1.0 / 0.9453 / 0.9613 / 0.9992 | OK | F5, F6 |

What was checked and is fine, with evidence in `tests/phase1/`:
- Post-processing never rescues a wrong shot (`test_leak_postprocess_*`); the success rule
  `order_from_shot == classical_order` is the one the theory uses.
- The Grover oracle equals the brute-force consistent set on the statevector for every key,
  both `peel_last_sbox` modes, 1 to 4 pairs (`test_grover_oracle_*`); three deliberate bugs in
  the oracle are caught.
- The Beauregard arithmetic is right for 18 (N, a) pairs, unfolded and folded, and the same
  builder recovers the classically computed order and factors for every one of them.
- Simulating the FakeKingston-**transpiled** circuits (what the 2q counts are about) gives the
  theoretical success for the textbook circuit and Grover k=2..4 (reviewer, added in this
  audit); the architect reports the same for all seven within 0.013.

## Findings, ranked

### F1. BLOCKER (claim is false, no number changes): textbook "x7" block computes x13 · verified
`quantum/circuits/shor_textbook.py:28-33` is documented as multiplication by 7 mod 15 and the
metadata says `a=7`. The power-1 block maps `x -> 13x mod 15` (13 = 7^-1). Powers 2, 4 and 8
are right. The order and the QPE distribution are the same for `a` and `a^-1`, so no
distribution test can see it; only a block-level test does.
Test: `test_shor_textbook_blocks_multiply_by_7_to_the_power_mod_15[1]` fails today (the other
three powers pass). Architect's suggested fix: `cswap(w0,w1); cswap(w1,w2); cswap(w2,w3)` before
the CX gates (I did not verify this fix; the test will). Owner: **builder**.
My own gap: the earlier textbook tests could not catch this, and I passed units 1+2 on them.

### F2. CONCERN: the success check is one-sided · reported, reasoning confirmed
The gate requires `success >= theory - 0.02`. A circuit that leaks the answer scores above
theory and passes. Proposed: two-sided, `|success - theory| <= max(0.02, 4 sigma)` with
`sigma = sqrt(0.25 / shots)`. All current circuits pass this (largest deviation 0.0083,
reported). The reviewer's metrics tests are now two-sided. `scripts/gate.py` is lead's. -> **P004**.

### F3. CONCERN: "N=15 a=7 cannot detect noise" is false · verified, reviewer's error
The claim came from builder's note and I repeated it in the P003 "Later" section and a test
comment without re-running it. Measured: dephasing the control before the final H gives 0.170
at N=15 (coherent 0.512, theory 0.500) and 0.075 at N=21 (coherent 0.331); dephasing after the
final H changes nothing (0.491 / 0.329), which is the placement that produced "0.5 either way".
Chance baselines (every outcome equally likely), verified: 0.1719 (N=15), 0.0781 (N=21), 0.25 /
0.125 / 0.0625 / 0.0312 (Grover k=2..5). Fixed in P003 (CORRECTION) and tests added. Lead's note in
PLAN.md that N=15 a=7 "scores 0.50 even when dephased" should be corrected. Success values
should be shown next to their chance baseline. -> **P004**. Owner: lead (docs), builder (field).

### F4. CONCERN: generic cost still varies with the base · verified
There is no `A == 1` test any more, but the transpiled 2q count (opt 3, honest build) still
depends on `a`, through constants that fold to zero angles. Numbers are 5-seed medians from
`benchmarks/phase1-spread-over-a.md` (single-seed numbers mislead: at seed 1234 a=7 looks like the
most expensive N=15 base, 5446, but its median is 5368, mid-pack):
- N=21: 13231 (a=13) to 15164 (a=10), a spread of 14.6%. The order-2 bases (8, 13, 20) average
  13392 against 14805 (r=3) and 14939 (r=6): about 10% cheaper.
- N=15: 5033 (a=4) to 5413 (a=11, 14), a spread of 7.6%, with no order effect (r=2 averages 5286,
  r=4 averages 5228).
- Registry bases: a=7 at N=15 has median 5368 (rank 4 to 5 of 7); a=2 at N=21 has median 14606
  (rank 4 of 11, the cheapest of the r >= 3 bases).
The `generic` label stands (the structure, 28 / 45 cswaps, is the same for every base). But a
single `a` is not "the cost of N". Publish the spread, and do not scale Phase 3 resource numbers
from an order-2 base. -> **P005** (accepted; rules are in PLAN.md Phase 3).

### F5. CONCERN: Grover costs do not carry over to AES · reported, reasoning checked in code
`peel_last_sbox=True` (`grover_present.py:186-187`) works only because the toy SPN has no key
after its last S-box. AES ends with AddRoundKey, so this trick does not apply, and for k=2,3 the
plaintext constants fold into the S-box. Do not extrapolate S-box cost from these 2q counts;
use the `peel_last_sbox=False` cost for any projection. Owner: lead (docs, Phase 3). -> **P005**.

### F6. CONCERN: cutting pairs in OPTIMIZE changes what "success" means · verified guard added
With too few pairs, M > 1: the M=1 iteration count is wrong and "any consistent key" no longer
means "the true key". Test added:
`test_grover_registry_plaintexts_give_m_equal_one_for_every_key` checks M = 1 for **every** key
with the registry's own plaintexts (passes today with 3 pairs), so plan A (2 pairs for k=2..4)
must clear it.

### Notes
- F7 (builder): the textbook docstring says it uses no knowledge of the order, but the skip at
  `shor_textbook.py:24-26` does (r divides 4). Add a `compiled_reason` to the metadata.
- F8 (builder): `SHOR_CASES.n_count` (`registry.py:40-42`) is never checked against the
  builder's metadata, and `_grover_theory` uses `default_iterations`, not `metadata["iterations"]`.
  Both agree today; read them from the metadata, or assert they agree in `build_circuit`.
- F9 (builder / lead, docs): `depth` in the metrics is logical depth with composite gates
  counted as one, and `n_qubits` is logical (the Beauregard N=15 circuit uses 12 physical
  qubits after routing). Say so.
- F10 (lead, docs): Shor "success" means the order was found, not that N was factored. They
  differ for a=14 at N=15 and a=20 at N=21; for the two registry bases both are 3x5 / 3x7.
- F11 (reviewer, done): with one seed, bases with the same order gave byte-identical samples,
  so the multi-`a` leak tests were effectively one sample. Each case now has its own seed.
  Doing this exposed a bug in my own recovery test (it overwrote instead of summing counts per
  recovered value); fixed, and it now also requires the true order to be >97% of the answers.
- F12 (reviewer, done): added key-independent gate structure for Grover, simulation of the
  transpiled circuits (textbook, Grover k=2..4), and two-sided metrics checks.

## Not re-run by the reviewer
Architect-only numbers: the Beauregard multiplier phase-spread check on every basis state, TVD
0.0084 and chi-square p = 0.08 against the analytic distributions, "shot branching gives counts
identical to plain Aer" (metrics.py:41), and transpiled-circuit simulation for shor15, shor21 and
Grover k=5. They are consistent with everything the reviewer measured but are not independent
confirmation.
