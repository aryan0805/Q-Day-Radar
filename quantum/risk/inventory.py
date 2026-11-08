"""CBOM + timeline -> per-asset Mosca margins, shortfalls, ranks, replacements, family order."""

from __future__ import annotations

import json
import math
from pathlib import Path

import yaml

from quantum.estimate import common
from quantum.risk import mosca
from quantum.risk.mapping import FAMILIES, TARGET_OF_FAMILY, classify
from quantum.risk.models import Cbom, parse_cbom

ROOT = Path(__file__).resolve().parents[2]
CBOM_PATH = ROOT / "quantum" / "risk" / "data" / "demo_cbom.cdx.json"
EXPOSURE_PATH = ROOT / "quantum" / "risk" / "exposure.yaml"
REPLACEMENTS_PATH = ROOT / "quantum" / "risk" / "replacements.yaml"
CRQC_LABEL = "trend extrapolation"
CRQC_BASIS_DEPRECATED = "classically deprecated (SP 800-131A), not a quantum estimate"
TIMELINE_PATH = ROOT / "results" / "risk" / "timeline.json"


def load_cbom() -> Cbom:
    return parse_cbom(CBOM_PATH.read_text())


def _replacement_rules() -> dict[tuple[str, str], dict]:
    rules = yaml.safe_load(REPLACEMENTS_PATH.read_text())["rules"]
    return {(r["family"], r["usage"]): r for r in rules}


def build_inventory(cbom: Cbom, timeline: dict) -> dict:
    weights = yaml.safe_load(EXPOSURE_PATH.read_text())["weights"]
    rules = _replacement_rules()
    lit = common.literature()
    as_of_year = timeline["as_of_year"]
    scenarios = list(timeline["scenarios"])
    assets = []
    for comp in cbom.components:
        cls = classify(comp)
        shelf, mig, exposure, usage = comp.risk_inputs()
        rule = rules.get((cls.family, usage))
        if rule is None:
            raise ValueError(
                f"{comp.bom_ref}: no replacement rule for family {cls.family!r} with usage "
                f"{usage!r} in quantum/risk/replacements.yaml"
            )
        deadline_id = rule["nist_deadline_id"]
        assets.append(
            {
                "id": comp.bom_ref,
                "name": comp.description or comp.name,
                "algorithm": comp.name,
                "family": cls.family,
                "usage": usage,
                "attack_target": cls.attack_target,
                "mapping_note": cls.mapping_note,
                "key_bits": cls.key_bits,
                "classically_deprecated": cls.classically_deprecated,
                "exposure": exposure,
                "exposure_weight": float(weights[exposure]),
                "shelf_life_years": shelf,
                "migration_years": mig,
                "replacement": {
                    "algorithm": rule["replacement"],
                    "standard_id": rule["standard_id"],
                },
                "nist_deadline_year": int(lit[deadline_id]["value"]) if deadline_id else None,
                "by_scenario": {},
            }
        )
    family_order = {}
    for sc in scenarios:
        targets = timeline["scenarios"][sc]["targets"]
        scored = []
        crqc_of: dict[str, float | None] = {}
        for a in assets:
            if a["classically_deprecated"]:
                crqc, basis = as_of_year, CRQC_BASIS_DEPRECATED
            else:
                crqc = targets[a["attack_target"]]["crqc_year"] if a["attack_target"] else None
                basis = CRQC_LABEL if crqc is not None else None
            m = mosca.margin(crqc, as_of_year, a["shelf_life_years"], a["migration_years"])
            s = mosca.shortfall(a["exposure_weight"], m)
            crqc_of[a["id"]] = crqc
            a["by_scenario"][sc] = {
                "crqc_year": crqc,
                "crqc_basis": basis,
                "margin_years": m,
                "shortfall": s,
            }
            scored.append(mosca.Scored(a["id"], m, s))
        ranks = mosca.rank(scored)
        for a in assets:
            a["by_scenario"][sc]["rank"] = ranks[a["id"]]

        def family_year(f: str, targets: dict = targets) -> float:
            t = TARGET_OF_FAMILY[f]
            y = targets[t]["crqc_year"] if t else None
            return math.inf if y is None else y

        family_order[sc] = sorted(FAMILIES, key=lambda f: (family_year(f), f))
    return {
        "as_of": timeline["as_of"],
        "as_of_year": as_of_year,
        "scenarios": scenarios,
        "crqc_label": CRQC_LABEL,
        "family_order": family_order,
        "assets": assets,
    }


def load_timeline() -> dict:
    return json.loads(TIMELINE_PATH.read_text())
