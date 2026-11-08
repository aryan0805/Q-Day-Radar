"""Classical deprecation (SP 800-131A: below 112 bits of security): the mapping's classify().

Lead (2026-11-08): RSA < 2048, ECC < 224 bits and SHA-1 are reachable NOW (crqc_year = as_of);
X25519 (255 bits) is not deprecated. The checks here call classify() on synthetic components so
that every branch of the rule is exercised, including key sizes the demo CBOM does not contain.
"""

from __future__ import annotations

import pytest

from quantum.risk.mapping import classify
from quantum.risk.models import Component


def _comp(name, param=None, curve=None, primitive="signature", usage=None):
    props = {"primitive": primitive}
    if param:
        props["parameterSetIdentifier"] = param
    if curve:
        props["curve"] = curve
    return Component.model_validate(
        {
            "type": "cryptographic-asset",
            "bom-ref": "x",
            "name": name,
            "cryptoProperties": {"assetType": "algorithm", "algorithmProperties": props},
            "properties": [{"name": "qday:usage", "value": usage}] if usage else [],
        }
    )


@pytest.mark.parametrize(
    ("name", "param", "bits", "deprecated"),
    [
        ("RSA-512", "512", 512, True),
        ("RSA-1024", "1024", 1024, True),
        ("RSA-1536", "1536", 1536, True),
        ("RSA-2047", "2047", 2047, True),
        ("RSA-2048", "2048", 2048, False),
        ("RSA-3072", "3072", 3072, False),
        ("RSA-4096", "4096", 4096, False),
    ],
)
def test_mosca_rsa_is_deprecated_exactly_below_2048_bits(name, param, bits, deprecated):
    c = classify(_comp(name, param=param))
    assert c.key_bits == bits and c.classically_deprecated is deprecated, name
    assert c.attack_target == "rsa2048"  # the quantum target is unchanged by the classical flag


@pytest.mark.parametrize(
    ("curve", "bits", "deprecated"),
    [
        ("nist/P-256", 256, False),
        ("nist/P-384", 384, False),
        ("nist/P-521", 521, False),
        ("secp256k1", 256, False),
        ("x25519", 255, False),
        ("ed25519", 255, False),
    ],
)
def test_mosca_ecc_curves_of_at_least_224_bits_are_not_deprecated(curve, bits, deprecated):
    name = {"x25519": "X25519", "ed25519": "Ed25519"}.get(curve, "ECDSA")
    c = classify(_comp(name, curve=curve))
    assert c.key_bits == bits and c.classically_deprecated is deprecated, curve
    assert c.attack_target == "ecc256"


@pytest.mark.parametrize("curve", ["nist/P-192", "secp192r1", "secp160r1", "secp192k1"])
def test_mosca_ecc_curve_below_224_bits_is_classified_deprecated_not_refused(curve):
    """A 192-bit curve is a valid curve of at most 521 bits (brief) and below 112 bits of
    strength; the engine must flag it as reachable now rather than crash on an unknown curve."""
    c = classify(_comp("ECDSA", curve=curve))
    assert c.classically_deprecated is True, curve
    assert c.key_bits is not None and c.key_bits < 224
    assert c.attack_target == "ecc256"


@pytest.mark.parametrize(
    ("name", "param", "deprecated"),
    [
        ("SHA-1", "160", True),
        ("SHA-256", "256", False),
        ("SHA-384", "384", False),
        ("SHA3-256", "256", False),
        ("HMAC-SHA-256", "256", False),
    ],
)
def test_mosca_only_sha_1_is_deprecated_among_the_hashes(name, param, deprecated):
    c = classify(_comp(name, param=param, primitive="hash", usage="hash"))
    assert c.classically_deprecated is deprecated, name
    assert c.family == "SHA"


@pytest.mark.parametrize(
    "name", ["AES-128-GCM", "AES-256-GCM", "ML-KEM-768", "ML-DSA-65", "SLH-DSA-SHA2-128s"]
)
def test_mosca_symmetric_and_post_quantum_algorithms_are_never_classically_deprecated(name):
    param = "128" if "128" in name else ("256" if "256" in name else None)
    c = classify(_comp(name, param=param, primitive="block-cipher"))
    assert c.classically_deprecated is False, name


def test_mosca_the_deprecation_note_says_it_is_classical_not_quantum():
    c = classify(_comp("RSA-1024", param="1024"))
    note = c.mapping_note.lower()
    assert "classical" in note and "sp 800-131a" in note


@pytest.mark.parametrize(
    ("usage", "deprecated"),
    [("signature", True), ("hash", True), ("encryption", False), ("key_exchange", False)],
)
def test_mosca_plain_sha_1_is_deprecated_only_in_signature_or_hash_use(usage, deprecated):
    """Lead (option a): collision resistance matters for signing and hashing, not for the others."""
    c = classify(_comp("SHA-1", param="160", primitive="hash", usage=usage))
    assert c.classically_deprecated is deprecated, usage


@pytest.mark.parametrize("usage", ["signature", "hash", "encryption", "key_exchange"])
def test_mosca_hmac_sha_1_is_never_deprecated(usage):
    c = classify(_comp("HMAC-SHA-1", param="160", primitive="mac", usage=usage))
    assert c.classically_deprecated is False, usage
    assert c.family == "SHA"
