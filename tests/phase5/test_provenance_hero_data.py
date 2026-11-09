"""Provenance of the hero's data (lead's item 3, task 6): hero.json against the sources it claims.

Every figure the hero will show comes from hero.json, so this checks hero.json against (a) the
circuit registry (kind), (b) the immutable raw job files in results/hardware (id, counts, shots,
backend, status, and that the job ran THIS circuit), and (c) an independent recomputation of the
Shor answer (order, factors, ideal peaks), so a wrong figure in the file cannot hide behind a
matching wrong figure in the page.
"""

from __future__ import annotations

import json
from collections import Counter
from fractions import Fraction
from math import gcd
from pathlib import Path

import pytest

from quantum.circuits.registry import build_circuit

from .helpers import REPO, load_data

HERO = load_data("hero")
CIRCUIT = HERO["circuit"]
BATCH = REPO / "results" / "hardware" / HERO["hardware"]["batch"]


def _job_file(index: int) -> dict:
    return json.loads((BATCH / "jobs" / f"{index}.json").read_text())


# ------------------------------------------------------------------ the circuit and its label


def test_hero_circuit_kind_name_and_size_equal_the_registry() -> None:
    qc = build_circuit(CIRCUIT["name"])
    assert CIRCUIT["kind"] == qc.metadata["kind"] == "compiled"
    assert CIRCUIT["name"] == qc.metadata["name"]
    assert CIRCUIT["n_qubits"] == qc.num_qubits
    assert CIRCUIT["n_clbits"] == qc.num_clbits


def test_hero_notes_say_compiled_and_not_generic() -> None:
    # the label drives the on-page caption: a compiled circuit is never presented as generic Shor
    note = HERO["notes"]["compiled"]
    assert "compiled" in note and "generic" in note and "not generic" in note.replace("  ", " ")
    assert HERO["notes"]["hardware"].startswith(HERO["hardware"]["backend"])


def test_hero_gate_list_is_the_circuit_instruction_for_instruction() -> None:
    qc = build_circuit(CIRCUIT["name"])
    expected = [
        {
            "op": inst.operation.name,
            "qubits": [qc.find_bit(q).index for q in inst.qubits],
            "clbits": [qc.find_bit(c).index for c in inst.clbits],
        }
        for inst in qc.data
    ]
    shown = [{k: g[k] for k in ("op", "qubits", "clbits")} for g in CIRCUIT["gates"]]
    assert shown == expected, "the gate list drawn on screen is not the circuit"
    layers = [g["layer"] for g in CIRCUIT["gates"]]
    assert min(layers) >= 0 and all(isinstance(x, int) for x in layers)


# ------------------------------------------------------------------------------- hardware jobs


def test_hero_every_hardware_job_matches_its_raw_result_file() -> None:
    jobs = HERO["hardware"]["jobs"]
    assert len(jobs) >= 1
    for j in jobs:
        raw = _job_file(j["index"])
        assert raw["job_id"] == j["job_id"], j["index"]
        assert raw["name"] == CIRCUIT["name"], "job ran a different circuit"
        assert raw["backend"] == HERO["hardware"]["backend"]
        assert raw["status"] == j["status"] == "DONE"
        assert raw["config"] == j["config"]
        assert int(raw["shots"]) == j["shots"] == sum(j["counts"].values())
        assert {k: int(v) for k, v in raw["counts"].items()} == j["counts"]
        assert raw["finished"] == j["finished"]


def test_hero_no_job_id_is_repeated_and_all_are_from_one_batch() -> None:
    ids = [j["job_id"] for j in HERO["hardware"]["jobs"]]
    assert len(ids) == len(set(ids))
    submitted = (BATCH / "submitted.jsonl").read_text()
    assert all(i in submitted for i in ids), "a job id is not in the batch's submission log"


def test_hero_pooled_counts_are_the_sum_of_the_raw_config_jobs() -> None:
    pooled: Counter[str] = Counter()
    for j in HERO["hardware"]["jobs"]:
        if j["config"] == "raw":
            pooled.update(_job_file(j["index"])["counts"])
    assert dict(pooled) == HERO["hardware"]["pooled_raw_counts"]
    assert sum(pooled.values()) == sum(
        j["shots"] for j in HERO["hardware"]["jobs"] if j["config"] == "raw"
    )


def test_hero_device_size_comes_from_the_snapshot_not_a_typed_number() -> None:
    lab = load_data("lab")
    assert HERO["hardware"]["device_qubits"] == lab["device"]["n_qubits"]


# ----------------------------------------------------------- the Shor answer, recomputed here


def _order(a: int, n: int) -> int:
    return next(r for r in range(1, n) if pow(a, r, n) == 1)


