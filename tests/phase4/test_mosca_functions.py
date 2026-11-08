"""quantum.risk.mosca and quantum.risk.mapping against the hand-computed fixtures and the reference.

The fixtures (tests/phase4/mosca_cases.py) were worked on paper; the reference
(tests/phase4/reference.py) is an independent implementation. Builder's functions must agree with
both, and must obey the monotonicity properties for random inputs.
"""

from __future__ import annotations

import math
import random

import pytest

from quantum.risk import mosca
from tests.phase4 import mosca_cases as mc
from tests.phase4 import reference as ref


def _builder(scenario: str):
    rows = {}
    for aid, (target, x, y, w) in mc.ASSETS.items():
        crqc = mc.CRQC[scenario].get(target) if target else None
        m = mosca.margin(crqc, mc.AS_OF, x, y)
        rows[aid] = (m, mosca.shortfall(w, m))
    ranks = mosca.rank([mosca.Scored(a, m, s) for a, (m, s) in rows.items()])
    return {a: (*rows[a], ranks[a]) for a in rows}


@pytest.mark.parametrize("scenario", ["median", "optimistic"])
def test_mosca_builder_matches_the_hand_computed_assets(scenario):
    got, want = _builder(scenario), mc.HAND[scenario]
    for aid, (m, s, r) in want.items():
        gm, gs, gr = got[aid]
        assert (gm is None) == (m is None), (scenario, aid)
        if m is not None:
            assert gm == pytest.approx(m, abs=1e-12), (scenario, aid)
        assert gs == pytest.approx(s, abs=1e-12), (scenario, aid)
        assert gr == r, (scenario, aid)


def test_mosca_builder_null_crqc_year_gives_null_margin_zero_shortfall_and_last_rank():
    assert mosca.margin(None, 2026, 5, 5) is None
    assert mosca.shortfall(3, None) == 0
    items = [mosca.Scored("n", None, 0.0), mosca.Scored("f", 400.0, 0.0)]
    assert mosca.rank(items) == {"f": 1, "n": 2}


def test_mosca_builder_ties_break_on_margin_then_asset_id():
    a = mosca.Scored("b", -2.0, 2.0)
    b = mosca.Scored("a", -1.0, 2.0)
    assert mosca.rank([a, b]) == {"b": 1, "a": 2}
    c = mosca.Scored("z", -1.0, 1.0)
    d = mosca.Scored("m", -1.0, 1.0)
    assert mosca.rank([c, d]) == {"m": 1, "z": 2}


def test_mosca_builder_agrees_with_the_reference_on_random_portfolios():
    rng = random.Random(2026)
    for _ in range(300):
        n = rng.randrange(2, 12)
        items = []
        for i in range(n):
            crqc = None if rng.random() < 0.2 else 2026 + rng.uniform(0, 40)
            x, y = rng.uniform(0, 25), rng.uniform(0, 12)
            w = rng.choice([1, 2, 3])
            items.append((f"a{i:02d}", w, crqc, x, y))
        ref_m = {a: ref.margin(c, 2026, x, y) for a, w, c, x, y in items}
        got_m = {a: mosca.margin(c, 2026, x, y) for a, w, c, x, y in items}
        for a in ref_m:
            assert (ref_m[a] is None) == (got_m[a] is None)
            if ref_m[a] is not None:
                assert got_m[a] == pytest.approx(ref_m[a], abs=1e-9)
        want = ref.ranks([(a, w, ref_m[a]) for a, w, *_ in items])
        got = mosca.rank(
            [mosca.Scored(a, got_m[a], mosca.shortfall(w, got_m[a])) for a, w, *_ in items]
        )
        assert got == want


def _portfolio(rng, n=8):
    return [(f"a{i}", rng.choice([1, 2, 3]), rng.uniform(-20, 40)) for i in range(n)]


def _ranks(items):
    return mosca.rank([mosca.Scored(a, m, mosca.shortfall(w, m)) for a, w, m in items])


def test_mosca_raising_x_or_y_never_improves_an_assets_rank():
    rng = random.Random(21)
    for _ in range(300):
        base = _portfolio(rng)
        k = rng.randrange(len(base))
        bump = rng.uniform(0.1, 15)
        worse = [(a, w, m - bump if j == k else m) for j, (a, w, m) in enumerate(base)]
        assert _ranks(worse)[f"a{k}"] <= _ranks(base)[f"a{k}"]


