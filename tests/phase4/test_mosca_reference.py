"""Mosca margin, shortfall and ranking: hand-computed assets and properties of the reference.

Falsifying checks: hand-computed assets under two scenarios (worked on paper in mosca_cases.py),
plus tie-break, null-last and monotonicity properties.
"""

from __future__ import annotations

import random

import pytest

from tests.phase4 import mosca_cases as mc
from tests.phase4 import reference as ref


def _compute(scenario: str, assets=None):
    assets = assets or mc.ASSETS
    out, items = {}, []
    for aid, (target, x, y, w) in assets.items():
        crqc = mc.CRQC[scenario].get(target) if target else None
        m = ref.margin(crqc, mc.AS_OF, x, y)
        out[aid] = [m, ref.shortfall(w, m)]
        items.append((aid, w, m))
    rk = ref.ranks(items)
    return {aid: (m, s, rk[aid]) for aid, (m, s) in out.items()}


@pytest.mark.parametrize("scenario", ["median", "optimistic"])
def test_mosca_hand_computed_assets_match_the_reference(scenario):
    assert _compute(scenario) == mc.HAND[scenario]


def test_mosca_hand_computed_ranking_differs_between_scenarios():
    """The two scenarios must give different orders, or the fixture proves nothing."""
    med = {a: v[2] for a, v in mc.HAND["median"].items()}
    opt = {a: v[2] for a, v in mc.HAND["optimistic"].items()}
    assert med != opt


def test_mosca_ties_break_on_margin_then_on_asset_id():
    # equal shortfall 2.0: margin -2 (w=1) vs margin -1 (w=2) -> the more negative margin first
    items = [("b", 1.0, -2.0), ("a", 2.0, -1.0)]
    assert ref.ranks(items) == {"b": 1, "a": 2}
    # identical shortfall and margin -> asset id decides
    assert ref.ranks([("z", 1.0, -1.0), ("m", 1.0, -1.0)]) == {"m": 1, "z": 2}


def test_mosca_every_null_margin_ranks_below_every_finite_margin():
    rng = random.Random(7)
    items = [(f"f{i}", rng.choice([0.3, 1.0, 2.0]), rng.uniform(-30, 80)) for i in range(25)]
    items += [(f"n{i}", rng.choice([0.3, 1.0, 2.0]), None) for i in range(6)]
    rk = ref.ranks(items)
    assert max(rk[i[0]] for i in items if i[2] is not None) < min(
        rk[i[0]] for i in items if i[2] is None
    )


def test_mosca_raising_x_or_y_never_improves_the_rank():
    rng = random.Random(11)
    for _ in range(200):
        n = 8
        base = [(f"a{i}", rng.choice([0.3, 0.6, 1.0]), rng.uniform(-20, 40)) for i in range(n)]
        k = rng.randrange(n)
        bump = rng.uniform(0.1, 15)  # more x or y lowers the margin by `bump`
        worse = [(i, w, m - bump if j == k else m) for j, (i, w, m) in enumerate(base)]
        assert ref.ranks(worse)[f"a{k}"] <= ref.ranks(base)[f"a{k}"]


def test_mosca_raising_exposure_never_improves_the_rank_of_an_at_risk_asset():
    rng = random.Random(13)
    for _ in range(200):
        n = 8
        base = [(f"a{i}", rng.choice([0.3, 0.6, 1.0]), rng.uniform(-20, 40)) for i in range(n)]
        at_risk = [j for j, (_, _, m) in enumerate(base) if m < 0]
        if not at_risk:
            continue
        k = rng.choice(at_risk)
        higher = [(i, w * 1.5 if j == k else w, m) for j, (i, w, m) in enumerate(base)]
        assert ref.ranks(higher)[f"a{k}"] <= ref.ranks(base)[f"a{k}"]


def test_mosca_a_faster_doubling_time_never_makes_any_crqc_year_later():
    for needed in (1e3, 5e4, 7e6):
        late = ref.crqc_year(2026, 3.0, needed, 3600, 1000)
        early = ref.crqc_year(2026, 1.5, needed, 3600, 1000)
        assert early <= late
