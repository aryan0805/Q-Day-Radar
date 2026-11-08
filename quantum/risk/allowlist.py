"""Explicit allow-list for web/public/data/*.json (task 6, security).

A key may appear in a web data file only if it is named here. A new field therefore needs a
deliberate edit of this file (reviewed), not just a change in a builder. Values are scanned too:
no local path, no credential-shaped string, no instance CRN. Keys whose names suggest a secret are
refused even if someone adds them to a set by mistake.
"""

from __future__ import annotations

import re
from typing import Any

# Keys that are data, not field names: scenario names, attack targets and measured bitstrings.
DATA_KEYS = frozenset({"median", "optimistic", "pessimistic", "rsa2048", "ecc256", "aes128"})
_BITSTRING = re.compile(r"[01]+")

FORBIDDEN_NAME_PARTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "apikey",
    "api_key",
    "credential",
    "crn",
    "instance",
    "bearer",
    "private",
    "bypass",
    "authorization",
    "cookie",
    "session",
)

# Value patterns that must never appear in any string.
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"/Users/|/home/|[A-Za-z]:\\"),  # local paths
    re.compile(r"crn:v\d:"),  # IBM Cloud resource names
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[:=]"),
    re.compile(r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),  # JWT
)

ALLOWED: dict[str, frozenset[str]] = {
    "inventory": frozenset(
        {
            "summary",
            "assets_total",
            "with_finite_margin",
            "exposed",
            "soonest_crqc_year",
            "algorithm",
            "as_of",
            "as_of_year",
            "assets",
            "attack_target",
            "by_scenario",
            "classically_deprecated",
            "crqc_basis",
            "crqc_label",
            "crqc_year",
            "deadlines",
            "exposure",
            "exposure_weight",
            "family",
            "family_order",
            "id",
            "key",
            "key_bits",
            "literature_id",
            "mapping_note",
            "margin_years",
            "migration_years",
            "name",
            "nist_deadline_year",
            "rank",
            "replacement",
            "scenarios",
            "scope",
            "shelf_life_years",
            "shortfall",
            "standard_id",
            "usage",
            "year",
        }
    ),
    "scenarios": frozenset(
        {
            "gaps",
            "over_device",
            "over_record",
            "actual",
            "as_of",
            "as_of_year",
            "baseline",
            "bound",
            "by_scenario",
            "ccixCount",
            "cczCount",
            "ci95",
            "code_distance",
            "context",
            "crqc_label",
            "crqc_year",
            "cycle_time_seconds",
            "delta_years",
            "doubling_years",
            "error_budget",
            "family_order",
            "feasible",
            "fit",
            "frontier",
            "gate_error_rate",
            "history",
            "holdout",
            "inclusion_rule",
            "instruction_set",
            "intercept",
            "label",
            "literature_id",
            "literature_ids",
            "logical_counts",
            "logical_qubits",
            "logical_source",
            "measurementCount",
            "measurement_count_assumption",
            "measurement_error_rate",
            "model_only",
            "model_year",
            "name",
            "note",
            "numQubits",
            "order_notes",
            "peel_last_sbox",
            "physical_bound",
            "physical_error_rate",
            "physical_qubits",
            "physical_source",
            "points",
            "predicted",
            "qec_scheme",
            "qubit_params",
            "qubits",
            "r2",
            "rel",
            "rel_error",
            "repetitions",
            "residuals",
            "rotationCount",
            "rotationDepth",
            "runtime_cap_years",
            "runtime_seconds",
            "runtime_source",
            "scenario_notes",
            "scenarios",
            "sensitivity_raw_series",
            "signed_rel_error",
            "slope",
            "source",
            "source_ids",
            "superseded_by",
            "survey_check",
            "survey_year",
            "tCount",
            "targets",
            "timeline",
            "toffoli_count",
            "year",
        }
    ),
    "scaling": frozenset(
        {
            "N",
            "actual",
            "bases",
            "c",
            "caveat",
            "coeffs",
            "eps",
            "eps_consistent_rotation_t_cost",
            "eps_consistent_value",
            "error_budget",
            "estimator",
            "exponent",
            "extrapolated",
            "extrapolated_budget_eps",
            "extrapolated_range",
            "extrapolation_caveat",
            "fits",
            "high",
            "holdout",
            "intercept",
            "last_slope_continuation",
            "low",
            "model",
            "n_bits",
            "non_rotation_toffoli_equiv",
            "params",
            "points",
            "predicted",
            "quantity",
            "r2",
            "rel",
            "rel_error",
            "residuals",
            "rotation_count",
            "rotation_t_cost",
            "selected",
            "slope",
            "spread",
            "value",
        }
    ),
    "lab": frozenset(
        {
            "device",
            "n_qubits",
            "source",
            "chance_baseline",
            "circuits",
            "config",
            "drift_beyond_shot_noise",
            "hardware",
            "hardware_batch",
            "hellinger_vs_ideal",
            "ideal",
            "kind",
            "m3_success_probability_mean",
            "name",
            "noise_model",
            "noisy",
            "normalized_score",
            "predicted_success",
            "predicted_vs_chance",
            "repeat_spread",
            "seed_simulator",
            "shots",
            "shots_pooled",
            "signal",
            "success_probability",
            "theoretical_success",
            "wilson_95",
        }
    ),
    "hero": frozenset(
        {
            "a",
            "backend",
            "batch",
            "bitstring",
            "circuit",
            "clbits",
            "config",
            "convergents",
            "count",
            "counts",
            "denominator",
            "device_qubits",
            "device_qubits_source",
            "factors",
            "finished",
            "gates",
            "hardware",
            "ideal",
            "index",
            "isa_sha256",
            "notes",
            "compiled",
            "success",
            "job_id",
            "jobs",
            "kind",
            "layer",
            "measured",
            "method",
            "n",
            "n_clbits",
            "n_count",
            "n_qubits",
            "name",
            "op",
            "order",
            "pooled_raw_counts",
            "probabilities",
            "qubits",
            "registers",
            "resolution",
            "shots",
            "size",
            "status",
        }
    ),
    "meta": frozenset(
        {
            "generated_at",
            "git_commit",
            "path",
            "sha256",
            "sources",
        }
    ),
}


def _walk(name: str, obj: Any, path: str, out: list[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            if not (k in DATA_KEYS or _BITSTRING.fullmatch(k) or k in ALLOWED[name]):
                out.append(f"key not on the allow-list: {here}")
            low = k.lower()
            if k not in DATA_KEYS and any(part in low for part in FORBIDDEN_NAME_PARTS):
                out.append(f"secret-looking key name: {here}")
            _walk(name, v, here, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk(name, v, f"{path}[{i}]", out)
    elif isinstance(obj, str):
        for pat in FORBIDDEN_VALUE_PATTERNS:
            if pat.search(obj):
                out.append(f"forbidden value at {path}: matches {pat.pattern}")


def check(name: str, obj: Any) -> list[str]:
    """Return a list of problems (empty = clean) for one data file's content."""
    if name not in ALLOWED:
        return [f"no allow-list for {name}"]
    out: list[str] = []
    _walk(name, obj, "", out)
    return out
