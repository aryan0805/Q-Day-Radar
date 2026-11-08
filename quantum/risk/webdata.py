"""Typed web data files (inventory, scenarios, scaling, lab, meta) and their JSON schemas.

web/public/data/<name>.json is validated against schema/<name>.schema.json, generated from the
pydantic models below. Everything is computed from result files; nothing is typed here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from quantum.backends import get_fake_backend
from quantum.estimate import common
from quantum.risk import allowlist, herodata, inventory
from quantum.risk.mapping import FAMILIES, TARGET_OF_FAMILY
from quantum.risk.timeline import SECONDS_PER_YEAR, crqc_year

ROOT = inventory.ROOT
EST = ROOT / "results" / "estimate"
HW_SUMMARY = ROOT / "results" / "analysis" / "phase2" / "summary-batch-20261108T044751Z.json"
HW_BATCH = ROOT / "results" / "hardware" / HW_SUMMARY.stem.removeprefix("summary-")
# NIST IR 8547 dates shown beside each other on the Inventory screen: literature ids only.
DEADLINE_IDS = {
    "federal_key_establishment": "nistir8547_federal_key_establishment_deadline",
    "federal_signature": "nistir8547_federal_signature_deadline",
    "deprecate_after": "nistir8547_deprecate_after",
    "disallow_after": "nistir8547_disallow_after",
}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioResult(_M):
    crqc_year: float | None
    crqc_basis: str | None
    margin_years: float | None
    shortfall: float
    rank: int


class Replacement(_M):
    algorithm: str
    standard_id: str


class Asset(_M):
    id: str
    name: str
    algorithm: str
    family: str
    usage: str
    attack_target: str | None
    mapping_note: str
    key_bits: int | None
    classically_deprecated: bool
    exposure: str
    exposure_weight: float
    shelf_life_years: float
    migration_years: float
    replacement: Replacement
    nist_deadline_year: int | None
    by_scenario: dict[str, ScenarioResult]


class Deadline(_M):
    key: str
    literature_id: str
    year: int
    scope: str


class Inventory(_M):
    as_of: str
    as_of_year: int
    scenarios: list[str]
    crqc_label: str
    deadlines: list[Deadline]
    summary: dict[str, Any]
    family_order: dict[str, list[str]]
    assets: list[Asset]


class ScenariosFile(_M):
    crqc_label: str
    scenario_notes: dict[str, str]
    order_notes: dict[str, str]
    model_only: dict[str, Any]
    gaps: dict[str, Any]
    scenarios: dict[str, Any]
    targets: dict[str, Any]
    timeline: dict[str, Any]


class ScalingFile(_M):
    fits: list[dict[str, Any]]


class Wilson(_M):
    lo: float
    hi: float


class HardwareEntry(_M):
    config: str
    shots_pooled: int
    success_probability: float
    wilson_95: list[float]
    normalized_score: float | None
    chance_baseline: float
    theoretical_success: float
    predicted_success: float | None
    predicted_vs_chance: str | None
    repeat_spread: float | None
    drift_beyond_shot_noise: bool | None
    m3_success_probability_mean: float | None


class LabCircuit(_M):
    name: str
    kind: str
    ideal: dict[str, Any]
    noisy: dict[str, Any]
    hardware: list[HardwareEntry]


class LabFile(_M):
    hardware_batch: str
    device: dict[str, Any]
    circuits: list[LabCircuit]


class HeroFile(_M):
    circuit: dict[str, Any]
    ideal: dict[str, Any]
    hardware: dict[str, Any]
    notes: dict[str, str]
    resolution: dict[str, Any] | None


class SourceFile(_M):
    path: str
    sha256: str


class Meta(_M):
    git_commit: str
    generated_at: str
    sources: list[SourceFile]


MODELS: dict[str, type[BaseModel]] = {
    "inventory": Inventory,
    "scenarios": ScenariosFile,
    "scaling": ScalingFile,
    "lab": LabFile,
    "hero": HeroFile,
    "meta": Meta,
}


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def device() -> dict:
    """The device the hardware batch ran on: its qubit count, from the snapshot we simulate with."""
    return {
        "name": herodata.DEVICE_NAME,
        "n_qubits": get_fake_backend().num_qubits,
        "source": herodata.DEVICE_QUBITS_SOURCE,
    }


def gaps(timeline: dict, dev: dict) -> dict:
    """Physical qubits each Shor attack needs, over the device's size and over the record chip."""
    record = timeline["baseline"]["qubits"]
    out: dict = {}
    for sc, body in timeline["scenarios"].items():
        out[sc] = {}
        for t in ("rsa2048", "ecc256"):
            p = body["targets"][t]["physical_qubits"]
            out[sc][t] = {
                "physical_qubits": p,
                "over_device": p / dev["n_qubits"],
                "over_record": p / record,
            }
    return out


