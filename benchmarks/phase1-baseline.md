# Phase 1 baseline (BEFORE)

This is the BEFORE state for the Phase 1 OPTIMIZE step: each registry circuit transpiled at optimization level 3 for FakeKingston with seed_transpiler 1234 (counts and depth), plus the 2-qubit gate count for seeds 1234 to 1238 reported as min / median / max. Wall-clock is the median of 3 seed-1234 transpiles. shor15_beauregard is the honest circuit (build_shor(15, 7) applies all 28 controlled swaps, identity multipliers included). shor15_beauregard_skip_identity is the compiled variant (build_shor(15, 7, skip_identity=True), the old 1068-gate number); it is not a registry circuit and is shown only so the cost of honesty is visible. Qiskit 2.6.2, HEAD 4896340a2c, 2026-11-07T23:47:46.732181+00:00. All seed-1234 two-qubit counts and transpiled depths match results/metrics/*.json. No circuit took more than 3 minutes to transpile.

| circuit | logical qubits | logical size | 2q (seed 1234) | 2q min / median / max (5 seeds) | depth (seed 1234) | transpile s (median of 3) | matches results/metrics |
|---|---|---|---|---|---|---|---|
| shor15_textbook | 12 | 27 | 180 | 172 / 180 / 189 | 322 | 0.03 | yes |
| shor21_beauregard | 13 | 21376 | 14575 | 14575 / 14606 / 14864 | 28313 | 0.61 | yes |
| grover_present_k2 | 9 | 268 | 402 | 397 / 402 / 414 | 901 | 0.05 | yes |
| grover_present_k3 | 10 | 610 | 988 | 953 / 988 / 1042 | 2179 | 0.06 | yes |
| grover_present_k4 | 11 | 974 | 1790 | 1646 / 1719 / 1790 | 3815 | 0.07 | yes |
| grover_present_k5 | 12 | 1362 | 2621 | 2621 / 2654 / 2706 | 5430 | 0.08 | yes |
| shor15_beauregard | 11 | 7064 | 5446 | 5348 / 5368 / 5446 | 11041 | 0.25 | yes |
| shor15_beauregard_skip_identity | 11 | 1238 | 1068 | 1010 / 1039 / 1079 | 2383 | 0.04 | n/a (compiled) |


## shor15_beauregard vs results/metrics/shor15_beauregard.json

Seed 1234: here two_qubit_gates 5446, depth 11041; metrics file two_qubit_gates 5446, transpile.depth 11041. They match.

## Cost of honesty

Honest (all multipliers) 5446 vs skip_identity 1068 two-qubit gates at seed 1234 (5.10x); 5-seed medians 5368 vs 1039.

## How to compare AFTER

Rerun with the same backend (FakeKingston), optimization level 3 and seeds 1234 to 1238, and compare the 5-seed median two-qubit count (not a single seed) against the BEFORE median. Compare shor15_beauregard against the honest row, never against shor15_beauregard_skip_identity.
