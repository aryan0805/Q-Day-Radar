"""`norefs`: no kept file names a removed path or file (a dead pointer in the public repo).

Names (phase brief): `.coord`, `docs/`, `CLAUDE.md`, `.claude`, `coord.py`, `team.sh`,
`install-claude-config`, `setup/claude`, `STATE.md`, `PLAN.md`, `DECISIONS(.md)`, `WORKFLOW.md`,
`TWEAKS.md`, `PHASE5-DESIGN.md`. Exempt: `.gitignore`, `scripts/gate.py`, `scripts/make_public.py`,
the `public` and `norefs` tests, and raw files under `results/` (immutable; its README is checked).

This file is exempt because it has to name them. The patterns are written here independently of the
gate's. Planted defects: every name in a kept file, the same name in each exempt place (must NOT be
flagged) and look-alikes that must not be flagged either (`docsite/`, `.coordinates`).
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

from tests.phase6 import helpers as h

NAMES = {
    ".coord": r"(?<![\w.])\.coord\b",
    "docs/": r"(?<![\w./-])docs/",
    "CLAUDE.md": r"\bCLAUDE\.md\b",
    ".claude": r"(?<![\w.])\.claude\b",
    "coord.py": r"\bcoord\.py\b",
    "team.sh": r"\bteam\.sh\b",
    "install-claude-config": r"install-claude-config",
    "setup/claude": r"setup/claude(?![\w-])",
    "STATE.md": r"\bSTATE\.md\b",
    "PLAN.md": r"\bPLAN\.md\b",
    "DECISIONS": r"\bDECISIONS\b",
    "WORKFLOW.md": r"\bWORKFLOW\.md\b",
    "TWEAKS.md": r"\bTWEAKS\.md\b",
    "PHASE5-DESIGN.md": r"\bPHASE5-DESIGN\.md\b",
}
PATTERN = re.compile("|".join(NAMES.values()))
EXEMPT = [
    ".gitignore",
    "scripts/gate.py",
    "scripts/make_public.py",
    "tests/phase6/test_public_*.py",
    "tests/phase6/test_norefs*.py",
]


def exempt(rel: str) -> bool:
    return (
        any(fnmatch.fnmatch(rel, g) for g in EXEMPT)
        or rel.endswith(".lock")
        or rel.endswith("package-lock.json")
        or (rel.startswith("results/") and rel != "results/README.md")
    )


def references(root: Path, files: list[str]) -> list[str]:
    hits = []
    for rel in files:
        if exempt(rel):
            continue
        try:
            text = (root / rel).read_text()
        except (UnicodeDecodeError, OSError):
            continue  # binary: a font, a PNG
        for i, line in enumerate(text.splitlines(), 1):
            if m := PATTERN.search(line):
                hits.append(f"{rel}:{i} {m.group(0)!r}")
    return hits


def test_norefs_no_kept_file_names_a_removed_path():
    files = h.kept_files()
    assert len(files) > 200, "the kept file list looks wrong"
    assert references(h.ROOT, files) == []


def test_norefs_the_kept_list_excludes_removed_paths_and_includes_new_files():
    files = set(h.kept_files())
    for r in h.REMOVED:
        assert not any(f == r or f.startswith(r + "/") for f in files), r
    assert "tests/README.md" in files and "scripts/make_public.py" in files


def test_norefs_the_list_of_names_covers_every_removed_path():
    """Each removed path's own name must match one of the patterns."""
    for removed in h.REMOVED:
        sample = removed + "/x" if "." not in Path(removed).name else removed
        assert PATTERN.search(sample), f"no pattern would catch a mention of {removed}"


def test_norefs_matches_the_gates_own_scan():
    """Two independent implementations must agree on the real repository."""
    import sys

    sys.path.insert(0, str(h.ROOT / "scripts"))
    import gate

    ok, detail = gate.p6_no_refs_to_removed()
    assert ok, detail


# ------------------------------------------------------------------ planted defects


def _kept(tmp_path: Path, rel: str, line: str) -> list[str]:
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"first line\n{line}\nlast\n")
    return [rel]


MENTIONS = [
    "see .coord/LOG for the log",
    "read docs/PLAN.md first",
    "see CLAUDE.md",
    "settings in .claude/settings.json",
    "run scripts/coord.py log",
    "start with scripts/team.sh",
    "bash scripts/install-claude-config.sh",
    "copied from setup/claude/agents",
    "as in STATE.md",
    "in PLAN.md Phase 3",
    "see DECISIONS for why",
    "per WORKFLOW.md",
    "listed in TWEAKS.md",
    "the PHASE5-DESIGN.md spec",
]


@pytest.mark.parametrize("line", MENTIONS)
@pytest.mark.parametrize("rel", ["quantum/x.py", "README.md", "web/src/a.tsx", "results/README.md"])
def test_norefs_defect_each_name_in_a_kept_file_is_found(tmp_path, line, rel):
    assert references(tmp_path, _kept(tmp_path, rel, line)), f"{line!r} in {rel} not found"


@pytest.mark.parametrize(
    "rel",
    [
        ".gitignore",
        "scripts/gate.py",
        "scripts/make_public.py",
        "tests/phase6/test_public_x.py",
        "tests/phase6/test_norefs_x.py",
        "results/hardware/raw.json",
        "web/package-lock.json",
        "uv.lock",
    ],
)
def test_norefs_exempt_files_may_name_them(tmp_path, rel):
    assert references(tmp_path, _kept(tmp_path, rel, "mentions .coord/ and docs/PLAN.md")) == []


@pytest.mark.parametrize(
    "line",
    [
        "the docsite/ folder",
        "my-docs/ are elsewhere",
        "docs are documentation",
        ".coordinates",
        "the coordinator",
        "a plan.md file",
        "COORDINATE",
        "stated in the plan",
        "decisions were made",
        "setup/claude-extra.txt is a different name",
    ],
)
def test_norefs_look_alikes_are_not_flagged(tmp_path, line):
    assert references(tmp_path, _kept(tmp_path, "README.md", line)) == []
