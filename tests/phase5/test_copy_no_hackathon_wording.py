"""No hackathon, submission or judging wording in README.md or web/ (lead, 2026-11-08).

Q-Day Radar is a personal project that started at Qiskit Fall Fest 2026; it is not an entry. So the
words a competition entry would use must not appear in what a visitor reads or in the source behind
it. "Qiskit Fall Fest" itself is allowed (CLAUDE.md states the project's origin that way). The scan
covers README.md and web/ except dependencies, build output and the lockfile. A mutation test plants
each banned word in a temp tree and checks the scanner finds it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from .helpers import REPO, WEB

BANNED = {
    "hackathon": r"hackathon",
    "submission": r"submissions?\b",
    "advanced track": r"advanced\s+track",
    "judging": r"\bjudg(?:e|es|ed|ing|ement|ements)\b",
    "competition": r"\bcompetitions?\b",
    "prize": r"\bprizes?\b",
}
SKIP_DIRS = {"node_modules", ".next", "out", ".vercel", ".turbo", "__pycache__"}
SKIP_FILES = {"package-lock.json"}
TEXT_SUFFIXES = {
    ".md", ".mdx", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".json", ".txt",
    ".html", ".svg", ".yml", ".yaml", ".toml", "",
}  # fmt: skip


def scan(root: Path, files: list[Path] | None = None) -> dict[str, list[str]]:
    """{file: [banned word, ...]} for every text file under root (or the given files)."""
    found: dict[str, list[str]] = {}
    paths = files if files is not None else sorted(p for p in root.rglob("*") if p.is_file())
    for p in paths:
        if (
            SKIP_DIRS & set(p.parts)
            or p.name in SKIP_FILES
            or p.suffix.lower() not in TEXT_SUFFIXES
        ):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        hits = [name for name, rx in BANNED.items() if re.search(rx, text, re.I)]
        if hits:
            found[str(p.relative_to(root) if root in p.parents else p)] = hits
    return found


def test_copy_readme_and_web_have_no_hackathon_or_judging_wording() -> None:
    found = scan(WEB)
    found.update(scan(REPO, [REPO / "README.md"]))
    assert found == {}, found


def test_copy_the_scan_actually_reads_the_web_tree_and_the_readme() -> None:
    # a scan over an empty or wrong directory would pass for the wrong reason
    web_files = [p for p in WEB.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.parts)]
    assert len(web_files) > 30, f"only {len(web_files)} files under {WEB}: wrong path?"
    assert (REPO / "README.md").read_text(encoding="utf-8").strip()
    assert any(p.suffix == ".tsx" for p in web_files), "no page source was scanned"


def test_copy_the_origin_sentence_is_allowed() -> None:
    assert "Fall Fest" not in "".join(BANNED.values())
    sample = "A personal project, started at Qiskit Fall Fest 2026."
    assert not any(re.search(rx, sample, re.I) for rx in BANNED.values())


@pytest.mark.parametrize(
    ("word", "sample"),
    [
        ("hackathon", "Built for a Hackathon"),
        ("submission", "our submission to the event"),
        ("advanced track", "Advanced  Track entry"),
        ("judging", "scored by the judges"),
        ("competition", "this competition"),
        ("prize", "a prize winner"),
    ],
)
def test_copy_the_scan_catches_each_banned_word(tmp_path: Path, word: str, sample: str) -> None:
    (tmp_path / "page.tsx").write_text(f"<p>{sample}</p>")
    (tmp_path / "clean.tsx").write_text("<p>A personal project.</p>")
    assert scan(tmp_path) == {"page.tsx": [word]}


def test_copy_the_scan_skips_dependencies_and_build_output(tmp_path: Path) -> None:
    for d in ("node_modules", ".next", "out"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "x.js").write_text("hackathon")
    (tmp_path / "package-lock.json").write_text("hackathon")
    assert scan(tmp_path) == {}
