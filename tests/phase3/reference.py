"""Independent references for Phase 3 (nothing here imports from quantum/).

Everything below is written from textbook definitions so that builder's estimators, fits and
files are checked against something builder did not produce. Loaders FAIL (never skip) when a
file the phase promises is missing: a missing result is a failed gate, not a skipped test.
"""

from __future__ import annotations

import json
import math
import statistics
from math import gcd
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EST = ROOT / "results" / "estimate"
LIT = ROOT / "quantum" / "estimate" / "literature.yaml"
FACTCHECK = ROOT / "tests" / "phase3" / "factcheck.json"
DECISIONS = ROOT / "docs" / "DECISIONS.md"

REGISTRY = {
    "shor15_textbook": "compiled",
    "shor15_beauregard": "generic",
    "shor21_beauregard": "generic",
    **{f"grover_present_k{k}": "generic" for k in range(2, 6)},
}
TARGETS = ("rsa2048", "ecc256", "aes128")
SCENARIOS = ("optimistic", "median", "pessimistic")


def load_json(path: Path) -> dict:
    if not path.exists():
        pytest.fail(f"{path.relative_to(ROOT)} does not exist yet (promised by the phase brief)")
    return json.loads(path.read_text())


def cases(tool: str) -> dict[str, dict]:
    d = EST / tool
    if not d.exists() or not list(d.glob("*.json")):
        pytest.fail(f"results/estimate/{tool}/ has no case files")
    return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))}


CIRCUITS = EST / "circuits"


def circuit_files() -> list[Path]:
    """Every stored common-basis circuit (gzip; name = sha256 of the uncompressed QASM)."""
    files = sorted(CIRCUITS.glob("*.qasm.gz"))
    if not files:
        pytest.fail("results/estimate/circuits/ has no *.qasm.gz circuits")
    return files


def read_circuit(sha256: str) -> str:
    """Decompressed QASM text of one stored circuit, by its sha256."""
    import gzip

    path = CIRCUITS / f"{sha256}.qasm.gz"
    if not path.exists():
        pytest.fail(f"{path.relative_to(ROOT)} missing: store the QASM both tools were given")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.read()


def literature() -> list[dict]:
    import yaml

    if not LIT.exists():
        pytest.fail("quantum/estimate/literature.yaml does not exist yet")
    data = yaml.safe_load(LIT.read_text())
    return data if isinstance(data, list) else data.get("entries", [])


# ---- number theory ----------------------------------------------------------------------
def order(a: int, n: int) -> int:
    """Multiplicative order of a mod n, by brute force."""
    if gcd(a, n) != 1:
        raise ValueError(f"{a} not coprime to {n}")
    x, r = a % n, 1
    while x != 1:
        x, r = (x * a) % n, r + 1
    return r


def prime_factors(n: int) -> list[int]:
    out, p = [], 2
    while p * p <= n:
        while n % p == 0:
            out.append(p)
            n //= p
        p += 1
    if n > 1:
        out.append(n)
    return out


# ---- the cost formula the brief fixes ---------------------------------------------------
def toffoli_equiv_qdk(c: dict) -> float:
    lc, k = c["logical_counts"], c["rotation_t_cost"]
    return lc["ccz_count"] + lc["ccix_count"] + lc["t_count"] / 4 + lc["rotation_count"] * k / 4


def toffoli_equiv_qualtran(c: dict) -> float:
    ct, k = c["counts"], c["rotation_t_cost"]
    return ct["toffoli"] + ct["t"] / 4 + ct["rotations"] * k / 4


def equiv_of(tool: str, c: dict) -> float:
    return toffoli_equiv_qdk(c) if tool == "qdk" else toffoli_equiv_qualtran(c)


def qubits_of(tool: str, c: dict) -> int:
    return c["logical_counts"]["num_qubits"] if tool == "qdk" else c["logical_qubits"]


def ratio(x: float, y: float) -> float:
    lo, hi = min(x, y), max(x, y)
    return hi / lo if lo > 0 else math.inf


# ---- hand-countable truths --------------------------------------------------------------
def qft_rotations(n: int) -> int:
    """An n-qubit QFT without swaps has n(n-1)/2 controlled-phase rotations."""
    return n * (n - 1) // 2


