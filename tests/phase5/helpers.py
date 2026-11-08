"""Pure-Python helpers for the Phase 5 tests. Owned by reviewer. No browser, no network.

Thresholds come from the "Falsifying checks" table in .coord/STATE.md (fixed before BUILD):
  * provenance: 0 untraced figures, 0 mismatches beyond HALF THE LAST DIGIT SHOWN.
  * secret hygiene: 0 hits, and a planted canary in a temp copy must be caught.
These helpers implement the comparison rules once so the tests only decide *what* to compare.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
# QDAY_WEB_ROOT points the tests at a clean build of another checkout; default = ./web
WEB = Path(os.environ.get("QDAY_WEB_ROOT") or REPO / "web")
DATA_DIR = WEB / "public" / "data"
OUT_DIR = WEB / "out"
SCENARIOS = ("optimistic", "median", "pessimistic")
ROUTES = ("/", "/lab/", "/scaling/", "/inventory/")
VIEWPORTS = ((1440, 900), (1024, 768), (390, 844))


# --------------------------------------------------------------------------- data


def load_data(name: str) -> Any:
    """Load web/public/data/<name>.json (name without extension)."""
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_\-]*)|\[(\d+)\]")


def resolve_path(data: Any, path: str) -> Any:
    """Walk `a.b[3].c` through nested dicts/lists. A missing step raises KeyError/IndexError,
    so a `data-src` that points nowhere fails loudly rather than comparing against None."""
    cur = data
    pos = 0
    path = path.strip()
    while pos < len(path):
        if path[pos] == ".":
            pos += 1
            continue
        m = _TOKEN.match(path, pos)
        if not m:
            raise KeyError(f"cannot parse data path {path!r} at offset {pos}")
        key, idx = m.group(1), m.group(2)
        cur = cur[key] if key is not None else cur[int(idx)]
        pos = m.end()
    return cur


def resolve_src(src: str) -> Any:
    """Resolve a `data-src` value of the form `<file>:<path>` against web/public/data."""
    if ":" not in src:
        raise ValueError(f"data-src {src!r} is not '<file>:<path>'")
    file, path = src.split(":", 1)
    return resolve_path(load_data(file), path)


# ----------------------------------------------------------------- figure comparison

_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_SCI = re.compile(r"^(?P<m>[+\-−]?\d+(?:\.\d+)?)\s*(?:[eE]|[x×·*]\s*10\s*\^?)\s*(?P<e>[+\-−]?\d+)$")
_NUM = re.compile(r"^[+\-−]?\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class Shown:
    """A figure as displayed: its value in the displayed unit and the half-last-digit slack."""

    value: float
    tolerance: float


def parse_shown(text: str) -> Shown:
    """Parse what a person reads: '8.73', '6.35e6', '6.35 × 10⁶', '1,234', '42%', '−3.1'.

    The tolerance is half of the last digit shown (so '8.73' tolerates ±0.005). An integer
    like '1,234' has last digit 1, tolerance 0.5. Unparseable text raises ValueError, never
    silently passes."""
    t = text.strip().replace(" ", "").replace(" ", "").replace(",", "")
    t = t.replace("−", "-").rstrip("%").strip()
    t = t.translate(_SUP) if "×" in t or "·" in t else t
    m = _SCI.match(t)
    if m:
        mant, exp = m.group("m"), int(m.group("e").replace("−", "-"))
        decimals = len(mant.split(".")[1]) if "." in mant else 0
        return Shown(float(mant) * 10**exp, 0.5 * 10 ** (-decimals) * 10**exp)
    if _NUM.match(t):
        decimals = len(t.split(".")[1]) if "." in t else 0
        return Shown(float(t), 0.5 * 10 ** (-decimals))
    raise ValueError(f"cannot read a figure from {text!r}")


def figure_matches(shown_text: str, actual: Any, scale: float = 1.0) -> tuple[bool, str]:
    """Rule from the brief: text equals the data value (times data-scale) to the digits shown.

    numbers: |shown - actual*scale| <= half the last digit shown (+ float slack)
    strings: the text contains the value
    null:    there must be no figure (text must hold no digits)"""
    if actual is None:
        has_digit = any(c.isdigit() for c in shown_text)
        return (not has_digit, f"null value but text {shown_text!r} shows a figure")
    if isinstance(actual, bool):
        return (str(actual).lower() in shown_text.lower(), f"bool {actual} not in {shown_text!r}")
    if isinstance(actual, str):
        return (actual in shown_text, f"{actual!r} not contained in {shown_text!r}")
    shown = parse_shown(shown_text)
    want = float(actual) * scale
    slack = shown.tolerance * (1 + 1e-9) + 1e-12 * max(1.0, abs(want))
    ok = math.isfinite(want) and abs(shown.value - want) <= slack
    return (ok, f"shown {shown.value!r} (±{shown.tolerance:g}) vs data {want!r}")


# ----------------------------------------------------------------------- secret scan


@dataclass(frozen=True)
class Hit:
    file: str
    kind: str  # "value" or "pattern"
    detail: str  # never the secret itself: an index or pattern name


def scan_tree(
    root: Path,
    values: Iterable[str] = (),
    patterns: dict[str, re.Pattern[str]] | None = None,
) -> list[Hit]:
    """Scan every file under root for exact secret values and for regex patterns.

    Binary files are scanned as latin-1 so a value cannot hide in a font or image. Hits carry
    the value's index or the pattern name only, so a failing test never prints a secret."""
    vals = [v for v in values if v]
    pats = patterns or {}
    hits: list[Hit] = []
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        text = f.read_bytes().decode("latin-1")
        rel = str(f.relative_to(root))
        hits += [Hit(rel, "value", f"#{i}") for i, v in enumerate(vals) if v in text]
        hits += [Hit(rel, "pattern", name) for name, rx in pats.items() if rx.search(text)]
    return hits


