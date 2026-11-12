"""Helpers for the Phase 6 tests. Owned by reviewer. No network, no browser.

This file must not name a removed path (a kept file that does is a dead pointer in the public
repo); the list of removed paths is read from the publish script, whose own list a `public` test
compares with the decided one.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
READMES = [
    "README.md",
    "quantum/README.md",
    "web/README.md",
    "tests/README.md",
    "results/README.md",
    "scripts/README.md",
    "benchmarks/README.md",
]
LIVE_URL = "https://q-day-web-q-day.vercel.app"


def _load_make_public():
    spec = importlib.util.spec_from_file_location(
        "make_public_for_tests", ROOT / "scripts/make_public.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REMOVED = list(_load_make_public().REMOVED_PATHS)


def is_removed(path: str) -> bool:
    return any(path == r or path.startswith(r + "/") for r in REMOVED)


def kept_files(root: Path = ROOT) -> list[str]:
    """Tracked and not-yet-tracked (but not ignored) files that are not under a removed path."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return sorted({p for p in out if p and not is_removed(p) and (root / p).exists()})


# ------------------------------------------------------------------ markdown


def strip_fences(text: str) -> str:
    """Text with fenced code blocks blanked (line count kept)."""
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            out.append("")
        else:
            out.append("" if fence else line)
    return "\n".join(out)


def slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, drop punctuation except - and space, spaces to -."""
    h = heading.strip().lstrip("#").strip().lower()
    h = re.sub(r"[`*_]", "", h)
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(text: str) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    for line in strip_fences(text).splitlines():
        if re.match(r"#{1,6}\s", line):
            s = slug(line)
            n = seen.get(s, 0)
            out.add(s if n == 0 else f"{s}-{n}")
            seen[s] = n + 1
    return out


LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
REFDEF = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.M)


def link_targets(text: str) -> list[str]:
    body = strip_fences(text)
    return LINK.findall(body) + AUTOLINK.findall(body) + REFDEF.findall(body)
