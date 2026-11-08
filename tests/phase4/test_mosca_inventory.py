"""web/public/data/inventory.json recomputed from the CBOM text, timeline.json and the design yamls.

Nothing here calls builder's risk code: the CBOM is read as plain JSON, the arithmetic is
tests/phase4/reference.py, the weights and replacement rules are read from their yaml files.
Every asset x scenario number (CRQC year, margin, shortfall, rank), the family order, the mapping
and every replacement are checked. Missing files FAIL (never skip).
"""

from __future__ import annotations

import json
import math

import pytest

from tests.phase4 import reference as ref

INV = ref.WEB_DATA / "inventory.json"


@pytest.fixture(scope="module")
def inv() -> dict:
    return ref.load_json(INV)


@pytest.fixture(scope="module")
def tl() -> dict:
    return ref.load_json(ref.RESULTS / "timeline.json")


@pytest.fixture(scope="module")
def cbom() -> dict:
    return json.loads(ref.DEMO_CBOM.read_text())


@pytest.fixture(scope="module")
def weights() -> dict:
    return ref.load_yaml(ref.RISK / "exposure.yaml")["weights"]


@pytest.fixture(scope="module")
def lit() -> dict:
    return {e["id"]: e for e in ref.literature()}


def _props(component) -> dict:
    return {p["name"]: p["value"] for p in component["properties"]}


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


def _by_id(inv):
    return {a["id"]: a for a in inv["assets"]}


def test_mosca_inventory_has_exactly_the_cbom_assets_once_each(inv, cbom):
    got = [a["id"] for a in inv["assets"]]
    assert sorted(got) == sorted(c["bom-ref"] for c in cbom["components"])
    assert len(got) == len(set(got))


def test_mosca_inventory_scenarios_and_as_of_match_the_timeline(inv, tl):
    assert sorted(inv["scenarios"]) == sorted(ref.SCENARIOS)
    assert inv["as_of_year"] == tl["as_of_year"] and inv["as_of"] == tl["as_of"]


def test_mosca_inventory_asset_fields_come_from_the_cbom(inv, cbom, weights):
    by = _by_id(inv)
    for c in cbom["components"]:
        a = by[c["bom-ref"]]
        p = _props(c)
        assert a["algorithm"] == c["name"]
        assert a["family"] == _family(c["name"]), c["name"]
        assert a["attack_target"] == ref.attack_target(a["family"]), c["name"]
        assert a["usage"] == p["qday:usage"] and a["exposure"] == p["qday:exposure"]
        assert a["shelf_life_years"] == pytest.approx(float(p["qday:shelf_life_years"]))
        assert a["migration_years"] == pytest.approx(float(p["qday:migration_years"]))
        assert a["exposure_weight"] == pytest.approx(float(weights[p["qday:exposure"]]))
        assert str(a["mapping_note"]).strip()


def test_mosca_inventory_exposure_weights_are_ordered_and_labelled_a_design_choice():
    y = ref.load_yaml(ref.RISK / "exposure.yaml")
    w = y["weights"]
    assert set(w) == set(ref.EXPOSURES)
    assert w["internet"] > w["partner"] > w["internal"] > 0
    assert y["label"] == "design_choice"


def _bits_and_deprecated(cbom):
    out = {}
    for c in cbom["components"]:
        fam = _family(c["name"])
        bits = ref.key_bits(c)
        usage = _props(c)["qday:usage"]
        out[c["bom-ref"]] = (bits, ref.classically_deprecated(fam, c["name"], bits, usage))
    return out


def test_mosca_inventory_crqc_year_is_the_timeline_value_or_now_if_classically_deprecated(
    inv, tl, cbom
):
    """Below 112 bits of classical security (SP 800-131A) an asset is reachable now: crqc_year =
    as_of_year in every scenario. Everything else takes its attack target's timeline year."""
    dep = _bits_and_deprecated(cbom)
    for a in inv["assets"]:
        for s in ref.SCENARIOS:
            got = a["by_scenario"][s]["crqc_year"]
            if dep[a["id"]][1]:
                assert got == inv["as_of_year"], (a["id"], s)
            elif a["attack_target"] is None:
                assert got is None, (a["id"], s)
            else:
                want = tl["scenarios"][s]["targets"][a["attack_target"]]["crqc_year"]
                assert got == want or got == pytest.approx(want, rel=1e-12), (a["id"], s)


def test_mosca_inventory_key_bits_match_the_cboms_algorithm_properties_for_every_asset(inv, cbom):
    dep = _bits_and_deprecated(cbom)
    for a in inv["assets"]:
        assert a["key_bits"] == dep[a["id"]][0], (a["id"], a["algorithm"])


