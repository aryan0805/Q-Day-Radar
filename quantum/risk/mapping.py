"""CBOM component -> family, attack target and mapping note (conservative = earlier threat).

Mapping (fixed in the Phase 4 brief): RSA-any -> rsa2048; ECDSA/ECDH/EdDSA/X25519 on any curve of
at most 521 bits -> ecc256; AES-any and SHA-2/3 -> aes128 (Grover); ML-KEM, ML-DSA, SLH-DSA -> None.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from quantum.risk.models import Component

FAMILIES = ("RSA", "ECC", "AES", "SHA", "ML-KEM", "ML-DSA", "SLH-DSA")
TARGET_OF_FAMILY = {
    "RSA": "rsa2048",
    "ECC": "ecc256",
    "AES": "aes128",
    "SHA": "aes128",
    "ML-KEM": None,
    "ML-DSA": None,
    "SLH-DSA": None,
}
_CURVE_BITS = {
    "p-256": 256,
    "p-384": 384,
    "p-521": 521,
    "secp256k1": 256,
    "x25519": 255,
    "ed25519": 255,
    "x448": 448,
    "ed448": 448,
}


@dataclass(frozen=True)
class Classification:
    family: str
    attack_target: str | None
    mapping_note: str
    key_bits: int | None
    classically_deprecated: bool = False


def family_of(name: str) -> str:
    n = name.upper()
    if n.startswith("ML-KEM"):
        return "ML-KEM"
    if n.startswith("ML-DSA"):
        return "ML-DSA"
    if n.startswith("SLH-DSA"):
        return "SLH-DSA"
    if n.startswith("RSA"):
        return "RSA"
    if n.startswith(("ECDSA", "ECDH", "ED25519", "ED448", "X25519", "X448", "EDDSA")):
        return "ECC"
    if n.startswith("AES"):
        return "AES"
    if "SHA" in n:  # SHA-1/2/3 and HMAC-SHA-*
        return "SHA"
    raise ValueError(f"no family for {name!r}")


def _curve_bits(component: Component) -> int | None:
    """Field size in bits from the CBOM curve (or the algorithm name), e.g. nist/P-192 -> 192."""
    curve = component.crypto_properties.algorithm_properties.curve
    for raw in (curve.split("/")[-1] if curve else None, component.name):
        if not raw:
            continue
        key = raw.lower()
        if key in _CURVE_BITS:
            return _CURVE_BITS[key]
        m = re.search(r"(?:p-?|secp|prime|brainpoolp|sect)(\d{3})", key)
        if m:
            return int(m.group(1))
    return None


def _rsa_bits(component: Component) -> int | None:
    pset = component.crypto_properties.algorithm_properties.parameter_set_identifier
    m = re.search(r"(\d{3,5})", pset or component.name)
    return int(m.group(1)) if m else None


def algorithm_is_sha1(name: str) -> bool:
    return name == "SHA-1"


def is_classically_deprecated(
    family: str, algorithm: str, key_bits: int | None, usage: str | None = None
) -> bool:
    """SP 800-131A (literature id sp800_131a): below 112 bits of classical security.

    RSA modulus < 2048, ECC key size < 224 (112-bit strength is about half the key size), SHA-1.
    """
    if algorithm_is_sha1(algorithm):
        # plain SHA-1 only where collisions matter; HMAC/KDF uses stay acceptable (SP 800-131A)
        return usage in ("signature", "hash")
    if key_bits is None:
        return False
    return (family == "RSA" and key_bits < 2048) or (family == "ECC" and key_bits < 224)


def _param_bits(component: Component) -> int | None:
    pset = component.crypto_properties.algorithm_properties.parameter_set_identifier
    m = re.search(r"(\d{2,5})", pset or "")
    return int(m.group(1)) if m else None


def classify(component: Component) -> Classification:
    family = family_of(component.name)
    target = TARGET_OF_FAMILY[family]
    if family == "RSA":
        bits = _rsa_bits(component)
    elif family == "ECC":
        bits = _curve_bits(component)
        if bits is None or bits > 521:
            raise ValueError(f"{component.name}: curve not in the mapped range")
    elif family in ("AES", "SHA"):
        bits = _param_bits(component)
    else:
        bits = None
    deprecated = is_classically_deprecated(
        family, component.name, bits, component.prop("qday:usage")
    )
    if deprecated and algorithm_is_sha1(component.name):
        note = (
            "SHA-1 in a signature or hash use: collision security is at most 80 bits "
            "(sp800_57_pt1r5_sha1_collision) and NIST SP 800-131A (sp800_131a) disallows it for "
            "signature generation. Treated as breakable now, so crqc_year = as_of_year (a "
            "classical reason). HMAC or key-derivation uses of SHA-1 are not flagged."
        )
    elif deprecated:
        note = (
            f"{component.name} gives less than 112 bits of classical security and is disallowed by "
            "NIST SP 800-131A (literature id sp800_131a): treated as breakable now, so "
            "crqc_year = as_of_year (a classical reason, not a quantum one)."
        )
    elif family == "RSA":
        if bits is not None and bits > 2048:
            note = (
                f"RSA-{bits} inherits the rsa2048 cost: a lower bound on attacker cost "
                "(the real attack is costlier, so the true threat is later)."
            )
        else:
            note = "RSA-2048 is the rsa2048 target."
    elif family == "ECC":
        note = (
            f"{bits}-bit curve inherits the ecc256 cost: a lower bound on attacker cost."
            if bits > 256
            else "Curve of about 256 bits is the ecc256 target."
        )
    elif family in ("AES", "SHA"):
        note = (
            "Grover on a symmetric primitive: mapped to the aes128 target (AES-256 and SHA-3 "
            "are costlier, so this is a lower bound)."
        )
    else:
        note = "Post-quantum standard: no known quantum attack target."
    return Classification(family, target, note, bits, deprecated)
