"""Security: the headers the build hands to Vercel, and the hash-based CSP (task 7, brief table).

Thresholds, fixed before BUILD (STATE.md):
  * headers: the six exact values below, on every path (route src "/(.*)").
  * CSP: every inline script on the 4 pages + 404 hashes into script-src (0 misses); no
    'unsafe-inline' / 'unsafe-eval' / wildcard / http: source in script-src.
Each check has a mutation test: a planted inline script, a stale hash and a weakened header must
all be caught, so a green run cannot come from a check that never looks.
The live comparison (same headers on the deployed site) is the gate's p5_live, not pytest's.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from .helpers import (
    CSP_FIXED,
    HEADERS_CONFIG,
    csp_hash,
    csp_problems,
    inline_script_hashes,
    load_headers,
    page_files,
    parse_csp,
    unlisted_hashes,
)

EXACT = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
EXPECTED_PAGES = {
    "index.html",
    "404.html",
    "lab/index.html",
    "scaling/index.html",
    "inventory/index.html",
}


@pytest.fixture(scope="module")
def headers(out_dir: Path) -> dict[str, str]:
    assert HEADERS_CONFIG.is_file(), f"{HEADERS_CONFIG} missing: the build must write it"
    return load_headers()


# ----------------------------------------------------------------------------- exact headers


@pytest.mark.parametrize(("name", "value"), sorted(EXACT.items()))
def test_security_header_has_the_exact_value(
    headers: dict[str, str], name: str, value: str
) -> None:
    assert headers.get(name) == value


def test_security_config_has_only_the_six_headers_and_a_404_route(out_dir: Path) -> None:
    cfg = json.loads(HEADERS_CONFIG.read_text())
    assert cfg["version"] == 3
    assert set(cfg["routes"][0]["headers"]) == {*EXACT, "Content-Security-Policy"}
    assert cfg["routes"][0].get("continue") is True  # headers must not end routing
    assert {"handle": "filesystem"} in cfg["routes"]
    last = cfg["routes"][-1]
    assert last["dest"] == "/404.html" and last["status"] == 404  # unknown paths: a real 404


def test_security_hsts_is_long_enough_for_preload(headers: dict[str, str]) -> None:
    # hstspreload.org: max-age >= 31536000 with includeSubDomains and preload
    v = headers["Strict-Transport-Security"]
    age = int(v.split("max-age=")[1].split(";")[0])
    assert age >= 31536000 and "includeSubDomains" in v and "preload" in v


# --------------------------------------------------------------------------------- CSP policy


def test_security_csp_is_exactly_the_spec_policy(headers: dict[str, str]) -> None:
    assert csp_problems(headers["Content-Security-Policy"]) == []


def test_security_csp_script_src_is_self_plus_hashes_only(headers: dict[str, str]) -> None:
    srcs = parse_csp(headers["Content-Security-Policy"])["script-src"]
    assert srcs[0] == "'self'" and len(srcs) > 1
    assert srcs[1:] == sorted(srcs[1:]), "hashes are written in sorted order"


# ------------------------------------------------------------------------- hash recomputation


def test_security_every_inline_script_is_hashed_in_script_src(
    out_dir: Path, headers: dict[str, str]
) -> None:
    srcs = parse_csp(headers["Content-Security-Policy"])["script-src"]
    assert unlisted_hashes(out_dir, srcs) == {}


def test_security_header_hashes_are_exactly_the_inline_scripts_in_out(
    out_dir: Path, headers: dict[str, str]
) -> None:
    # the build promises the sorted union of every inline script; a stale extra hash widens
    # script-src for code that no longer exists
    srcs = parse_csp(headers["Content-Security-Policy"])["script-src"][1:]
    union: set[str] = set()
    for f in page_files(out_dir):
        union |= inline_script_hashes(f.read_text(encoding="utf-8"))
    assert set(srcs) == union
    assert srcs == sorted(srcs), "hashes are written in sorted order"


def test_security_the_four_routes_and_404_are_all_in_the_export(out_dir: Path) -> None:
    found = {str(f.relative_to(out_dir)) for f in page_files(out_dir)}
    assert EXPECTED_PAGES <= found, EXPECTED_PAGES - found


def test_security_no_inline_event_handlers_or_javascript_urls(out_dir: Path) -> None:
    # script-src hashes do not cover on*= attributes or javascript: URLs (they need
    # 'unsafe-inline' / 'unsafe-hashes'), so a page carrying one would break under this CSP
    bad = re.compile(r"""<[a-z][^>]*\s(on[a-z]+\s*=|href\s*=\s*["']?\s*javascript:)""", re.I)
    for f in page_files(out_dir):
        m = bad.search(f.read_text(encoding="utf-8"))
        assert m is None, f"{f.name}: {m.group(0)[:80]!r}"


# ----------------------------------------------------------------------- mutation: it can fail


def _copy_out(out_dir: Path, tmp: Path) -> Path:
    dst = tmp / "out"
    shutil.copytree(out_dir, dst)
    return dst


def test_security_a_planted_inline_script_is_not_in_script_src(
    out_dir: Path, headers: dict[str, str], tmp_path: Path
) -> None:
    copy = _copy_out(out_dir, tmp_path)
    page = copy / "lab" / "index.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "</body>", "<script>window.__planted=1</script></body>"
        ),
        encoding="utf-8",
    )
    srcs = parse_csp(headers["Content-Security-Policy"])["script-src"]
    missing = unlisted_hashes(copy, srcs)
    assert missing == {"lab/index.html": {csp_hash("window.__planted=1")}}


