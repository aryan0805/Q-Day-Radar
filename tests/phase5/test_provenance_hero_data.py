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
