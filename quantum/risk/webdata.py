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

from quantum.risk import inventory
from quantum.risk.timeline import SECONDS_PER_YEAR

ROOT = inventory.ROOT
EST = ROOT / "results" / "estimate"
HW_SUMMARY = ROOT / "results" / "analysis" / "phase2" / "summary-batch-20261108T044751Z.json"


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


class Inventory(_M):
    as_of: str
    as_of_year: int
    scenarios: list[str]
    crqc_label: str
    family_order: dict[str, list[str]]
    assets: list[Asset]


class ScenariosFile(_M):
    crqc_label: str
    scenario_notes: dict[str, str]
    order_notes: dict[str, str]
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
    circuits: list[LabCircuit]


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
    "meta": Meta,
}


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


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
    return {"hardware_batch": HW_SUMMARY.stem.removeprefix("summary-"), "circuits": circuits}


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
    ]
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


def order_notes(timeline: dict) -> dict[str, str]:
    """Say when a scenario's family order rests on a paper's upper bound (a preprint)."""
    notes = {}
    for sc, body in timeline["scenarios"].items():
        rests = [
            f"{t} ({r['physical_source']})"
            for t, r in body["targets"].items()
            if r.get("physical_bound") == "upper"
        ]
        notes[sc] = (
            "The family order here depends on an upper bound on physical qubits from a preprint: "
            + ", ".join(rests)
            + ". A different published figure could change the order."
            if rests
            else "The family order here rests on the Phase 3 model and on peer-reviewed or "
            "labelled paper figures only."
        )
    return notes


def build_all() -> dict[str, dict]:
    timeline = inventory.load_timeline()
    est = _json(EST / "scenarios.json")
    data = {
        "inventory": inventory.build_inventory(inventory.load_cbom(), timeline),
        "scenarios": {
            "crqc_label": inventory.CRQC_LABEL,
            "scenario_notes": scenario_notes(timeline),
            "order_notes": order_notes(timeline),
            "scenarios": est["scenarios"],
            "targets": est["targets"],
            "timeline": timeline,
        },
        "scaling": _json(EST / "scaling.json"),
        "lab": build_lab(),
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
    return data


def schemas() -> dict[str, dict]:
    return {name: model.model_json_schema() for name, model in MODELS.items()}
