"""Tweak panel, static half: the dev-only panel must not ship (task 7, spec section 8.2).

Pass if: the sentinel QDAY_TWEAK_PANEL is in the panel module and absent from every file of out/
and of the copy Vercel serves; AND the panel's runtime strings (which survive minification) are
absent too. The second part exists because the sentinel lives in a source COMMENT: a minifier drops
comments, so a panel that did ship would still lack the sentinel, and "sentinel absent" alone could
pass on a build that contains the panel. Measured (reviewer, 2026-11-08, Next 16.4.5): a probe
client component built into out/ lost its comment sentinel and kept its aria-label and button text.
The in-browser half (the panel appears on /?tweak under
`npm run dev`, never on a production build) is tests/phase5/test_tweak_panel_browser.py.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .helpers import WEB

SENTINEL = "QDAY_TWEAK_PANEL"
PANEL = WEB / "src" / "components" / "dev" / "TweakPanel.tsx"
LOADER = WEB / "src" / "components" / "TweakLoader.tsx"
# strings the panel renders; JSX attribute values and text survive minification
RUNTIME_STRINGS = ("Design tweaks (development only)", "Copy tokens")
VERCEL_STATIC = WEB / ".vercel" / "output" / "static"


def tweak_leaks(root: Path) -> dict[str, list[str]]:
    """{file: [what leaked]} for the sentinel or any runtime string anywhere under root. Files are
    read as latin-1 so a string cannot hide in a binary or in a source map."""
    needles = (SENTINEL, *RUNTIME_STRINGS)
    found: dict[str, list[str]] = {}
    for p in sorted(q for q in root.rglob("*") if q.is_file()):
        text = p.read_bytes().decode("latin-1")
        hit = [n for n in needles if n in text]
        if hit:
            found[str(p.relative_to(root))] = hit
    return found


# ------------------------------------------------------------------- the panel is real


def test_tweak_the_sentinel_and_runtime_strings_are_in_the_panel_source() -> None:
    src = PANEL.read_text(encoding="utf-8")
    assert SENTINEL in src
    for s in RUNTIME_STRINGS:
        assert s in src, f"the test checks for {s!r} but the panel no longer contains it"


def test_tweak_the_sentinel_is_only_in_the_panel_module() -> None:
    in_src = [
        str(p.relative_to(WEB))
        for p in (WEB / "src").rglob("*")
        if p.is_file() and SENTINEL in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert in_src == [str(PANEL.relative_to(WEB))]


# --------------------------------------------------------------- gated and never imported


def test_tweak_the_loader_gates_on_development_and_imports_dynamically() -> None:
    code = LOADER.read_text(encoding="utf-8")
    assert 'process.env.NODE_ENV === "development"' in code
    # the import must sit inside the gated branch, so the production build removes it
    gate = code.index('process.env.NODE_ENV === "development"')
    dyn = code.index('import("./dev/TweakPanel")')
    assert gate < dyn
    assert re.search(r"\.has\(\s*[\"']tweak[\"']\s*\)", code), "/?tweak is the only trigger"


def test_tweak_nothing_imports_the_panel_statically() -> None:
    static_import = re.compile(
        r"""^\s*import\s[^;]*\bfrom\s+["'][^"']*TweakPanel["']|^\s*import\s+["'][^"']*TweakPanel["']""",
        re.M,
    )
    offenders = [
        str(p.relative_to(WEB))
        for p in (WEB / "src").rglob("*")
        if p.suffix in {".ts", ".tsx", ".js", ".jsx"}
        and static_import.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_tweak_no_tweak_library_is_a_production_dependency() -> None:
    pkg = json.loads((WEB / "package.json").read_text())
    prod = set(pkg.get("dependencies", {}))
    assert not prod & {"leva", "tweakpane", "dat.gui", "lil-gui"}, prod


# ------------------------------------------------------------------- absent from the build


def test_tweak_the_panel_is_absent_from_out(out_dir: Path) -> None:
    assert tweak_leaks(out_dir) == {}


def test_tweak_the_panel_is_absent_from_the_copy_vercel_serves(out_dir: Path) -> None:
    assert VERCEL_STATIC.is_dir(), f"{VERCEL_STATIC} missing: the build must write it"
    assert tweak_leaks(VERCEL_STATIC) == {}


# ------------------------------------------------------------------- the check can fail


def test_tweak_a_planted_sentinel_or_panel_string_is_caught(out_dir: Path, tmp_path: Path) -> None:
    copy = tmp_path / "out"
    shutil.copytree(out_dir, copy)
    assert tweak_leaks(copy) == {}
    js = next(copy.rglob("*.js"))
    js.write_text(js.read_text(encoding="utf-8") + f"\n/*{SENTINEL}*/\n", encoding="utf-8")
    assert tweak_leaks(copy) == {str(js.relative_to(copy)): [SENTINEL]}
    # the case the sentinel alone would miss: the panel shipped, comment stripped by the minifier
    js.write_text(js.read_text(encoding="utf-8").replace(f"/*{SENTINEL}*/", ""), encoding="utf-8")
    html = copy / "index.html"
    html.write_text(
        html.read_text(encoding="utf-8") + '<aside aria-label="Design tweaks (development only)">',
        encoding="utf-8",
    )
    assert tweak_leaks(copy) == {"index.html": ["Design tweaks (development only)"]}
    # and a string hidden in a binary file
    font = next(copy.rglob("*.woff2"))
    font.write_bytes(font.read_bytes() + b"\x00Copy tokens\x00")
    assert str(font.relative_to(copy)) in tweak_leaks(copy)
