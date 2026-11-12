"""`wording`: no hackathon, submission or judging language in the READMEs or the site.

The project is personal; it started at Qiskit Fall Fest 2026 and is not an entry. Scope (phase
brief): the seven READMEs, `web/src` and the built site `web/out`. The phrase "Qiskit Fall Fest"
is allowed. The scan here is stricter than a word list: it matches the stems, so "judgement" and
"submissions" are found too. Planted defects: each banned word, in each place, in three spellings.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.phase6 import helpers as h

BANNED = re.compile(r"hackathon|submission|advanced[ -]track|\bjudg\w*", re.I)
SITE_SUFFIXES = {
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".css",
    ".md",
    ".mdx",
    ".html",
    ".txt",
    ".json",
    ".svg",
}


def hits_in(path: Path) -> list[str]:
    out = []
    for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
        for m in BANNED.finditer(line.replace("Qiskit Fall Fest", "")):
            out.append(f"{path.name}:{i} {m.group(0)!r}")
    return out


def scan(root: Path) -> list[str]:
    files = [root / r for r in h.READMES if (root / r).is_file()]
    for base in (root / "web" / "src", root / "web" / "out"):
        if base.is_dir():
            files += [p for p in base.rglob("*") if p.is_file() and p.suffix in SITE_SUFFIXES]
    hits = []
    for f in files:
        hits += [f"{f.relative_to(root)}: {x}" for x in hits_in(f)]
    return hits


def test_wording_readmes_and_site_are_clean():
    assert (h.ROOT / "web" / "out").is_dir(), "web/out is missing: build the site first"
    assert scan(h.ROOT) == []


def test_wording_the_scan_covers_the_files_it_claims_to():
    seen = [r for r in h.READMES if (h.ROOT / r).is_file()]
    assert seen == h.READMES
    assert any((h.ROOT / "web" / "src").rglob("*.tsx"))
    assert any((h.ROOT / "web" / "out").rglob("*.html"))


WORDS = [
    "hackathon",
    "Hackathon",
    "HACKATHON",
    "submission",
    "Submissions",
    "advanced track",
    "Advanced-Track",
    "judge",
    "judges",
    "Judging",
    "judgement",
]


def _tree(tmp_path: Path, place: str, word: str) -> Path:
    for r in h.READMES:
        (tmp_path / r).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / r).write_text("# fine\nnothing here\n")
    for sub in ("web/src/app", "web/out"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    target = {
        "readme": tmp_path / "quantum" / "README.md",
        "src": tmp_path / "web" / "src" / "app" / "page.tsx",
        "out": tmp_path / "web" / "out" / "index.html",
    }[place]
    target.write_text(f"before\nthe word {word} here\n")
    return tmp_path


@pytest.mark.parametrize("place", ["readme", "src", "out"])
@pytest.mark.parametrize("word", WORDS)
def test_wording_defect_each_banned_word_is_found_everywhere(tmp_path, place, word):
    assert scan(_tree(tmp_path, place, word)), f"{word!r} in {place} was not found"


def test_wording_the_allowed_phrase_is_not_flagged(tmp_path):
    tree = _tree(tmp_path, "readme", "Qiskit Fall Fest 2026")
    assert scan(tree) == []


def test_wording_site_files_outside_the_scope_are_not_read(tmp_path):
    tree = _tree(tmp_path, "readme", "plain")
    (tree / "web" / "node_modules" / "x").mkdir(parents=True)
    (tree / "web" / "node_modules" / "x" / "a.js").write_text("hackathon")
    assert scan(tree) == []