def test_hero_resolution_is_the_continued_fraction_answer() -> None:
    r = HERO["resolution"]
    n, a = r["n"], r["a"]
    width = CIRCUIT["n_clbits"]
    measured = int(r["bitstring"], 2)
    assert measured == r["measured"] and r["denominator"] == 2**width
    # period from the measured phase, computed here and not read from the file
    frac = Fraction(measured, 2**width).limit_denominator(n)
    order = frac.denominator
    assert order == r["order"] == _order(a, n) == 4
    assert pow(a, order, n) == 1 and all(pow(a, k, n) != 1 for k in range(1, order))
    p, q = sorted({gcd(pow(a, order // 2, n) - 1, n), gcd(pow(a, order // 2, n) + 1, n)})
    assert [p, q] == sorted(r["factors"]) and p * q == n
    assert r["convergents"][-1] == [frac.numerator, frac.denominator]


def test_hero_the_resolved_bitstring_count_is_its_measured_count() -> None:
    r = HERO["resolution"]
    assert HERO["hardware"]["pooled_raw_counts"][r["bitstring"]] == r["count"]


def test_hero_ideal_distribution_has_exactly_the_four_period_peaks() -> None:
    probs = HERO["ideal"]["probabilities"]
    width = CIRCUIT["n_clbits"]
    r = _order(HERO["resolution"]["a"], HERO["resolution"]["n"])
    peaks = {format(s * 2**width // r, f"0{width}b") for s in range(r)}
    assert set(probs) == peaks, "ideal peaks must sit at multiples of 2^n / r"
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(p == pytest.approx(1 / r, abs=1e-9) for p in probs.values())


def test_hero_data_file_lives_where_the_build_writes_it() -> None:
    assert Path(REPO / "web" / "public" / "data" / "hero.json").is_file()


# -------------------------------------------- herostrip.json: the hero's lean copy of hero.json

STRIP = load_data("herostrip")
# the only things the strip may omit: bookkeeping and the per-job count tables (hero.json still
# feeds the coin egg with those); it may never add or change a value
ALLOWED_DROPPED = {
    ".hardware.batch",
    ".hardware.device_qubits_source",
    *(
        f".hardware.jobs[].{k}"
        for k in ("config", "counts", "finished", "isa_sha256", "shots", "status")
    ),
}


def _paths(x, p: str = "") -> set[str]:  # noqa: ANN001
    out: set[str] = set()
    if isinstance(x, dict):
        for k, v in x.items():
            out |= {f"{p}.{k}"} | _paths(v, f"{p}.{k}")
    elif isinstance(x, list):
        for v in x:
            out |= _paths(v, f"{p}[]")
    return out


def _value_diffs(strip, full, path: str = "") -> list[str]:  # noqa: ANN001
    """Where `strip` holds a value that `full` does not (lists compared element by element)."""
    if isinstance(strip, dict):
        if not isinstance(full, dict):
            return [path]
        return [
            d
            for k, v in strip.items()
            for d in (_value_diffs(v, full[k], f"{path}.{k}") if k in full else [f"{path}.{k}"])
        ]
    if isinstance(strip, list):
        if not isinstance(full, list) or len(strip) != len(full):
            return [path]
        return [
            d for a, b in zip(strip, full, strict=True) for d in _value_diffs(a, b, f"{path}[]")
        ]
    return [] if strip == full else [path]


def test_hero_strip_holds_no_value_that_differs_from_hero() -> None:
    assert _value_diffs(STRIP, HERO) == []


def test_hero_strip_adds_nothing_and_drops_only_the_allowed_keys() -> None:
    strip_paths, hero_paths = _paths(STRIP), _paths(HERO)
    assert strip_paths - hero_paths == set(), "the strip has a key hero.json does not"
    dropped = {p for p in hero_paths - strip_paths if ".counts." not in p}
    assert dropped <= ALLOWED_DROPPED, sorted(dropped - ALLOWED_DROPPED)


def test_hero_strip_diff_check_can_fail() -> None:
    import copy

    bad = copy.deepcopy(STRIP)
    bad["resolution"]["order"] += 1
    bad["hardware"]["jobs"][0]["job_id"] = "tampered"
    assert set(_value_diffs(bad, HERO)) == {".resolution.order", ".hardware.jobs[].job_id"}
    extra = copy.deepcopy(STRIP)
    extra["hardware"]["secret_note"] = "x"
    assert ".hardware.secret_note" in _paths(extra) - _paths(HERO)


def test_hero_strip_keeps_what_the_page_shows() -> None:
    # the hero reads these from the strip; a field lost here would silently empty a figure
    jobs = STRIP["hardware"]["jobs"]
    assert [j["job_id"] for j in jobs] == [j["job_id"] for j in HERO["hardware"]["jobs"]]
    assert STRIP["hardware"]["backend"] == HERO["hardware"]["backend"]
    assert STRIP["resolution"] == HERO["resolution"]
    assert STRIP["ideal"] == HERO["ideal"]
