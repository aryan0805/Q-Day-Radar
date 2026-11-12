"""QDK vs Qualtran cross-check: every ratio is recomputed from the two per-case files."""

from __future__ import annotations

import re

import pytest

from tests.phase3 import reference as ref

LIMIT = 3.0


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return ref.load_json(ref.EST / "crosscheck.json")["cases"]


def _pair(row):
    qdk, qt = ref.cases("qdk"), ref.cases("qualtran")
    assert row["qdk"] in qdk, f"{row['case']}: no QDK file {row['qdk']}"
    assert row["qualtran"] in qt, f"{row['case']}: no Qualtran file {row['qualtran']}"
    return qdk[row["qdk"]], qt[row["qualtran"]]


def test_crosscheck_ratios_recomputed_from_per_case_files(rows):
    assert rows
    for row in rows:
        a, b = _pair(row)
        # recompute from RAW counts, not from the stored toffoli_equiv, so a bad conversion shows
        want_q = ref.ratio(a["logical_counts"]["num_qubits"], b["logical_qubits"])
        want_t = ref.ratio(ref.toffoli_equiv_qdk(a), ref.toffoli_equiv_qualtran(b))
        assert row["ratio_logical_qubits"] == pytest.approx(want_q, rel=1e-6), row["case"]
        assert row["ratio_toffoli_equiv"] == pytest.approx(want_t, rel=1e-6), row["case"]
        assert row["ratio_logical_qubits"] >= 1 and row["ratio_toffoli_equiv"] >= 1


def test_crosscheck_has_enough_cases_of_each_kind(rows):
    kinds = [r["kind"] for r in rows]
    assert set(kinds) <= {"same_circuit", "same_function"}
    assert kinds.count("same_circuit") >= 4 and kinds.count("same_function") >= 4, kinds


def test_crosscheck_kinds_match_what_was_actually_costed(rows):
    """same_circuit: one circuit, both tools. same_function: our Beauregard vs Qualtran ModExp."""
    for row in rows:
        a, b = _pair(row)
        assert (a["N"], a["base_a"]) == (b["N"], b["base_a"]), f"{row['case']}: different N or a"
        if row["kind"] == "same_circuit":
            assert b["method"] == "same_circuit", f"{row['case']}: Qualtran method {b['method']}"
        else:
            assert b["method"] == "bloq", f"{row['case']}: Qualtran method {b['method']}"
            assert re.match(r"^beauregard_N\d+_a\d+$", row["qdk"]), row["qdk"]
            assert re.match(r"^modexp_N\d+_a\d+$", row["qualtran"]), row["qualtran"]


def test_crosscheck_P005_compared_over_several_bases_not_order_two_only(rows):
    for kind in ("same_circuit", "same_function"):
        sel = [_pair(r)[0] for r in rows if r["kind"] == kind]
        bases = {(c["N"], c["base_a"]) for c in sel}
        assert len({a for _, a in bases}) >= 2 and len({n for n, _ in bases}) >= 2, (
            f"{kind}: only {sorted(bases)}"
        )
        assert any(ref.order(a, n) > 2 for n, a in bases), f"{kind}: every base has order <= 2"


def _unexplained_over_limit(rows, explained):
    over = []
    for r in rows:
        for key in ("ratio_logical_qubits", "ratio_toffoli_equiv"):
            if r[key] > LIMIT and r["case"] not in explained:
                over.append(f"{r['case']} {key}={r[key]:.3g}")
    return over


def test_crosscheck_every_ratio_over_3x_has_a_written_explanation(rows):
    explained = set(ref.private_facts()["explained_crosscheck_case_ids"])
    over = _unexplained_over_limit(rows, explained)
    assert not over, "over 3x with no written explanation: " + "; ".join(over)


def test_crosscheck_explanation_check_catches_an_unexplained_case(rows):
    """Planted defect: drop one over-3x case from the explained set and the check must name it."""
    explained = set(ref.private_facts()["explained_crosscheck_case_ids"])
    first_over = next(
        r["case"]
        for r in rows
        if r["ratio_logical_qubits"] > LIMIT or r["ratio_toffoli_equiv"] > LIMIT
    )
    over = _unexplained_over_limit(rows, explained - {first_over})
    assert any(first_over in o for o in over)


def test_crosscheck_ids_unique(rows):
    ids = [r["case"] for r in rows]
    assert len(ids) == len(set(ids))


def test_crosscheck_same_circuit_cases_gave_both_tools_the_identical_non_dynamic_circuit(rows):
    """Caveat B (written down before the phase closed): one non-dynamic form feeds both tools.

    The hash proves it.

    Needs `circuit_sha256` (sha256 of the QASM both tools were given) and `circuit_form` in both
    per-case files of every same_circuit row.
    """
    for row in rows:
        if row["kind"] != "same_circuit":
            continue
        a, b = _pair(row)
        for tool, c in (("qdk", a), ("qualtran", b)):
            assert c.get("circuit_sha256"), f"{row['case']}: {tool} file has no circuit_sha256"
            assert c.get("circuit_form") == "non_dynamic", (
                f"{row['case']}: {tool} {c.get('circuit_form')}"
            )
        assert a["circuit_sha256"] == b["circuit_sha256"], (
            f"{row['case']}: tools got different circuits"
        )
        assert a.get("classical_control_counted") == "executed", (
            f"{row['case']}: classically controlled rotations must count as executed"
        )
