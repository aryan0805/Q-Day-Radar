"""Hand-computed Mosca fixtures, shared by the reference tests and the tests of builder's code.

Fixture weights and CRQC years are made up for the arithmetic; they are NOT the design values.
as_of_year = 2026. margin = (crqc_year - 2026) - (x + y); shortfall = weight * max(0, -margin).

  scenario "median":      crqc rsa2048 = 2034, ecc256 = 2040   (z = 8, 14)
  scenario "optimistic":  crqc rsa2048 = 2031, ecc256 = 2036   (z = 5, 10)

  A  rsa2048  x=10 y=3  w=1.0
       median 8-13 = -5, shortfall 5.0      optimistic 5-13 = -8, shortfall 8.0
  B  ecc256   x=8  y=3  w=2.0
       median 14-11 = +3, shortfall 0       optimistic 10-11 = -1, shortfall 2.0
  C  rsa2048  x=6  y=1  w=0.5
       median 8-7 = +1, shortfall 0         optimistic 5-7 = -2, shortfall 1.0
  D  ML-KEM (no attack target)  margin None, shortfall 0 in both scenarios

  median ranking:      A(5.0) 1, then C(margin 1) 2, B(margin 3) 3, D(null) 4
  optimistic ranking:  A(8.0) 1, B(2.0) 2, C(1.0) 3, D(null) 4
"""

from __future__ import annotations

AS_OF = 2026
CRQC = {
    "median": {"rsa2048": 2034.0, "ecc256": 2040.0},
    "optimistic": {"rsa2048": 2031.0, "ecc256": 2036.0},
}
# id: (attack_target, x, y, weight)
ASSETS = {
    "A": ("rsa2048", 10, 3, 1.0),
    "B": ("ecc256", 8, 3, 2.0),
    "C": ("rsa2048", 6, 1, 0.5),
    "D": (None, 20, 5, 1.0),
}
# scenario -> id -> (margin, shortfall, rank)
HAND = {
    "median": {
        "A": (-5.0, 5.0, 1),
        "B": (3.0, 0.0, 3),
        "C": (1.0, 0.0, 2),
        "D": (None, 0.0, 4),
    },
    "optimistic": {
        "A": (-8.0, 8.0, 1),
        "B": (-1.0, 2.0, 2),
        "C": (-2.0, 1.0, 3),
        "D": (None, 0.0, 4),
    },
}
