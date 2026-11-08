# Phase 1 spread over base a (P005)

Honest generic Beauregard Shor circuit (`build_shor(N, a)`, defaults), optimization level 3, FakeKingston. Registry bases are a=7 (N=15) and a=2 (N=21). Order r is a label only. Seeds [1234, 1235, 1236, 1237, 1238]. Qiskit 2.6.2. HEAD 4896340a2c; `git status --short quantum`: dirty (see JSON).

cswap deviations: none

## N=15

| a | r | cswap | 2q seed1234 | 2q min | 2q median | 2q max | depth |
|---|---|---|---|---|---|---|---|
| 2 | 4 | 28 | 5088 | 5019 | 5088 | 5127 | 10295 |
| 4 | 2 | 28 | 5033 | 4963 | 5033 | 5059 | 10235 |
| 7 | 4 | 28 | 5446 | 5348 | 5368 | 5446 | 11041 |
| 8 | 4 | 28 | 5088 | 5018 | 5088 | 5117 | 10295 |
| 11 | 2 | 28 | 5413 | 5317 | 5413 | 5452 | 11003 |
| 13 | 4 | 28 | 5434 | 5342 | 5368 | 5448 | 10993 |
| 14 | 2 | 28 | 5413 | 5317 | 5413 | 5452 | 11003 |

- Per-base seed-median over 7 bases: min 5033, median 5368, max 5413
- Spread (max/min - 1): 7.6%
- Registry base a=7: median 5368; rank 4-5 (ascending, 1 = cheapest, of 7; range reflects ties)
- Mean of per-base medians by order:
  - r=2: 5286.3 (3 bases)
  - r=4: 5228.0 (4 bases)

## N=21

| a | r | cswap | 2q seed1234 | 2q min | 2q median | 2q max | depth |
|---|---|---|---|---|---|---|---|
| 2 | 6 | 45 | 14575 | 14575 | 14606 | 14864 | 28313 |
| 4 | 3 | 45 | 14747 | 14602 | 14747 | 14824 | 28187 |
| 5 | 6 | 45 | 15038 | 14927 | 15029 | 15077 | 28523 |
| 8 | 2 | 45 | 13377 | 13276 | 13531 | 13617 | 25617 |
| 10 | 6 | 45 | 15183 | 14910 | 15164 | 15222 | 29029 |
| 11 | 6 | 45 | 14627 | 14457 | 14691 | 14747 | 28027 |
| 13 | 2 | 45 | 13231 | 13142 | 13231 | 13363 | 25592 |
| 16 | 3 | 45 | 14878 | 14654 | 14862 | 14878 | 27793 |
| 17 | 6 | 45 | 14976 | 14966 | 15022 | 15299 | 28539 |
| 19 | 6 | 45 | 15105 | 14994 | 15122 | 15242 | 29124 |
| 20 | 2 | 45 | 13367 | 13324 | 13414 | 13600 | 25498 |

- Per-base seed-median over 11 bases: min 13231, median 14747, max 15164
- Spread (max/min - 1): 14.6%
- Registry base a=2: median 14606; rank 4-4 (ascending, 1 = cheapest, of 11; range reflects ties)
- Mean of per-base medians by order:
  - r=2: 13392.0 (3 bases)
  - r=3: 14804.5 (2 bases)
  - r=6: 14939.0 (6 bases)