def build_lab() -> dict:
    summary = _json(HW_SUMMARY)
    circuits = []
    for ideal_path in sorted((ROOT / "results" / "metrics").glob("*.json")):
        name = ideal_path.stem
        ideal = _json(ideal_path)
        noisy = _json(ROOT / "results" / "noisy" / f"{name}.json")
        hw = []
        for _key, e in sorted(summary["entries"].items()):
            if e["name"] == name:
                hw.append({k: e.get(k) for k in HardwareEntry.model_fields})
        circuits.append(
            {
                "name": name,
                "kind": noisy["kind"],
                "ideal": {
                    k: ideal[k]
                    for k in (
                        "success_probability",
                        "theoretical_success",
                        "chance_baseline",
                        "shots",
                        "seed_simulator",
                    )
                },
                "noisy": {
                    k: noisy[k]
                    for k in (
                        "noise_model",
                        "shots",
                        "seed_simulator",
                        "success_probability",
                        "wilson_95",
                        "theoretical_success",
                        "chance_baseline",
                        "normalized_score",
                        "hellinger_vs_ideal",
                        "signal",
                    )
                },
                "hardware": hw,
            }
        )
    return {
        "hardware_batch": HW_SUMMARY.stem.removeprefix("summary-"),
        "device": device(),
        "circuits": circuits,
    }


def source_files() -> list[Path]:
    files = [
        ROOT / "quantum" / "estimate" / "literature.yaml",
        inventory.CBOM_PATH,
        inventory.EXPOSURE_PATH,
        inventory.REPLACEMENTS_PATH,
        EST / "scenarios.json",
        EST / "scaling.json",
        inventory.TIMELINE_PATH,
        HW_SUMMARY,
        ROOT / "quantum" / "circuits" / "shor_textbook.py",
        HW_BATCH / "plan.json",
    ]
    files += sorted((HW_BATCH / "jobs").glob("*.json"))
    files += sorted((ROOT / "results" / "metrics").glob("*.json"))
    files += sorted((ROOT / "results" / "noisy").glob("*.json"))
    return files


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def scenario_notes(timeline: dict) -> dict[str, str]:
    """Say why a scenario has no finite margin, so a UI never shows 'nothing at risk' bare."""
    cap = timeline["runtime_cap_years"]
    notes = {}
    for sc, body in timeline["scenarios"].items():
        years = {t: r["runtime_seconds"] / SECONDS_PER_YEAR for t, r in body["targets"].items()}
        shor = {t: y for t, y in years.items() if t != "aes128"}
        over = [t for t, y in shor.items() if y > cap]
        if len(over) == len(shor):
            detail = ", ".join(f"{t} {y:.3g} y" for t, y in shor.items())
            notes[sc] = (
                f"Every Shor attack exceeds the {cap:g}-year runtime cap in this scenario "
                f"({detail}), so no asset has a finite Mosca margin here; that is a statement "
                "about the cap, not evidence that nothing is at risk."
            )
        else:
            notes[sc] = "At least one Shor attack fits inside the runtime cap."
    return notes


def _family_year(targets: dict, family: str) -> float:
    """CRQC year of the family's costed attack target; infinity when there is none or no year."""
    t = TARGET_OF_FAMILY[family]
    y = targets[t]["crqc_year"] if t else None
    return float("inf") if y is None else y


def _family_order(targets: dict) -> list[str]:
    return sorted(FAMILIES, key=lambda f: (_family_year(targets, f), f))


def order_notes(timeline: dict, est: dict, mo: dict) -> dict[str, str]:
    """Say what the family order rests on, from the data (no number is typed here).

    Compares the computed order with the model-only order, names the paper-fed targets and the
    ECC-256 logical source with its bound flag, and records the Phase 4 history as text.
    """
    src = est["targets"]["ecc256"]["logical_source"]
    ids = ", ".join(src["literature_ids"])
    bound = src.get("bound")
    notes = {}
    for sc, body in timeline["scenarios"].items():
        computed = _family_order(body["targets"])
        at_risk = [f for f in computed if _family_year(body["targets"], f) != float("inf")]
        alone = mo[sc]["family_order"]
        fed = [t for t, r in body["targets"].items() if r["physical_source"] != "model"]
        same = computed == alone
        relation = (
            "equals the order from the base cost model alone, so the paper feeds move the "
            "CRQC years but not the order"
            if same
            else "differs from the order from the base cost model alone, so the paper feeds "
            "change the order"
        )
        fed_text = (
            "Physical qubits come from a paper for " + ", ".join(fed) + "; "
            if fed
            else "No paper sets physical qubits here; "
        )
        bound_text = f" ({bound} bound)" if bound else ""
        notes[sc] = (
            f"The computed family order ({' > '.join(at_risk)}) {relation}. {fed_text}the "
            f"ECC-256 logical counts come from {ids}{bound_text}, so the order rests on that "
            "source."
        )
    return notes