def test_mosca_x_or_y_through_margin_function_never_lowers_shortfall():
    rng = random.Random(22)
    for _ in range(300):
        crqc, x, y = 2026 + rng.uniform(0, 40), rng.uniform(0, 25), rng.uniform(0, 12)
        m0 = mosca.margin(crqc, 2026, x, y)
        for m1 in (mosca.margin(crqc, 2026, x + 1, y), mosca.margin(crqc, 2026, x, y + 1)):
            assert m1 < m0
            assert mosca.shortfall(2, m1) >= mosca.shortfall(2, m0)


def test_mosca_raising_exposure_never_improves_an_at_risk_assets_rank():
    rng = random.Random(23)
    for _ in range(300):
        base = _portfolio(rng)
        risky = [j for j, (_, _, m) in enumerate(base) if m < 0]
        if not risky:
            continue
        k = rng.choice(risky)
        higher = [(a, w + 1 if j == k else w, m) for j, (a, w, m) in enumerate(base)]
        assert _ranks(higher)[f"a{k}"] <= _ranks(base)[f"a{k}"]


def test_mosca_every_null_margin_ranks_below_every_finite_margin():
    rng = random.Random(24)
    for _ in range(100):
        items = [
            (f"f{i}", rng.choice([1, 2, 3]), rng.uniform(-30, 80))
            for i in range(rng.randrange(1, 10))
        ] + [(f"n{i}", rng.choice([1, 2, 3]), None) for i in range(rng.randrange(1, 5))]
        rk = _ranks(items)
        fin = [rk[a] for a, _, m in items if m is not None]
        nul = [rk[a] for a, _, m in items if m is None]
        assert max(fin) < min(nul)


# ------------------------------------------------------------------ mapping from the CBOM text
def _family(name: str) -> str:
    n = name.upper()
    for prefix, fam in (
        ("ML-KEM", "ML-KEM"),
        ("ML-DSA", "ML-DSA"),
        ("SLH-DSA", "SLH-DSA"),
        ("RSA", "RSA"),
        ("AES", "AES"),
    ):
        if n.startswith(prefix):
            return fam
    if n.startswith(("ECDSA", "ECDH", "ED25519", "X25519")):
        return "ECC"
    if "SHA" in n:
        return "SHA"
    raise AssertionError(n)


def test_mosca_mapping_family_and_target_match_the_reference_for_every_cbom_asset():
    from quantum.risk.mapping import classify
    from quantum.risk.models import parse_cbom

    cbom = parse_cbom(ref.DEMO_CBOM.read_text())
    assert cbom.components
    for comp in cbom.components:
        c = classify(comp)
        assert c.family == _family(comp.name), comp.name
        assert c.attack_target == ref.attack_target(c.family), comp.name
        assert c.mapping_note.strip(), comp.name


@pytest.mark.parametrize(
    ("name", "param", "curve", "target", "bound"),
    [
        ("RSA-2048", "2048", None, "rsa2048", False),
        ("RSA-4096", "4096", None, "rsa2048", True),
        ("ECDSA", None, "nist/P-256", "ecc256", False),
        ("ECDSA", None, "nist/P-521", "ecc256", True),
        ("X25519", None, "x25519", "ecc256", False),
        ("AES-256-GCM", "256", None, "aes128", True),
        ("SHA3-256", None, None, "aes128", True),
        ("ML-KEM-768", None, None, None, False),
        ("SLH-DSA-SHA2-128s", None, None, None, False),
    ],
)
def test_mosca_mapping_rules_from_the_brief(name, param, curve, target, bound):
    from quantum.risk.mapping import classify
    from quantum.risk.models import Component

    comp = Component.model_validate(
        {
            "type": "cryptographic-asset",
            "bom-ref": "x",
            "name": name,
            "cryptoProperties": {
                "assetType": "algorithm",
                "algorithmProperties": {
                    "primitive": "signature",
                    **({"parameterSetIdentifier": param} if param else {}),
                    **({"curve": curve} if curve else {}),
                },
            },
        }
    )
    c = classify(comp)
    assert c.attack_target == target
    if bound:  # larger keys inherit the smaller target's cost: labelled as a lower bound
        assert "lower bound" in c.mapping_note.lower()


def test_mosca_mapping_an_unmapped_curve_is_refused_not_silently_assigned():
    from quantum.risk.mapping import classify
    from quantum.risk.models import Component

    comp = Component.model_validate(
        {
            "type": "cryptographic-asset",
            "bom-ref": "x",
            "name": "ECDSA",
            "cryptoProperties": {
                "assetType": "algorithm",
                "algorithmProperties": {"primitive": "signature", "curve": "sect571k1"},
            },
        }
    )
    with pytest.raises(ValueError):
        classify(comp)


def test_mosca_math_is_float_safe_for_huge_margins():
    assert math.isfinite(mosca.margin(2026 + 1e6, 2026, 10, 10))
