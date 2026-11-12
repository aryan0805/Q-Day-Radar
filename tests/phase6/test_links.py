"""`links`: every link in the seven READMEs resolves inside the public repo.

Rules (from the phase brief): a relative link must point at a file or folder that is kept (not
removed, not missing), with a heading anchor that exists in the target Markdown file; external
links are not fetched here (the gate does that, listing bot walls); a link into the private
development repository would be a dead end for a visitor. Planted defects: a missing file, a
removed path, a wrong anchor, a link that escapes the repository, a link to the private repo, and
a mail link.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.phase6 import helpers as h

PRIVATE_REPO = re.compile(r"github\.com/aryan0805/Q-Day(?![\w-])", re.I)


def link_problems(readme_rel: str, text: str, files: set[str], root: Path = h.ROOT) -> list[str]:
    """What is wrong with the links of one README (given its text and the kept file set)."""
    base = (root / readme_rel).parent
    dirs = {str(Path(p).parent.as_posix()) for p in files} | {
        q.as_posix() for p in files for q in Path(p).parents
    }
    problems = []
    own = h.anchors(text)
    for target in h.link_targets(text):
        if target.startswith(("http://", "https://")):
            if PRIVATE_REPO.search(target):
                problems.append(f"{target}: points into the private repository")
            if target.startswith("http://"):
                problems.append(f"{target}: not https")
            continue
        if target.startswith(("mailto:", "tel:")):
            problems.append(f"{target}: a mail link (no address is published)")
            continue
        path, _, anchor = target.partition("#")
        if not path:
            if anchor and anchor not in own:
                problems.append(f"#{anchor}: no such heading here")
            continue
        try:
            dest = (base / path).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            problems.append(f"{target}: leaves the repository")
            continue
        dest = dest.rstrip("/") or "."
        if h.is_removed(dest):
            problems.append(f"{target}: points at a removed path")
        elif dest not in files and dest not in dirs:
            problems.append(f"{target}: no such kept file or folder")
        elif anchor and dest.endswith(".md"):
            if anchor not in h.anchors((root / dest).read_text()):
                problems.append(f"{target}: no such heading in {dest}")
    return problems


@pytest.fixture(scope="module")
def files() -> set[str]:
    return set(h.kept_files())


@pytest.mark.parametrize("rel", h.READMES)
def test_links_every_link_in_each_readme_resolves(rel, files):
    assert (h.ROOT / rel).is_file(), f"{rel} is missing"
    assert link_problems(rel, (h.ROOT / rel).read_text(), files) == []


def test_links_root_readme_links_every_folder_readme_and_the_live_site(files):
    text = (h.ROOT / "README.md").read_text()
    targets = {t.split("#")[0] for t in h.link_targets(text)}
    for rel in h.READMES[1:]:
        assert rel in targets, f"README.md does not link {rel}"
    assert h.LIVE_URL in targets or any(t.rstrip("/") == h.LIVE_URL for t in targets)


def test_links_no_readme_points_at_a_file_that_is_not_kept(files):
    for rel in h.READMES:
        for t in h.link_targets((h.ROOT / rel).read_text()):
            if t.startswith(("http", "#", "mailto")):
                continue
            dest = (h.ROOT / rel).parent.joinpath(t.partition("#")[0]).resolve()
            assert not h.is_removed(dest.relative_to(h.ROOT).as_posix()), (rel, t)


# ------------------------------------------------------------------ the checker catches defects

FILES = {"README.md", "quantum/a.py", "tests/README.md"}


def _check(text: str, readme: str = "README.md", files: set[str] = FILES) -> list[str]:
    return link_problems(readme, text, files)


def test_links_checker_accepts_good_links():
    good = "# Title\n[a](quantum/a.py) [d](quantum/) [s](#title) [e](https://example.org/x)"
    assert _check(good) == []
    # a real anchor in a real file: the heading "# tests" of tests/README.md
    assert link_problems("README.md", "[h](tests/README.md#tests)", {"tests/README.md"}) == []


def test_links_defect_missing_file_is_reported():
    assert _check("[x](quantum/missing.py)")


def test_links_defect_removed_path_is_reported():
    removed = h.REMOVED[0]
    assert any("removed" in p for p in _check(f"[x]({removed}/anything.md)"))


def test_links_defect_wrong_anchor_is_reported():
    assert any("no such heading" in p for p in _check("# Real\n[x](#nope)"))
    # and in another file: the real tests README has no heading called 'nope'
    assert any(
        "no such heading" in p
        for p in link_problems("README.md", "[x](tests/README.md#nope)", {"tests/README.md"})
    )


def test_links_defect_escaping_the_repository_is_reported():
    assert any("leaves" in p for p in _check("[x](../../etc/passwd)"))


def test_links_defect_private_repo_and_mail_and_plain_http_are_reported():
    assert any("private" in p for p in _check("[x](https://github.com/aryan0805/Q-Day)"))
    assert not any("private" in p for p in _check("[x](https://github.com/aryan0805/q-day-radar)"))
    assert any("mail" in p for p in _check("[x](mailto:someone@example.org)"))
    assert any("https" in p for p in _check("[x](http://example.org)"))


def test_links_links_inside_code_fences_are_not_checked():
    assert _check("```\n[x](quantum/missing.py)\n```\n") == []


def test_links_reference_style_and_autolinks_are_checked():
    assert _check("[x][r]\n\n[r]: quantum/missing.py\n")
    assert any("private" in p for p in _check("<https://github.com/aryan0805/Q-Day>"))


def test_links_anchor_slugs_follow_github_rules():
    assert h.slug("How this was built") == "how-this-was-built"
    assert h.slug("## Run them (fast)") == "run-them-fast"
    assert h.anchors("# A\n## A\n") == {"a", "a-1"}