# ---- fitting ----------------------------------------------------------------------------
def power_law(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least squares on log y = log c + k log x. Returns (k, c)."""
    lx, ly = [math.log(x) for x in xs], [math.log(y) for y in ys]
    mx, my = statistics.fmean(lx), statistics.fmean(ly)
    k = sum((a - mx) * (b - my) for a, b in zip(lx, ly, strict=False)) / sum(
        (a - mx) ** 2 for a in lx
    )
    return k, math.exp(my - k * mx)


def linear(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Ordinary least squares y = a x + b. Returns (a, b)."""
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False)) / sum(
        (x - mx) ** 2 for x in xs
    )
    return a, my - a * mx


# ---- our own QASM parser (never builder's code): the reference gate counts -----------------
import ast  # noqa: E402
import re  # noqa: E402

_CLIFFORD = {
    "h",
    "x",
    "y",
    "z",
    "s",
    "sdg",
    "sx",
    "sxdg",
    "cx",
    "cz",
    "cy",
    "swap",
    "id",
    "reset",
    "barrier",
}
_ROT = {"rz", "rx", "ry", "p", "u1"}
_STMT = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*(?:\(([^)]*)\))?\s*(.*)$")


def eval_angle(expr: str) -> float:
    """Evaluate a QASM angle such as '-pi/4' or '0.3' with a whitelist (no eval of names)."""

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id == "pi":
            return math.pi
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return -ev(node.operand) if isinstance(node.op, ast.USub) else ev(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            a, b = ev(node.left), ev(node.right)
            return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b, ast.Div: a / b}[type(node.op)]
        raise ValueError(f"unsupported angle expression {expr!r}")

    return ev(ast.parse(expr.strip(), mode="eval"))


def qasm_counts(qasm: str) -> dict[str, int]:
    """Count T-type gates, generic rotations and Toffolis in an OpenQASM 2 string.

    A rotation by an odd multiple of pi/4 is one T gate, by an even multiple a Clifford, by any
    other angle one generic rotation. ccx, ccz and cswap each count as one Toffoli. A gate
    outside the common basis (e.g. cp, crz, mcx) raises, so a leak cannot be miscounted.
    """
    out = {"t": 0, "rotations": 0, "ccx": 0, "measurements": 0, "clifford": 0}
    body = re.sub(r"//[^\n]*", "", qasm)
    for raw in body.split(";"):
        m = _STMT.match(raw.strip().replace("\n", " "))
        if not m or not raw.strip():
            continue
        name, params, _ = m.groups()
        if name in {"openqasm", "include", "qreg", "creg"}:
            continue
        if name in {"t", "tdg"}:
            out["t"] += 1
        elif name in _ROT:
            quarter = eval_angle(params) / (math.pi / 4)
            if abs(quarter - round(quarter)) < 1e-9:
                if round(quarter) % 2:
                    out["t"] += 1
                else:
                    out["clifford"] += 1
            else:
                out["rotations"] += 1
        elif name in {"ccx", "ccz", "cswap"}:
            out["ccx"] += 1
        elif name == "measure":
            out["measurements"] += 1
        elif name in _CLIFFORD:
            out["clifford"] += 1
        else:
            raise ValueError(f"gate {name!r} is not in the common basis")
    return out


def counts_equiv(counts: dict[str, int], rotation_t_cost: float) -> float:
    """toffoli_equiv of reference counts, by the brief's formula."""
    return counts["ccx"] + counts["t"] / 4 + counts["rotations"] * rotation_t_cost / 4


def poly_rel(xs: list[float], ys: list[float], degree: int = 4) -> list[float]:
    """Degree-d polynomial, least squares on RELATIVE residuals (weights 1/y), highest power first.

    Solved with the normal equations in exact rational arithmetic so it shares no code with numpy.
    """
    from fractions import Fraction

    rows = [
        [Fraction(x) ** p / Fraction(y) for p in range(degree, -1, -1)]
        for x, y in zip(xs, ys, strict=True)
    ]
    m = degree + 1
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(m)] for i in range(m)]
    atb = [sum(r[i] for r in rows) for i in range(m)]  # target is 1 (y/y)
    for i in range(m):  # Gauss-Jordan
        piv = next(k for k in range(i, m) if ata[k][i] != 0)
        ata[i], ata[piv], atb[i], atb[piv] = ata[piv], ata[i], atb[piv], atb[i]
        d = ata[i][i]
        ata[i] = [v / d for v in ata[i]]
        atb[i] /= d
        for k in range(m):
            if k != i and ata[k][i] != 0:
                f = ata[k][i]
                ata[k] = [a - f * b for a, b in zip(ata[k], ata[i], strict=True)]
                atb[k] -= f * atb[i]
    return [float(v) for v in atb]


def polyval(coeffs: list[float], x: float) -> float:
    out = 0.0
    for c in coeffs:
        out = out * x + c
    return out
