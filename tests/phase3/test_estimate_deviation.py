"""Each tool's counts on every same_circuit case against this directory's own parser.

Lead (2026-11-08): count T, rotations and ccx straight from the common-basis QASM with our own
parser, then report each tool's deviation from it. The QASM each tool was given is stored by
file name = circuit_sha256 + .qasm.gz in results/estimate/circuits/ (the hash is of the
uncompressed QASM).
The numbers are printed by benchmarks/phase3-tool-deviation.py.
"""

from __future__ import annotations

import hashlib

import pytest

from tests.phase3 import reference as ref

TOLERANCE = 0.05  # reviewer threshold on toffoli_equiv, relative to the reference


def same_circuit_rows() -> list[dict]:
    rows = [
        r
        for r in ref.load_json(ref.EST / "crosscheck.json")["cases"]
        if r["kind"] == "same_circuit"
    ]
    if not rows:
        pytest.fail("crosscheck.json has no same_circuit rows")
    return rows


def _case(row):
    a, b = ref.cases("qdk")[row["qdk"]], ref.cases("qualtran")[row["qualtran"]]
    return a, b, ref.read_circuit(a["circuit_sha256"])


def test_estimate_stored_qasm_is_exactly_what_the_sha256_says():
    for row in same_circuit_rows():
        a, b, text = _case(row)
        assert (
            hashlib.sha256(text.encode()).hexdigest() == a["circuit_sha256"] == b["circuit_sha256"]
        )


def test_estimate_same_circuit_qasm_is_in_the_common_basis_and_counts_agree_with_the_files():
    """The reference parser raises on any gate outside the basis (cp, crz, mcx...)."""
    for row in same_circuit_rows():
        a, b, text = _case(row)
        r = ref.qasm_counts(text)
        assert a["logical_counts"]["ccz_count"] + a["logical_counts"]["ccix_count"] == r["ccx"], row
        assert b["counts"]["toffoli"] == r["ccx"], row


def test_estimate_each_tool_is_within_tolerance_of_the_reference_cost():
    bad = []
    for row in same_circuit_rows():
        a, b, text = _case(row)
        r = ref.qasm_counts(text)
        want = ref.counts_equiv(r, a["rotation_t_cost"])
        for tool, c in (("qdk", a), ("qualtran", b)):
            got = c["toffoli_equiv"]
            if want == 0 or abs(got - want) / want > TOLERANCE:
                bad.append(f"{row['case']} {tool}: tool {got:.6g} vs reference {want:.6g}")
    assert not bad, "; ".join(bad)