def test_security_a_changed_inline_script_changes_its_hash(out_dir: Path, tmp_path: Path) -> None:
    copy = _copy_out(out_dir, tmp_path)
    page = copy / "index.html"
    before = inline_script_hashes(page.read_text(encoding="utf-8"))
    text = page.read_text(encoding="utf-8")
    first = next(iter(re.findall(r"<script>([^<]{8,})</script>", text)))
    page.write_text(text.replace(first, first + " ", 1), encoding="utf-8")
    assert inline_script_hashes(page.read_text(encoding="utf-8")) != before


def test_security_non_executable_and_external_scripts_need_no_hash() -> None:
    html = (
        '<script src="/a.js"></script>'
        '<script type="application/json">{"a":1}</script>'
        '<script type="application/ld+json">{}</script>'
        "<script>   </script>"
        '<script type="module">import 1</script>'
        "<script>x=1</script>"
    )
    assert inline_script_hashes(html) == {csp_hash("import 1"), csp_hash("x=1")}


def test_security_csp_hash_matches_a_known_value() -> None:
    # sha256("") is e3b0c442...; its base64 is 47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=
    assert csp_hash("") == "'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='"


def _spec_policy() -> str:
    parts = [f"{n} {' '.join(v)}".strip() for n, v in CSP_FIXED.items()]
    return "; ".join([*parts, "script-src 'self' 'sha256-AAAA'"])


def test_security_csp_problems_accepts_the_spec_and_rejects_each_weakening() -> None:
    assert csp_problems(_spec_policy()) == []
    weakened = {
        "unsafe-inline in script-src": _spec_policy().replace(
            "script-src 'self'", "script-src 'self' 'unsafe-inline'"
        ),
        "unsafe-eval": _spec_policy().replace(
            "script-src 'self'", "script-src 'self' 'unsafe-eval'"
        ),
        "remote script origin": _spec_policy().replace(
            "script-src 'self'", "script-src 'self' https://cdn.example.com"
        ),
        "wildcard default-src": _spec_policy().replace("default-src 'self'", "default-src *"),
        "frames allowed": _spec_policy().replace("frame-ancestors 'none'", "frame-ancestors *"),
        "no hashes": "; ".join(_spec_policy().split("; ")[:-1] + ["script-src 'self'"]),
        "extra directive": _spec_policy() + "; worker-src blob:",
        "missing directive": _spec_policy().replace("base-uri 'self'; ", ""),
    }
    for label, value in weakened.items():
        assert csp_problems(value), f"csp_problems missed: {label}"