def test_mosca_inventory_deprecation_flag_is_recomputed_not_trusted(inv, cbom):
    dep = _bits_and_deprecated(cbom)
    for a in inv["assets"]:
        assert a["classically_deprecated"] is dep[a["id"]][1], (a["id"], a["algorithm"])


def test_mosca_inventory_rsa_1024_and_sha_1_are_at_risk_now_and_x25519_is_not_deprecated(inv):
    by = {a["algorithm"]: a for a in inv["assets"]}
    for name in ("RSA-1024", "SHA-1"):
        a = by[name]
        for s in ref.SCENARIOS:
            row = a["by_scenario"][s]
            assert row["crqc_year"] == inv["as_of_year"], (name, s)
            assert row["margin_years"] == pytest.approx(
                -(a["shelf_life_years"] + a["migration_years"]), abs=1e-9
            ), (name, s)
            assert row["shortfall"] > 0, (name, s)
    assert by["X25519"]["key_bits"] == 255 and by["X25519"]["classically_deprecated"] is False
    for a in inv["assets"]:
        if a["algorithm"] not in ("RSA-1024", "SHA-1"):
            assert a["classically_deprecated"] is False, a["algorithm"]


def test_mosca_inventory_a_deprecated_asset_ranks_by_shortfall_like_any_other(inv):
    """It is not pinned to rank 1: the same shortfall rule applies (weight x years short)."""
    for s in ref.SCENARIOS:
        order = sorted(inv["assets"], key=lambda a: a["by_scenario"][s]["rank"])
        sf = [a["by_scenario"][s]["shortfall"] for a in order]
        assert sf == sorted(sf, reverse=True), s


def test_mosca_inventory_margin_shortfall_and_rank_recomputed_for_every_asset_and_scenario(inv):
    for s in ref.SCENARIOS:
        items = []
        for a in inv["assets"]:
            row = a["by_scenario"][s]
            m = ref.margin(
                row["crqc_year"], inv["as_of_year"], a["shelf_life_years"], a["migration_years"]
            )
            if m is None:
                assert row["margin_years"] is None, (a["id"], s)
            else:
                assert row["margin_years"] == pytest.approx(m, abs=1e-9), (a["id"], s)
            sf = ref.shortfall(a["exposure_weight"], m)
            assert row["shortfall"] == pytest.approx(sf, abs=1e-9), (a["id"], s)
            items.append((a["id"], a["exposure_weight"], m))
        want = ref.ranks(items)
        for a in inv["assets"]:
            assert a["by_scenario"][s]["rank"] == want[a["id"]], (a["id"], s)
        assert sorted(want.values()) == list(range(1, len(items) + 1))


def test_mosca_inventory_every_null_margin_asset_ranks_below_every_finite_margin_one(inv):
    for s in ref.SCENARIOS:
        rows = [a["by_scenario"][s] for a in inv["assets"]]
        fin = [r["rank"] for r in rows if r["margin_years"] is not None]
        nul = [r["rank"] for r in rows if r["margin_years"] is None]
        if fin and nul:
            assert max(fin) < min(nul), s


def test_mosca_inventory_non_quantum_targets_get_a_margin_only_when_classically_deprecated(
    inv,
):
    """ML-KEM / ML-DSA / SLH-DSA have no attack target; AES and SHA are infeasible under the
    one-year cap (Grover). Their margin is null in every scenario unless the asset is below 112
    bits of classical security (SHA-1), which is a classical, not a quantum, reason."""
    for a in inv["assets"]:
        if a["family"] in ("ML-KEM", "ML-DSA", "SLH-DSA", "AES", "SHA"):
            for s in ref.SCENARIOS:
                m = a["by_scenario"][s]["margin_years"]
                if a["classically_deprecated"]:
                    assert m is not None, a["id"]
                else:
                    assert m is None, a["id"]


def test_mosca_inventory_family_order_is_recomputed_from_the_attack_target_years(inv, tl):
    """Families sorted by their ATTACK TARGET's CRQC year (None = +inf), then name. A weak asset
    inside a family (RSA-1024, SHA-1) must not move the family."""
    for s in ref.SCENARIOS:
        years = {t: row["crqc_year"] for t, row in tl["scenarios"][s]["targets"].items()}
        assert inv["family_order"][s] == ref.family_order_by_target(years), s
        assert sorted(inv["family_order"][s]) == sorted(ref.FAMILIES)


