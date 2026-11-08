# Phase 1 OPTIMIZE round 1: AFTER vs BEFORE

- Round: OPTIMIZE round 1, optimization level 3, FakeKingston, 5-seed medians (seeds 1234..1238)
- git HEAD: `4896340a2c91e90922c21d1dabe2d64b5393306f`
- `git status --short quantum`:
```
?? quantum/circuits/
?? quantum/classical/
?? quantum/metrics.py
```
- Verdict: 'improved' only if AFTER median is lower than BEFORE median by more than the larger of the two 5-seed ranges (max-min); otherwise 'no significant change'.

| circuit | BEFORE median 2q | AFTER median 2q | abs change | % change | BEFORE seed1234 | AFTER seed1234 | AFTER min/max | noise | verdict | what changed |
|---|---|---|---|---|---|---|---|---|---|---|
| shor15_textbook | 180 | 173 | -7 | -3.9% | 180 | 181 | 172/184 | 17 | no significant change | correctness fix, not an optimization (F1 reversed swap order) |
| shor15_beauregard | 5368 | 5368 | +0 | +0.0% | 5446 | 5446 | 5348/5446 | 98 | no significant change | unchanged (round 2) |
| shor21_beauregard | 14606 | 14606 | +0 | +0.0% | 14575 | 14575 | 14575/14864 | 289 | no significant change | unchanged (round 2) |
| grover_present_k2 | 402 | 249 | -153 | -38.1% | 402 | 249 | 249/262 | 17 | improved | plan A: plaintexts (1,6) |
| grover_present_k3 | 988 | 625 | -363 | -36.7% | 988 | 629 | 623/638 | 89 | improved | plan A: plaintexts (1,6) |
| grover_present_k4 | 1719 | 1104 | -615 | -35.8% | 1790 | 1104 | 1083/1162 | 144 | improved | plan A: plaintexts (1,6) |
| grover_present_k5 | 2654 | 2654 | +0 | +0.0% | 2621 | 2621 | 2621/2706 | 85 | no significant change | plan A: plaintexts (1,6,11) |

Logical size (qc.size()) BEFORE vs AFTER, Grover k=2..4:

| circuit | BEFORE | AFTER |
|---|---|---|
| grover_present_k2 | 268 | 162 |
| grover_present_k3 | 610 | 378 |
| grover_present_k4 | 974 | 620 |

Note: round 1 was plan A (`quantum/circuits/registry.py` GROVER_PLAINTEXTS now (1,6) for k=2,3,4 and (1,6,11) for k=5; a registry/demo-instance change, builder code untouched). shor15_textbook also changed because the F1 correctness fix reversed its swap order (181 2q at seed 1234 vs 180); this is a bug fix and NOT an optimization (correctness fix, not an optimization). shor15_beauregard and shor21_beauregard are unchanged and belong to round 2.
