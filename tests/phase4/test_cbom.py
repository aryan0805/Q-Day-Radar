"""The demo CBOM: official CycloneDX 1.6 schema, exact round trip, content rules, broken inputs.

Falsifying checks: the official strict validator (not our models) judges the file; a set of
deliberately broken CBOMs must each be rejected by the schema or by our models; the round trip is
compared as parsed JSON, so a field our models silently dropped would show.
"""

from __future__ import annotations

import copy
import json
import re

import pytest

from tests.phase4 import reference as ref


@pytest.fixture(scope="module")
def text() -> str:
    if not ref.DEMO_CBOM.exists():
        pytest.fail(f"{ref.DEMO_CBOM.relative_to(ref.ROOT)} does not exist yet")
    return ref.DEMO_CBOM.read_text()


@pytest.fixture(scope="module")
def doc(text) -> dict:
    return json.loads(text)


def _official_errors(payload: str):
    from cyclonedx.schema import SchemaVersion
    from cyclonedx.validation.json import JsonStrictValidator

    return JsonStrictValidator(SchemaVersion.V1_6).validate_str(payload)


def _our_models_reject(payload: str) -> bool:
    from quantum.risk.models import dump_cbom, parse_cbom

    try:
        dump_cbom(parse_cbom(payload))
    except Exception:
        return True
    return False


def test_cbom_validates_against_the_official_cyclonedx_1_6_strict_schema(text):
    assert _official_errors(text) is None


def test_cbom_round_trips_through_our_models_exactly(text):
    from quantum.risk.models import dump_cbom, parse_cbom

    assert json.loads(dump_cbom(parse_cbom(text))) == json.loads(text)


def test_cbom_dump_is_stable_second_round_trip_gives_the_same_text(text):
    from quantum.risk.models import dump_cbom, parse_cbom

    once = dump_cbom(parse_cbom(text))
    assert dump_cbom(parse_cbom(once)) == once


def test_cbom_has_35_to_50_cryptographic_assets_and_is_marked_fictional(doc):
    assets = [c for c in doc["components"] if c["type"] == "cryptographic-asset"]
    assert 35 <= len(assets) <= 50, len(assets)
    assert len(assets) == len(doc["components"]), "every component must be a cryptographic-asset"
    props = {p["name"]: p["value"] for p in doc["metadata"]["properties"]}
    assert props.get("qday:fictional") == "true"
    assert doc["specVersion"] == "1.6" and doc["bomFormat"] == "CycloneDX"


def test_cbom_bom_refs_are_unique(doc):
    refs = [c["bom-ref"] for c in doc["components"]]
    assert len(refs) == len(set(refs))


def test_cbom_every_component_carries_the_four_qday_properties_with_valid_values(doc):
    for c in doc["components"]:
        p = {x["name"]: x["value"] for x in c["properties"]}
        assert {
            "qday:shelf_life_years",
            "qday:migration_years",
            "qday:exposure",
            "qday:usage",
        } <= set(p), c["bom-ref"]
        for key in ("qday:shelf_life_years", "qday:migration_years"):
            assert re.fullmatch(r"\d+(\.\d+)?", p[key]), f"{c['bom-ref']}: {key}={p[key]!r}"
            assert float(p[key]) > 0, c["bom-ref"]
        assert p["qday:exposure"] in ref.EXPOSURES, c["bom-ref"]
        assert p["qday:usage"] in ref.USAGES, c["bom-ref"]


def test_cbom_mix_covers_every_family_usage_and_exposure(doc):
    from quantum.risk.mapping import family_of

    fams = {family_of(c["name"]) for c in doc["components"]}
    usage = {
        x["value"] for c in doc["components"] for x in c["properties"] if x["name"] == "qday:usage"
    }
    expo = {
        x["value"]
        for c in doc["components"]
        for x in c["properties"]
        if x["name"] == "qday:exposure"
    }
    assert fams == set(ref.FAMILIES), f"families {sorted(fams)}"
    assert usage == set(ref.USAGES) and expo == set(ref.EXPOSURES)
    pqc = [c for c in doc["components"] if family_of(c["name"]) in ("ML-KEM", "ML-DSA", "SLH-DSA")]
    aes = [c for c in doc["components"] if family_of(c["name"]) == "AES"]
    assert len(pqc) >= 3 and len(aes) >= 2


def test_cbom_does_not_name_a_real_company_or_carry_key_material(text):
    low = text.lower()
    assert "begin certificate" not in low and "begin private" not in low
    assert not re.search(r"[A-Za-z0-9+/]{60,}={0,2}", text), "long base64-like blob in the CBOM"


# ------------------------------------------------------------------ broken CBOMs must fail
def _mut(doc, fn):
    d = copy.deepcopy(doc)
    fn(d)
    return json.dumps(d)


BROKEN = {
    "missing bomFormat": lambda d: d.pop("bomFormat"),
    "wrong specVersion": lambda d: d.__setitem__("specVersion", "1.2"),
    "components not a list": lambda d: d.__setitem__("components", {"a": 1}),
    "component type unknown": lambda d: d["components"][0].__setitem__("type", "crypto-thing"),
    "assetType unknown": lambda d: d["components"][0]["cryptoProperties"].__setitem__(
        "assetType", "spell"
    ),
    "primitive unknown": lambda d: d["components"][0]["cryptoProperties"][
        "algorithmProperties"
    ].__setitem__("primitive", "magic"),
    "property value not a string": lambda d: d["components"][0]["properties"][0].__setitem__(
        "value", 5
    ),
    "name missing": lambda d: d["components"][0].pop("name"),
    "serialNumber malformed": lambda d: d.__setitem__("serialNumber", "not-a-urn"),
}


@pytest.mark.parametrize("what", sorted(BROKEN))
def test_cbom_broken_input_is_rejected_by_the_schema_or_by_our_models(doc, what):
    bad = _mut(doc, BROKEN[what])
    assert _official_errors(bad) is not None or _our_models_reject(bad), what


@pytest.mark.parametrize("what", sorted(BROKEN))
def test_cbom_our_models_reject_what_the_official_schema_rejects(doc, what):
    """Our loader is what the risk engine uses, so it must not accept what the schema refuses."""
    bad = _mut(doc, BROKEN[what])
    if _official_errors(bad) is not None:
        assert _our_models_reject(bad), what


def test_cbom_an_unknown_extra_field_is_not_silently_dropped(doc):
    """The round trip must fail loudly instead of losing data."""
    bad = _mut(doc, lambda d: d["components"][0].__setitem__("surprise", 1))
    assert _our_models_reject(bad)


SEMANTIC = {
    "negative shelf life": ("qday:shelf_life_years", "-3"),
    "non numeric migration": ("qday:migration_years", "soon"),
    "unknown exposure": ("qday:exposure", "everywhere"),
    "unknown usage": ("qday:usage", "vibes"),
}


@pytest.mark.parametrize("what", sorted(SEMANTIC))
def test_cbom_a_semantically_wrong_property_is_rejected_by_the_loader(doc, what):
    """Schema-valid but meaningless values must not reach the Mosca arithmetic."""
    name, value = SEMANTIC[what]

    def f(d):
        for p in d["components"][0]["properties"]:
            if p["name"] == name:
                p["value"] = value

    assert _our_models_reject(_mut(doc, f)), what