def model_only(timeline: dict, est: dict) -> dict:
    """The family order from the Phase 3 model alone (no paper feed), next to the computed one.

    Same doubling time, baseline, runtime cap and CRQC formula as the timeline; only the physical
    qubits differ (the model's, not min(model, paper)).
    """
    base = timeline["baseline"]["qubits"]
    cap = timeline["runtime_cap_years"]
    out: dict = {}
    for sc, body in timeline["scenarios"].items():
        targets = {}
        for t in body["targets"]:
            m = est["targets"][t]["by_scenario"][sc]
            targets[t] = {
                "physical_qubits": float(m["physical_qubits"]),
                "runtime_seconds": float(m["runtime_seconds"]),
                "crqc_year": crqc_year(
                    float(m["physical_qubits"]),
                    float(m["runtime_seconds"]),
                    base,
                    body["doubling_years"],
                    timeline["as_of_year"],
                    cap,
                ),
            }
        out[sc] = {"targets": targets, "family_order": _family_order(targets)}
    return out


def summary(inv: dict) -> dict:
    """Per-scenario counts the Overview shows, so every figure on screen is a stored value."""
    out: dict = {}
    for sc in inv["scenarios"]:
        margins = [a["by_scenario"][sc]["margin_years"] for a in inv["assets"]]
        years = [
            a["by_scenario"][sc]["crqc_year"]
            for a in inv["assets"]
            if a["by_scenario"][sc]["crqc_basis"] == inventory.CRQC_LABEL
        ]
        out[sc] = {
            "assets_total": len(inv["assets"]),
            "with_finite_margin": sum(m is not None for m in margins),
            "exposed": sum(m is not None and m < 0 for m in margins),
            "classically_deprecated": sum(a["classically_deprecated"] for a in inv["assets"]),
            "soonest_crqc_year": min(years) if years else None,
        }
    return out


def deadlines() -> list[dict]:
    lit = common.literature()
    scopes = {
        "federal_key_establishment": "federal high value assets and high impact systems",
        "federal_signature": "federal high value assets and high impact systems",
        "deprecate_after": "NIST: quantum-vulnerable algorithms deprecated after this year",
        "disallow_after": "NIST: quantum-vulnerable algorithms disallowed after this year",
    }
    return [
        {
            "key": k,
            "literature_id": lid,
            "year": int(lit[lid]["value"]),
            "scope": scopes[k],
        }
        for k, lid in DEADLINE_IDS.items()
    ]


def _inventory_file(timeline: dict) -> dict:
    inv = inventory.build_inventory(inventory.load_cbom(), timeline)
    return {**inv, "deadlines": deadlines(), "summary": summary(inv)}


def build_all() -> dict[str, dict]:
    timeline = inventory.load_timeline()
    est = _json(EST / "scenarios.json")
    mo = model_only(timeline, est)
    data = {
        "inventory": _inventory_file(timeline),
        "scenarios": {
            "crqc_label": inventory.CRQC_LABEL,
            "scenario_notes": scenario_notes(timeline),
            "order_notes": order_notes(timeline, est, mo),
            "model_only": mo,
            "gaps": gaps(timeline, device()),
            "scenarios": est["scenarios"],
            "targets": est["targets"],
            "timeline": timeline,
        },
        "scaling": _json(EST / "scaling.json"),
        "lab": build_lab(),
        "hero": herodata.build_hero(HW_BATCH, device()["n_qubits"]),
    }
    data["meta"] = {
        "git_commit": _git_commit(),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [
            {
                "path": p.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in source_files()
        ],
    }
    for name, model in MODELS.items():
        model.model_validate(data[name])  # fail loudly if a file drifts from its model
        problems = allowlist.check(name, data[name])
        if problems:
            raise ValueError(f"{name}.json fails the allow-list: " + "; ".join(problems[:10]))
    return data


def schemas() -> dict[str, dict]:
    return {name: model.model_json_schema() for name, model in MODELS.items()}
