"""Independent reference for the Phase 4 risk model (nothing here imports from quantum/).

The model was fixed in the phase brief, before any code was written, so that it can be recomputed.
Everything below is written from that text and from textbook statistics, so builder's
code and result files are checked against something builder did not produce. Loaders FAIL
(never skip) when a file the phase promises is missing.

Falsifying checks (listed first, as the Phase 3 retro asks):
- timeline fit: known-answer synthetic series, a hand-computed regression, a Student-t table value.
- mosca: three hand-computed assets under two scenarios, written as literals in the tests.
- ranking: monotonicity properties and "null margin ranks last".
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RISK = ROOT / "quantum" / "risk"
RESULTS = ROOT / "results" / "risk"
WEB_DATA = ROOT / "web" / "public" / "data"
EST = ROOT / "results" / "estimate"
LIT = ROOT / "quantum" / "estimate" / "literature.yaml"
FACTCHECK = ROOT / "tests" / "phase3" / "factcheck.json"
DEMO_CBOM = RISK / "data" / "demo_cbom.cdx.json"

SCENARIOS = ("optimistic", "median", "pessimistic")
TARGETS = ("rsa2048", "ecc256", "aes128")
FAMILIES = ("RSA", "ECC", "AES", "SHA", "ML-KEM", "ML-DSA", "SLH-DSA")
EXPOSURES = ("internet", "partner", "internal")
USAGES = ("key_exchange", "encryption", "signature", "hash")
SECONDS_PER_YEAR = 365.25 * 86400  # the brief says "1 year"; far-from-boundary cases do not care


def load_json(path: Path) -> dict:
    if not path.exists():
        pytest.fail(f"{path.relative_to(ROOT)} does not exist yet (promised by the phase brief)")
    return json.loads(path.read_text())


def load_yaml(path: Path):
    import yaml

    if not path.exists():
        pytest.fail(f"{path.relative_to(ROOT)} does not exist yet (promised by the phase brief)")
    return yaml.safe_load(path.read_text())


def literature() -> list[dict]:
    return load_yaml(LIT)


def factcheck() -> dict:
    return load_json(FACTCHECK)


# ---------------------------------------------------------------- timeline: OLS + Student t
def t_crit(dof: int, p: float = 0.975) -> float:
    from scipy import stats

    return float(stats.t.ppf(p, dof))


def ols(xs: list[float], ys: list[float]) -> dict:
    """Ordinary least squares y = a + b x with the textbook standard error of b (n-2 dof)."""
    n = len(xs)
    assert n >= 3 and len(ys) == n
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    b = sxy / sxx
    a = my - b * mx
    res = [y - (a + b * x) for x, y in zip(xs, ys, strict=True)]
    sse = sum(r * r for r in res)
    sst = sum((y - my) ** 2 for y in ys)
    se_b = math.sqrt(sse / (n - 2) / sxx)
    return {
        "a": a,
        "b": b,
        "se_b": se_b,
        "r2": 1.0 - sse / sst if sst > 0 else 1.0,
        "n": n,
        "residuals": res,
    }


def doubling_fit(points: list[tuple[float, float]]) -> dict:
    """points = (year, qubits). log2(qubits) = a + b year; doubling_years = 1/b.

    95% CI = 1/(b +- t*se_b), Student t, n-2 dof; a bound whose slope is <= 0 is None. `ci95` is
    ordered [short end, long end] = [1/(b + t se), 1/(b - t se)], i.e. [lo, hi] in years.
    """
    xs = [float(y) for y, _ in points]
    ys = [math.log2(q) for _, q in points]
    f = ols(xs, ys)
    t = t_crit(f["n"] - 2)
    hi_slope, lo_slope = f["b"] + t * f["se_b"], f["b"] - t * f["se_b"]
    return {
        **f,
        "doubling_years": 1.0 / f["b"],
        "ci95": [
            1.0 / hi_slope if hi_slope > 0 else None,
            1.0 / lo_slope if lo_slope > 0 else None,
        ],
        "t": t,
    }


def predict_qubits(fit: dict, year: float) -> float:
    return 2.0 ** (fit["a"] + fit["b"] * year)


def holdout(points: list[tuple[float, float]]) -> dict:
    """Fit without the latest point, predict it."""
    pts = sorted(points)
    fit = doubling_fit(pts[:-1])
    year, actual = pts[-1]
    predicted = predict_qubits(fit, year)
    return {
        "year": year,
        "predicted": predicted,
        "actual": actual,
        "rel_error": (predicted - actual) / actual,
    }


# ---------------------------------------------------------------- CRQC year, Mosca, ranking
def crqc_year(
    as_of_year: float,
    doubling_years: float,
    physical_qubits: float,
    runtime_seconds: float,
    baseline_qubits: float,
    runtime_cap_years: float = 1.0,
) -> float | None:
    """as_of + doubling * max(0, log2(P / baseline)) if R <= cap, else None."""
    if runtime_seconds > runtime_cap_years * SECONDS_PER_YEAR:
        return None
    return as_of_year + doubling_years * max(0.0, math.log2(physical_qubits / baseline_qubits))


def margin(crqc: float | None, as_of_year: float, x: float, y: float) -> float | None:
    """margin = z - (x + y), z = crqc_year - as_of_year; None when there is no crqc year."""
    if crqc is None:
        return None
    return (crqc - as_of_year) - (x + y)


def shortfall(weight: float, m: float | None) -> float:
    return 0.0 if m is None else weight * max(0.0, -m)


def rank_key(asset_id: str, weight: float, m: float | None) -> tuple:
    return (-shortfall(weight, m), math.inf if m is None else m, asset_id)


def ranks(items: list[tuple[str, float, float | None]]) -> dict[str, int]:
    """items = (asset id, exposure weight, margin). Rank 1 = most urgent."""
    order = sorted(items, key=lambda it: rank_key(*it))
    return {it[0]: i + 1 for i, it in enumerate(order)}


def family_order(by_family: dict[str, list[float | None]]) -> list[str]:
    """Families sorted by (min crqc_year over their assets, None = +inf, name)."""

    def key(fam: str) -> tuple:
        vals = [v for v in by_family[fam] if v is not None]
        return (min(vals) if vals else math.inf, fam)

    return sorted(by_family, key=key)


# ---------------------------------------------------------------- mapping (as fixed in the brief)
def attack_target(family: str, algorithm: str = "") -> str | None:
    """RSA -> rsa2048; ECC (ECDSA/ECDH/EdDSA/X25519, <= 521 bit) -> ecc256; AES/SHA -> aes128."""
    return {
        "RSA": "rsa2048",
        "ECC": "ecc256",
        "AES": "aes128",
        "SHA": "aes128",
        "ML-KEM": None,
        "ML-DSA": None,
        "SLH-DSA": None,
    }[family]


def family_order_by_target(target_crqc: dict[str, float | None]) -> list[str]:
    """Lead (2026-11-08): families sorted by (CRQC year of their ATTACK TARGET, None = +inf, name).
    An asset's own deprecation status (classical weakness) never moves its family."""

    def key(fam: str) -> tuple:
        t = attack_target(fam)
        y = target_crqc.get(t) if t else None
        return (math.inf if y is None else y, fam)

    return sorted(FAMILIES, key=key)


