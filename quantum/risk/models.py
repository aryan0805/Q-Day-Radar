"""Pydantic models for the CycloneDX 1.6 subset Q-Day Radar reads, plus parse/dump.

Only what a cryptographic-asset BOM needs here: BOM header, metadata properties, and components of
type cryptographic-asset with algorithm properties. Unknown fields are rejected (extra="forbid"),
so parse_cbom -> dump_cbom is an exact JSON round trip or it fails loudly.
"""

from __future__ import annotations

import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

USAGES = ("key_exchange", "encryption", "signature", "hash")
EXPOSURES = ("internet", "partner", "internal")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Property(_Model):
    name: str
    value: str


class AlgorithmProperties(_Model):
    primitive: Literal[
        "drbg",
        "mac",
        "block-cipher",
        "stream-cipher",
        "signature",
        "hash",
        "pke",
        "xof",
        "kdf",
        "key-agree",
        "kem",
        "ae",
        "combiner",
        "other",
        "unknown",
    ]
    parameter_set_identifier: str | None = Field(default=None, alias="parameterSetIdentifier")
    curve: str | None = None
    mode: str | None = None
    padding: str | None = None
    crypto_functions: list[str] | None = Field(default=None, alias="cryptoFunctions")
    classical_security_level: int | None = Field(default=None, alias="classicalSecurityLevel")
    nist_quantum_security_level: int | None = Field(default=None, alias="nistQuantumSecurityLevel")


class CryptoProperties(_Model):
    asset_type: Literal["algorithm"] = Field(alias="assetType")
    algorithm_properties: AlgorithmProperties = Field(alias="algorithmProperties")


class Component(_Model):
    type: Literal["cryptographic-asset"]
    bom_ref: str = Field(alias="bom-ref")
    name: str
    description: str | None = None
    crypto_properties: CryptoProperties = Field(alias="cryptoProperties")
    properties: list[Property] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_qday_properties(self) -> Component:
        """Reject meaningless qday inputs before any Mosca arithmetic (error names the asset)."""
        for name in ("qday:shelf_life_years", "qday:migration_years"):
            value = self.prop(name)
            if value is None:
                continue
            try:
                years = float(value)
            except ValueError:
                raise ValueError(f"{self.bom_ref}: {name} = {value!r} is not a number") from None
            if not math.isfinite(years) or years < 0:
                raise ValueError(f"{self.bom_ref}: {name} = {value!r} must be a finite number >= 0")
        for name, allowed in (("qday:exposure", EXPOSURES), ("qday:usage", USAGES)):
            value = self.prop(name)
            if value is not None and value not in allowed:
                raise ValueError(f"{self.bom_ref}: {name} = {value!r} not in {allowed}")
        return self

    def risk_inputs(self) -> tuple[float, float, str, str]:
        """(shelf_life_years, migration_years, exposure, usage); all four must be present."""
        names = ("qday:shelf_life_years", "qday:migration_years", "qday:exposure", "qday:usage")
        missing = [n for n in names if self.prop(n) is None]
        if missing:
            raise ValueError(f"{self.bom_ref}: missing {missing}")
        return (
            float(self.prop(names[0])),
            float(self.prop(names[1])),
            str(self.prop(names[2])),
            str(self.prop(names[3])),
        )

    def prop(self, name: str) -> str | None:
        for p in self.properties:
            if p.name == name:
                return p.value
        return None


class Metadata(_Model):
    timestamp: str | None = None
    properties: list[Property] = Field(default_factory=list)


class Cbom(_Model):
    bom_format: Literal["CycloneDX"] = Field(alias="bomFormat")
    spec_version: Literal["1.6"] = Field(alias="specVersion")
    serial_number: str = Field(
        alias="serialNumber",
        pattern=r"^urn:uuid:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    )
    version: int
    metadata: Metadata
    components: list[Component]

    def is_fictional(self) -> bool:
        return any(
            p.name == "qday:fictional" and p.value == "true" for p in self.metadata.properties
        )


def parse_cbom(text: str) -> Cbom:
    return Cbom.model_validate_json(text)


def dump_cbom(model: Cbom) -> str:
    return json.dumps(model.model_dump(by_alias=True, exclude_none=True), indent=2) + "\n"