def read_dotenv_values(path: Path) -> list[str]:
    """Values of KEY=VALUE lines, in memory only. Short or trivial values are skipped (a 3-char
    value would match everywhere and prove nothing). Callers must never print the result."""
    if not path.is_file():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        val = line.split("=", 1)[1].strip().strip("'\"")
        if len(val) >= 8:
            out.append(val)
    return out


# ------------------------------------------------------------------------ CSP + inline scripts

HEADERS_CONFIG = WEB / ".vercel" / "output" / "config.json"
_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
_ATTR_TYPE = re.compile(r"""\btype\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)
_ATTR_SRC = re.compile(r"\bsrc\s*=", re.I)
INLINE_JS_TYPES = {"", "text/javascript", "application/javascript", "module"}


def csp_hash(body: str) -> str:
    """CSP source for an inline script: 'sha256-' + base64(sha256(utf8 body)), quoted."""
    digest = hashlib.sha256(body.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode() + "'"


def inline_script_hashes(html: str) -> set[str]:
    """Hashes of every executable inline script (rule posted by builder, task 2): no src, type
    absent or text/javascript, application/javascript, module, and a non-blank body. Data blocks
    (application/json, ld+json) are not executed, so they need no hash."""
    out: set[str] = set()
    for attrs, body in _SCRIPT.findall(html):
        if _ATTR_SRC.search(attrs) or not body.strip():
            continue
        m = _ATTR_TYPE.search(attrs)
        typ = next((g for g in m.groups() if g), "").strip().lower() if m else ""
        if typ in INLINE_JS_TYPES:
            out.add(csp_hash(body))
    return out


def page_files(out_dir: Path) -> list[Path]:
    """Every HTML document in the export (the 4 routes and 404.html)."""
    return sorted(out_dir.rglob("*.html"))


def parse_csp(value: str) -> dict[str, list[str]]:
    """'a b; c d' -> {'a': ['b'], 'c': ['d']}. A repeated directive keeps its first value."""
    out: dict[str, list[str]] = {}
    for part in value.split(";"):
        toks = part.split()
        if toks and toks[0].lower() not in out:
            out[toks[0].lower()] = toks[1:]
    return out


def load_headers() -> dict[str, str]:
    """Headers Vercel will add to every path: routes[0] of the Build Output config."""
    cfg = json.loads(HEADERS_CONFIG.read_text(encoding="utf-8"))
    route = cfg["routes"][0]
    assert route["src"] == "/(.*)", f"first route must match every path, got {route['src']!r}"
    return route["headers"]


def unlisted_hashes(out_dir: Path, script_src: Iterable[str]) -> dict[str, set[str]]:
    """{page: inline-script hashes missing from script-src}. Empty means every script is allowed."""
    allowed = set(script_src)
    missing: dict[str, set[str]] = {}
    for f in page_files(out_dir):
        gap = inline_script_hashes(f.read_text(encoding="utf-8")) - allowed
        if gap:
            missing[str(f.relative_to(out_dir))] = gap
    return missing


CSP_FIXED = {
    "default-src": ["'self'"],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:"],
    "font-src": ["'self'"],
    "connect-src": ["'self'"],
    "frame-ancestors": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'none'"],
    "upgrade-insecure-requests": [],
}
CSP_BANNED_SCRIPT = {"'unsafe-inline'", "'unsafe-eval'", "*", "data:", "blob:", "http:", "https:"}


def csp_problems(value: str) -> list[str]:
    """Every way a CSP header departs from the spec (section 9): empty list = policy as specified.
    The real test and the mutation tests both call this, so a blind rule cannot pass both."""
    csp = parse_csp(value)
    bad: list[str] = []
    for name, sources in CSP_FIXED.items():
        if csp.get(name) != sources:
            bad.append(f"{name}: {csp.get(name)!r} != {sources!r}")
    extra = set(csp) - {*CSP_FIXED, "script-src"}
    if extra:
        bad.append(f"directives beyond the spec: {sorted(extra)}")
    srcs = csp.get("script-src", [])
    if not srcs or srcs[0] != "'self'":
        bad.append("script-src must start with 'self'")
    hashes = srcs[1:]
    if not hashes:
        bad.append("script-src has no hashes")
    bad += [
        f"script-src source not a sha256 hash: {h}"
        for h in hashes
        if not (h.startswith("'sha256-") and h.endswith("'"))
    ]
    bad += [f"banned in script-src: {h}" for h in srcs if h in CSP_BANNED_SCRIPT]
    if len(hashes) != len(set(hashes)):
        bad.append("duplicate hash")
    for name, vals in csp.items():
        bad += [
            f"{name} names an origin or wildcard: {v}"
            for v in vals
            if v == "*" or "://" in v or v.startswith("//")
        ]
    return bad


# A fake access-key-shaped value for planting in a temp copy. Built from two parts at runtime so the
# source holds no literal that gitleaks (rightly) treats as a leaked key.
FAKE_AWS_KEY_ID = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