CURVE_BITS = {
    "nist/p-256": 256,
    "nist/p-384": 384,
    "nist/p-521": 521,
    "secp256k1": 256,
    "x25519": 255,
    "ed25519": 255,
}


def key_bits(component: dict) -> int | None:
    """Key size in bits read straight from a CBOM component (algorithmProperties)."""
    props = component["cryptoProperties"]["algorithmProperties"]
    name = component["name"].upper()
    if name.startswith("RSA"):
        return int(props["parameterSetIdentifier"])
    if name.startswith(("ECDSA", "ECDH", "ED25519", "X25519")):
        return CURVE_BITS[(props.get("curve") or component["name"]).lower()]
    if name.startswith(("ML-", "SLH-")):
        return None
    ps = props.get("parameterSetIdentifier")
    return int(ps) if ps else None


def classically_deprecated(
    family: str, algorithm: str, bits: int | None, usage: str | None = None
) -> bool:
    """Below 112 bits of classical security: RSA < 2048, ECC < 224 bits (SP 800-131A Rev. 2), and
    plain SHA-1 in signature or hash use, where collision resistance matters (lead, 2026-11-08;
    SP 800-57 Pt 1 Rev. 5 Table 3). HMAC-SHA-1 and SHA-1 in other uses are not."""
    if algorithm == "SHA-1":
        return usage in ("signature", "hash")
    if bits is None:
        return False
    return (family == "RSA" and bits < 2048) or (family == "ECC" and bits < 224)
