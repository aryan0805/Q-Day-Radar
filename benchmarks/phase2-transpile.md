# Phase 2 transpile verification

Optimization level 3, FakeKingston, 5-seed medians, seeds 1234..1238, qiskit 2.6.2. Metric: `num_nonlocal_gates()` after transpile.

| circuit | median 2q | min..max | recorded median | match | depth (seed 1234) |
|---|---|---|---|---|---|
| shor15_textbook | 173 | 172..184 | 173 | yes | 294 |
| shor15_beauregard | 5368 | 5348..5446 | 5368 | yes | 11041 |
| shor21_beauregard | 14606 | 14575..14864 | 14606 | yes | 28313 |
| grover_present_k2 | 249 | 249..262 | 249 | yes | 551 |
| grover_present_k3 | 625 | 623..638 | 625 | yes | 1447 |
| grover_present_k4 | 1104 | 1083..1162 | 1104 | yes | 2294 |
| grover_present_k5 | 2654 | 2621..2706 | 2654 | yes | 5430 |

## Cross-check with phase 1

- shor15_textbook: after-r1 median 173 (equal); baseline median 180 (different)
- shor15_beauregard: after-r1 median 5368 (equal); baseline median 5368 (equal)
- shor21_beauregard: after-r1 median 14606 (equal); baseline median 14606 (equal)
- grover_present_k2: after-r1 median 249 (equal); baseline median 402 (different)
- grover_present_k3: after-r1 median 625 (equal); baseline median 988 (different)
- grover_present_k4: after-r1 median 1104 (equal); baseline median 1719 (different)
- grover_present_k5: after-r1 median 2654 (equal); baseline median 2654 (equal)

## AI transpiler pass

The AI transpiler pass was NOT run by the reviewer, so there are no AI numbers here.

- mode: local
- reason: qiskit-ibm-transpiler not importable here (No module named 'qiskit_ibm_transpiler'). Probe 2026-11-08 with `uv run --with qiskit-ibm-transpiler`: 0.18.0 pulls qiskit-ibm-runtime down to 0.45.1 (no FakeKingston) and its import fails under qiskit 2.6.2 with 'No module named qiskit.synthesis.linear.linear_matrix_utils'. Kept opt 3.

This reason is as recorded by builder and was not reproduced by the reviewer (no install was attempted).

Opt level 3 is therefore kept for every circuit (`chosen`: opt3).

Git HEAD 86fba5ab8fea71540987f67ef2093e1747b2c8ce; timestamp 2026-11-08T02:08:55.446510+00:00.