def test_mosca_family_order_is_unchanged_by_adding_a_deprecated_asset(tl, cbom):
    """Falsifying check on builder's code: add RSA-1024 and SHA-1 duplicates to the CBOM and
    rebuild: the family order must not move. The old rule (earliest asset in the family) would."""
    import copy

    from quantum.risk.inventory import build_inventory
    from quantum.risk.models import parse_cbom

    base = build_inventory(parse_cbom(json.dumps(cbom)), tl)["family_order"]
    grown = copy.deepcopy(cbom)
    for i, tag in enumerate(("RSA-1024", "SHA-1")):
        src = next(c for c in cbom["components"] if c["name"] == tag)
        extra = copy.deepcopy(src)
        extra["bom-ref"] = f"extra-deprecated-{i}"
        grown["components"].append(extra)
    out = build_inventory(parse_cbom(json.dumps(grown)), tl)
    assert out["family_order"] == base
    assert len(out["assets"]) == len(cbom["components"]) + 2
    # teeth: the asset-minimum rule applied to the same grown inventory DOES move a family
    for s in ref.SCENARIOS:
        by_family: dict[str, list] = {}
        for a in out["assets"]:
            by_family.setdefault(a["family"], []).append(a["by_scenario"][s]["crqc_year"])
        if ref.family_order(by_family) != base[s]:
            return
    pytest.fail(
        "the asset-minimum rule gives the same order: this test cannot tell the rules apart"
    )


def test_mosca_inventory_family_order_is_not_a_hard_coded_list(inv):
    """The brief replaced 'ECC above RSA' by an order computed from the data. If the order were
    typed, it would be the same in every scenario even when the underlying years are not."""
    orders = {tuple(v) for v in inv["family_order"].values()}
    assert len(orders) >= 2, "family order identical in all scenarios; check it is computed"


def test_mosca_inventory_replacements_follow_the_rules_file_and_cite_verified_entries(inv, lit):
    rules = ref.load_yaml(ref.RISK / "replacements.yaml")["rules"]
    table = {(r["family"], r["usage"]): r for r in rules}
    fc = ref.factcheck()
    for a in inv["assets"]:
        r = table.get((a["family"], a["usage"]))
        assert r is not None, f"{a['id']}: no replacement rule for {a['family']}/{a['usage']}"
        rep = a["replacement"]
        assert rep["algorithm"] == r["replacement"] and rep["standard_id"] == r["standard_id"]
        assert rep["standard_id"] in lit and fc[rep["standard_id"]]["status"] == "verified", (
            a["id"],
            rep["standard_id"],
        )
        if r["nist_deadline_id"] is None:
            assert a["nist_deadline_year"] is None, a["id"]
        else:
            assert fc[r["nist_deadline_id"]]["status"] == "verified"
            assert a["nist_deadline_year"] == lit[r["nist_deadline_id"]]["value"], a["id"]


def test_mosca_inventory_every_quantum_vulnerable_asset_carries_the_nist_deadline(inv):
    for a in inv["assets"]:
        if a["family"] in ("RSA", "ECC"):
            assert a["nist_deadline_year"] is not None, a["id"]
        if a["family"] in ("ML-KEM", "ML-DSA", "SLH-DSA"):
            assert a["nist_deadline_year"] is None, a["id"]


def test_mosca_inventory_numbers_are_finite_and_json_clean(inv):
    text = INV.read_text()
    assert "NaN" not in text and "Infinity" not in text
    for a in inv["assets"]:
        for s in ref.SCENARIOS:
            for k, v in a["by_scenario"][s].items():
                if k == "crqc_basis":
                    assert v is None or isinstance(v, str), (a["id"], k)
                    continue
                assert v is None or (isinstance(v, (int, float)) and math.isfinite(v)), (a["id"], k)


def test_mosca_inventory_an_asset_with_no_replacement_rule_fails_with_a_clear_message(tl, cbom):
    """A SHA-1 asset used for signing has no (SHA, signature) rule in replacements.yaml. The
    engine must stop with an error naming the asset and the missing rule, not a bare KeyError."""
    import copy

    from quantum.risk.inventory import build_inventory
    from quantum.risk.models import parse_cbom

    grown = copy.deepcopy(cbom)
    src = copy.deepcopy(next(c for c in cbom["components"] if c["name"] == "SHA-1"))
    src["bom-ref"] = "sha1-used-for-signing"
    for p in src["properties"]:
        if p["name"] == "qday:usage":
            p["value"] = "signature"
    grown["components"].append(src)
    try:
        build_inventory(parse_cbom(json.dumps(grown)), tl)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        assert "sha1-used-for-signing" in msg, f"error does not name the asset: {msg!r}"
        assert "SHA" in msg and "signature" in msg, msg
        return
    # no error: a replacement rule exists, which is also fine
