"""No number is typed into the risk code except a listed, explainable one.

Brief (task 9): "no number typed outside literature.yaml, the CBOM and the two design yamls".
An AST scan of every numeric constant in quantum/risk/*.py and the two Phase 4 scripts. 0, 1, 2 and
-1 are structural; everything else must be in ALLOWED with the reason. A new literal (a tuned
weight, a hard-coded year, a typed qubit count) fails the test until it is explained here.
"""

from __future__ import annotations

import ast

import pytest

from tests.phase4 import reference as ref

STRUCTURAL = {0, 1, 2, -1}
# (relative file, value) -> why it may be typed
ALLOWED = {
    ("quantum/risk/mapping.py", 256): "curve size in bits (mapping table, brief)",
    ("quantum/risk/mapping.py", 384): "curve size in bits (mapping table, brief)",
    ("quantum/risk/mapping.py", 521): "curve size in bits; brief's upper limit for ecc256",
    ("quantum/risk/mapping.py", 255): "curve size in bits (x25519, ed25519)",
    ("quantum/risk/mapping.py", 448): "curve size in bits (x448, ed448)",
    ("quantum/risk/mapping.py", 2048): "RSA key size that defines the rsa2048 target (brief)",
    ("quantum/risk/mapping.py", 224): (
        "ECC key size below which strength is under 112 bits: printed in SP 800-131A Rev. 2 "
        "Table 2 p. 9 and p. 10 ('len(n) shall be at least 224 bits')"
    ),
    ("quantum/risk/models.py", 3): "index into the property-name tuple",
    ("quantum/risk/timeline.py", 365.25): "seconds per year, a unit conversion",
    ("quantum/risk/timeline.py", 86400): "seconds per day, a unit conversion",
    ("quantum/risk/timeline.py", 60.0): "unit conversion",
    ("quantum/risk/timeline.py", 3600.0): "unit conversion",
    ("quantum/risk/timeline.py", 3): "minimum number of points for a regression with n-2 dof",
    ("quantum/risk/timeline.py", 0.975): "two-sided 95% Student-t quantile level (brief)",
    ("scripts/risk_timeline.py", 1e-09): "floating-point comparison tolerance",
    ("scripts/risk_timeline.py", 4): "as_of[:4] slices the year out of an ISO date",
}


def _files():
    files = sorted((ref.ROOT / "quantum" / "risk").glob("*.py"))
    files += [ref.ROOT / "scripts" / n for n in ("risk_timeline.py", "build_data.py")]
    existing = [f for f in files if f.exists()]
    assert len(existing) >= 5, "expected the Phase 4 risk code to exist"
    return existing


def _numbers(path):
    out = []
    for n in ast.walk(ast.parse(path.read_text())):
        if (
            isinstance(n, ast.Constant)
            and isinstance(n.value, (int, float))
            and not isinstance(n.value, bool)
            and n.value not in STRUCTURAL
        ):
            out.append((n.lineno, n.value))
    return out


def test_timeline_risk_code_types_no_unlisted_number():
    bad = []
    for path in _files():
        rel = str(path.relative_to(ref.ROOT))
        for line, value in _numbers(path):
            if (rel, value) not in ALLOWED:
                bad.append(f"{rel}:{line} {value}")
    assert not bad, (
        "numbers typed in code (move to a yaml/CBOM or explain in ALLOWED): " + "; ".join(bad)
    )


def test_timeline_the_allow_list_has_no_stale_entries():
    seen = {(str(p.relative_to(ref.ROOT)), v) for p in _files() for _, v in _numbers(p)}
    stale = [k for k in ALLOWED if k not in seen]
    assert not stale, f"allow-list entries nothing uses any more: {stale}"


def test_timeline_the_scan_has_teeth(tmp_path):
    """A synthetic file with a typed qubit count and a typed weight must be caught."""
    f = tmp_path / "x.py"
    f.write_text("QUBITS = 897864\nWEIGHT = 3.5\n")
    assert {v for _, v in _numbers(f)} == {897864, 3.5}


@pytest.mark.parametrize("name", ["exposure.yaml", "replacements.yaml"])
def test_timeline_design_yamls_are_labelled_design_choices(name):
    text = (ref.RISK / name).read_text().lower()
    assert "design choice" in text or "label: design_choice" in text, name
