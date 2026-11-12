"""`public`: scripts/make_public.py on a scratch repo whose history holds all eight removed paths.

Falsifying checks (fixed by the phase brief before BUILD):
  * no removed path in ANY commit of ANY ref of the output (history, not just the tip);
  * every other file byte-identical: (mode, blob, path) of every kept ref equals the source's minus
    the removed paths, and every distinct kept tree in the history survives;
  * the phase-N-done tags are kept; no other branch or tag is;
  * a dry run (no --push) writes to no remote; `--push` refuses the source's own origin.

The scratch repo is built with traps: names that merely START like a removed path (`docsite/`,
`setup/claude-extra.txt`, `scripts/coord.py.md`), an executable file, a binary blob holding every
byte value, a file with spaces in its name, a removed path that exists only in an old commit, a
removed path that comes back later, a commit that touches only removed paths, an extra branch and
an extra tag. Each checker also gets planted defects that it must report: a checker that finds
nothing wrong in a broken output would be worth nothing.

Needs `git-filter-repo` and `gitleaks` on PATH. A machine without them FAILS here (never skips):
the gate needs them too.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKE_PUBLIC = ROOT / "scripts" / "make_public.py"

# The decided list, written here independently of the script (the script's own list is compared
# to it below). The gate keeps a third copy.
REMOVED = [
    ".claude",
    "docs",
    "CLAUDE.md",
    ".coord",
    "setup/claude",
    "scripts/coord.py",
    "scripts/team.sh",
    "scripts/install-claude-config.sh",
]
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Scratch",
    "GIT_AUTHOR_EMAIL": "scratch@example.org",
    "GIT_COMMITTER_NAME": "Scratch",
    "GIT_COMMITTER_EMAIL": "scratch@example.org",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}
NOREPLY = "12345+scratch@users.noreply.github.com"


def git(repo: Path, *args: str, check: bool = True, env: dict | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env or ENV)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def is_removed(path: str) -> bool:
    return any(path == r or path.startswith(r + "/") for r in REMOVED)


# ------------------------------------------------------------------ the checkers under test


def history_removed(repo: Path) -> list[str]:
    """Removed paths in any commit of any ref (every path ever touched, plus every ref's tree)."""
    seen = {
        p
        for p in git(repo, "log", "--all", "--name-only", "--format=", "--no-renames").splitlines()
        if p
    }
    for ref in git(repo, "for-each-ref", "--format=%(refname)").split():
        seen |= {
            line.split("\t", 1)[1]
            for line in git(repo, "ls-tree", "-r", ref).splitlines()
            if "\t" in line
        }
    return sorted(p for p in seen if is_removed(p))


def kept_listing(repo: Path, rev: str) -> list[str]:
    """`mode blob path` of every file at `rev` that is not under a removed path, sorted."""
    out = []
    for line in git(repo, "ls-tree", "-r", rev).splitlines():
        meta, path = line.split("\t", 1)
        mode, _kind, blob = meta.split()
        if not is_removed(path):
            out.append(f"{mode} {blob} {path}")
    return sorted(out)


def distinct_kept_trees(repo: Path, rev: str) -> set[str]:
    trees = set()
    for c in git(repo, "rev-list", rev).split():
        trees.add(hashlib.sha256("\n".join(kept_listing(repo, c)).encode()).hexdigest())
    return trees


def refs(repo: Path) -> list[str]:
    return sorted(git(repo, "for-each-ref", "--format=%(refname)").split())


def emails(repo: Path) -> set[str]:
    """Every identity address in any ref: author, committer and the tagger of annotated tags."""
    found = set(git(repo, "log", "--all", "--format=%ae%n%ce").split())
    taggers = git(repo, "for-each-ref", "--format=%(taggeremail)", "refs/tags").split()
    return found | {t.strip("<>") for t in taggers}


def local_email_problem(repo: Path, target: str) -> str | None:
    """The output repo's own `user.email` (repository-local config) must be the rewrite target."""
    got = git(repo, "config", "--local", "--get", "user.email", check=False).strip()
    return None if got == target else f"local user.email is {got!r}, not {target!r}"


def public_problems(source: Path, public: Path, *, rewritten_email: str | None = None) -> list[str]:
    """Everything wrong with `public` as a publication of `source` (empty list = fine)."""
    problems = []
    left = history_removed(public)
    if left:
        problems.append(f"removed paths survive: {left[:4]}")
    want = {"refs/heads/main"} | {
        r for r in refs(source) if r.startswith("refs/tags/phase-") and r.endswith("-done")
    }
    if set(refs(public)) != want:
        problems.append(f"refs {refs(public)} != wanted {sorted(want)}")
    for r in sorted(want & set(refs(public))):
        if kept_listing(source, r) != kept_listing(public, r):
            problems.append(f"{r}: kept files differ from the source's")
    if distinct_kept_trees(source, "refs/heads/main") != distinct_kept_trees(
        public, "refs/heads/main"
    ):
        problems.append("the set of kept trees in main's history differs from the source's")
    want_mail = {rewritten_email} if rewritten_email else emails(source)
    if emails(public) != want_mail:
        problems.append(f"e-mails {sorted(emails(public))} != {sorted(want_mail)}")
    return problems


# ------------------------------------------------------------------ the scratch source repo


def _write(repo: Path, rel: str, data: str | bytes, mode: int | None = None) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data.encode() if isinstance(data, str) else data)
    if mode:
        p.chmod(mode)


OTHER = "other@example.net"  # a second identity, so author and committer can differ


def _commit(repo: Path, msg: str, when: str, author: str | None = None) -> None:
    git(repo, "add", "-A")
    env = {**ENV, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    if author:
        env["GIT_AUTHOR_EMAIL"] = author
    git(repo, "commit", "-q", "-m", msg, env=env)


def build_source(base: Path) -> Path:
    repo = base / "source"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    # c1: everything, including all eight removed paths
    _write(repo, "README.md", "scratch\n")
    _write(repo, "quantum/a.py", "A = 1\n")
    _write(repo, "scripts/run.sh", "#!/bin/sh\necho hi\n", 0o755)
    _write(repo, "scripts/coord.py", "removed\n")
    _write(repo, "scripts/team.sh", "removed\n", 0o755)
    _write(repo, "scripts/install-claude-config.sh", "removed\n")
    _write(repo, "scripts/coord.py.md", "kept: only the exact path scripts/coord.py is removed\n")
    _write(repo, "CLAUDE.md", "removed\n")
    _write(repo, "docs/PLAN.md", "removed\n")
    _write(repo, "docsite/index.md", "kept: a folder that only starts like docs\n")
    _write(repo, ".coord/STATE.md", "removed\n")
    _write(repo, ".coord/LOG.md", "removed\n")
    _write(repo, ".claude/settings.json", "{}\n")
    _write(repo, "setup/claude/agents/x.md", "removed\n")
    _write(repo, "setup/claude-extra.txt", "kept\n")
    _write(repo, "setup/keep/y.txt", "kept\n")
    _write(repo, "results/raw.json", '{"counts": {"00": 5}}\n')
    _write(repo, "web/with space.txt", "kept\n")
    _write(repo, "web/blob.bin", bytes(range(256)) * 4)
    _commit(repo, "c1 first", "2026-01-01T10:00:00+00:00")
    git(repo, "tag", "phase-1-done")
    # c2: kept change, a removed path is deleted for good, another is edited
    _write(repo, "quantum/a.py", "A = 2\n")
    shutil.rmtree(repo / ".claude")
    _write(repo, "CLAUDE.md", "removed, edited\n")
    _commit(repo, "c2 second", "2026-01-02T10:00:00+00:00")
    git(repo, "tag", "-a", "-m", "second phase", "phase-2-done")
    git(repo, "tag", "private-note")
    # c3: touches only removed paths (its kept tree equals c2's)
    _write(repo, "docs/NEW.md", "removed\n")
    _write(repo, ".coord/LOG.md", "removed, longer\n")
    _commit(repo, "c3 only removed paths", "2026-01-03T10:00:00+00:00")
    # c4: kept change, a removed folder returns
    _write(repo, "quantum/b.py", "B = 1\n")
    _write(repo, ".claude/again.json", "{}\n")
    _commit(repo, "c4 fourth", "2026-01-04T10:00:00+00:00", author=OTHER)
    git(
        repo,
        "tag",
        "-a",
        "-m",
        "third phase",
        "phase-3-done",
        env={**ENV, "GIT_COMMITTER_EMAIL": OTHER},
    )
    git(repo, "branch", "feature")
    # origin: a bare repo standing in for the private remote
    private = base / "private-origin.git"
    git(base, "init", "-q", "--bare", str(private))
    git(repo, "remote", "add", "origin", str(private))
    git(repo, "push", "-q", "origin", "main")
    return repo


def run_make_public(source: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MAKE_PUBLIC), "--source", str(source), *extra],
        capture_output=True,
        text=True,
        env=ENV,
    )


def dry_run_leaks(source: Path, script: Path = MAKE_PUBLIC) -> list[str]:
    """Dry-run `script` on `source`; the refs of the source and its origin must not move."""
    origin = source.parent / "private-origin.git"
    before = (refs(source), refs(origin))
    subprocess.run(
        [sys.executable, str(script), "--source", str(source)],
        capture_output=True,
        text=True,
        env=ENV,
    )
    after = (refs(source), refs(origin))
    return [] if before == after else [f"refs moved: {before} -> {after}"]


def kept_dir(cp: subprocess.CompletedProcess) -> Path:
    lines = [ln for ln in cp.stdout.splitlines() if ln.startswith("kept: ")]
    assert lines, f"no 'kept:' line.\nstdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
    return Path(lines[-1][len("kept: ") :])


@pytest.fixture(scope="module")
def tools():
    missing = [t for t in ("git-filter-repo", "gitleaks") if shutil.which(t) is None]
    assert not missing, f"{missing} not on PATH: brew install git-filter-repo gitleaks"


@pytest.fixture(scope="module")
def scratch(tmp_path_factory, tools):
    return build_source(tmp_path_factory.mktemp("public"))


@pytest.fixture(scope="module")
def dry(scratch, tools):
    """One dry run, output kept for inspection. Also records the remotes before and after."""
    origin = scratch.parent / "private-origin.git"
    before = (refs(scratch), refs(origin))
    cp = run_make_public(scratch, "--keep")
    after = (refs(scratch), refs(origin))
    out = kept_dir(cp) if cp.returncode == 0 else None
    yield {"cp": cp, "out": out, "before": before, "after": after}
    if out is not None:
        shutil.rmtree(out.parent, ignore_errors=True)


# ------------------------------------------------------------------ the scratch repo is a fair test


def test_public_scratch_history_holds_every_removed_path(scratch):
    """The input must contain all eight removed paths, or the output check proves nothing."""
    ever = {p for p in git(scratch, "log", "--all", "--name-only", "--format=").splitlines() if p}
    for r in REMOVED:
        assert any(p == r or p.startswith(r + "/") for p in ever), (
            f"{r} never in the scratch history"
        )
    # shapes the filter must handle: one removed folder gone for good, one that comes back
    assert git(scratch, "ls-tree", "-r", "phase-2-done").count(".claude/") == 0
    assert ".claude/again.json" in git(scratch, "ls-tree", "-r", "main")


def test_public_script_list_equals_the_decided_list():
    spec = importlib.util.spec_from_file_location("mp", MAKE_PUBLIC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert sorted(mod.REMOVED_PATHS) == sorted(REMOVED)


# ------------------------------------------------------------------ the real behaviour


def test_public_dry_run_succeeds_and_output_is_a_correct_publication(scratch, dry):
    cp = dry["cp"]
    assert cp.returncode == 0, f"stdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
    assert public_problems(scratch, dry["out"]) == []


def test_public_no_removed_path_survives_in_any_ref(dry):
    assert history_removed(dry["out"]) == []
    # the trap names are kept: a prefix is not a path
    tip = git(dry["out"], "ls-tree", "-r", "--name-only", "main").splitlines()
    for kept in (
        "docsite/index.md",
        "setup/claude-extra.txt",
        "scripts/coord.py.md",
        "web/with space.txt",
    ):
        assert kept in tip, kept
    assert not any(is_removed(p) for p in tip)


def test_public_every_other_file_is_byte_identical(scratch, dry):
    out = dry["out"]
    for r in ("refs/heads/main", "refs/tags/phase-1-done", "refs/tags/phase-3-done"):
        assert kept_listing(scratch, r) == kept_listing(out, r), r
    # byte-level: the executable bit and the binary blob
    assert "100755 " in " ".join(kept_listing(out, "main")) and "scripts/run.sh" in " ".join(
        kept_listing(out, "main")
    )
    blob = subprocess.run(
        ["git", "show", "main:web/blob.bin"], cwd=out, capture_output=True, env=ENV
    ).stdout
    assert blob == bytes(range(256)) * 4


def test_public_tags_kept_and_other_refs_dropped(dry):
    got = refs(dry["out"])
    assert got == [
        "refs/heads/main",
        "refs/tags/phase-1-done",
        "refs/tags/phase-2-done",
        "refs/tags/phase-3-done",
    ], got


def test_public_history_keeps_messages_and_drops_commits_that_became_empty(dry):
    subjects = git(dry["out"], "log", "--format=%s", "--reverse", "main").splitlines()
    assert subjects == ["c1 first", "c2 second", "c4 fourth"], subjects


def test_public_dry_run_pushes_nothing(scratch, dry):
    assert dry["before"] == dry["after"], "a dry run changed a ref in the source or its origin"
    assert "dry run: nothing pushed" in dry["cp"].stdout
    assert dry_run_leaks(scratch) == []


def test_public_push_refuses_the_private_origin(scratch, tools):
    origin = scratch.parent / "private-origin.git"
    before = refs(origin)
    cp = run_make_public(scratch, "--push", str(origin))
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "private" in (cp.stdout + cp.stderr).lower()
    assert refs(origin) == before


def test_public_push_to_a_new_remote_publishes_exactly_the_kept_refs(scratch, tools, tmp_path):
    remote = tmp_path / "public-remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    cp = run_make_public(scratch, "--push", str(remote))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert public_problems(scratch, remote) == []


def test_public_scratch_has_more_than_one_identity_in_commits_and_tags(scratch):
    """The input must hold addresses a careless rewrite would miss."""
    assert emails(scratch) == {"scratch@example.org", OTHER}
    assert (
        git(scratch, "log", "--all", "--format=%ae %ce").count(f"{OTHER} scratch@example.org") >= 1
    )
    assert OTHER in git(
        scratch, "for-each-ref", "--format=%(taggeremail)", "refs/tags/phase-3-done"
    )


def test_public_email_rewrite_is_off_by_default(scratch, tools):
    cp = run_make_public(scratch, "--keep")
    out = kept_dir(cp)
    try:
        assert emails(out) == emails(scratch)
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


def test_public_email_rewrite_leaves_no_other_address_in_any_ref(scratch, tools):
    """Human decision: every author and committer address is rewritten to the target (a fake one
    here), annotated tags included, and the output repo's own user.email is that target."""
    cp = run_make_public(scratch, "--keep", "--noreply-email", NOREPLY)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = kept_dir(cp)
    try:
        assert emails(out) == {NOREPLY}, emails(out)
        assert public_problems(scratch, out, rewritten_email=NOREPLY) == []
        assert local_email_problem(out, NOREPLY) is None
        # the rewrite touched identities only: same subjects, same trees
        assert git(out, "log", "--format=%s", "--reverse", "main").splitlines() == [
            "c1 first",
            "c2 second",
            "c4 fourth",
        ]
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


def test_public_the_script_never_modifies_the_source_repository(scratch, dry):
    assert git(scratch, "status", "--porcelain") == ""
    assert refs(scratch) == dry["before"][0]
    assert ".coord/STATE.md" in git(scratch, "ls-tree", "-r", "--name-only", "main")


# ------------------------------------------------------------------ planted defects


def _broken_copy(dry, tmp_path: Path) -> Path:
    dst = tmp_path / "broken"
    shutil.copytree(dry["out"], dst)
    return dst


def _add_commit(repo: Path, files: dict[str, str], msg: str, rm: tuple[str, ...] = ()) -> None:
    for rel, data in files.items():
        _write(repo, rel, data)
    for rel in rm:
        git(repo, "rm", "-q", rel)
    _commit(repo, msg, "2026-02-01T10:00:00+00:00")


def test_public_defect_a_removed_file_added_to_the_tip_is_reported(scratch, dry, tmp_path):
    bad = _broken_copy(dry, tmp_path)
    _add_commit(bad, {"docs/leak.md": "x\n"}, "leak")
    assert any("removed paths survive" in p for p in public_problems(scratch, bad))


def test_public_defect_a_removed_file_only_in_old_history_is_reported(scratch, dry, tmp_path):
    """The case a tip-only check misses: committed, then deleted."""
    bad = _broken_copy(dry, tmp_path)
    _add_commit(bad, {".coord/old.md": "x\n"}, "add")
    _add_commit(bad, {}, "delete", rm=(".coord/old.md",))
    assert ".coord/old.md" not in git(bad, "ls-tree", "-r", "--name-only", "main")
    assert any(".coord/old.md" in p for p in public_problems(scratch, bad))


def test_public_defect_a_removed_file_on_another_ref_is_reported(scratch, dry, tmp_path):
    bad = _broken_copy(dry, tmp_path)
    git(bad, "checkout", "-q", "-b", "side")
    _add_commit(bad, {"CLAUDE.md": "x\n"}, "side leak")
    git(bad, "checkout", "-q", "main")
    problems = public_problems(scratch, bad)
    assert any("removed paths survive" in p for p in problems)
    assert any("refs" in p for p in problems)


def test_public_defect_a_changed_kept_file_is_reported(scratch, dry, tmp_path):
    bad = _broken_copy(dry, tmp_path)
    _add_commit(bad, {"quantum/a.py": "A = 3\n"}, "tamper")
    assert any("kept files differ" in p for p in public_problems(scratch, bad))


def test_public_defect_a_lost_executable_bit_is_reported(scratch, dry, tmp_path):
    bad = _broken_copy(dry, tmp_path)
    (bad / "scripts" / "run.sh").chmod(0o644)
    git(bad, "update-index", "--chmod=-x", "scripts/run.sh")
    _commit(bad, "mode", "2026-02-01T10:00:00+00:00")
    assert any("kept files differ" in p for p in public_problems(scratch, bad))


def test_public_defect_a_dropped_kept_file_is_reported(scratch, dry, tmp_path):
    bad = _broken_copy(dry, tmp_path)
    _add_commit(bad, {}, "drop", rm=("docsite/index.md",))
    assert any("kept files differ" in p for p in public_problems(scratch, bad))


def test_public_defect_a_missing_tag_is_reported(scratch, dry, tmp_path):
    bad = _broken_copy(dry, tmp_path)
    git(bad, "tag", "-d", "phase-2-done")
    assert any("refs" in p for p in public_problems(scratch, bad))


def test_public_defect_an_extra_tag_or_branch_is_reported(scratch, dry, tmp_path):
    bad = _broken_copy(dry, tmp_path)
    git(bad, "tag", "private-note")
    assert any("refs" in p for p in public_problems(scratch, bad))
    bad2 = tmp_path / "broken2"
    shutil.copytree(dry["out"], bad2)
    git(bad2, "branch", "feature")
    assert any("refs" in p for p in public_problems(scratch, bad2))


def test_public_defect_a_rewritten_history_that_lost_a_middle_state_is_reported(
    scratch, dry, tmp_path
):
    """Tip and tags equal but an intermediate kept tree squashed away."""
    bad = _broken_copy(dry, tmp_path)
    git(bad, "checkout", "-q", "--orphan", "squash")
    _commit(bad, "squashed", "2026-02-01T10:00:00+00:00")
    git(bad, "branch", "-D", "main")
    git(bad, "branch", "-M", "main")
    assert any("kept trees" in p for p in public_problems(scratch, bad))


def test_public_defect_an_unrewritten_email_is_reported(scratch, dry, tmp_path):
    bad = _broken_copy(dry, tmp_path)
    assert any("e-mails" in p for p in public_problems(scratch, bad, rewritten_email=NOREPLY))


def _rewritten_copy(tmp_path: Path) -> Path:
    """A correct rewritten output, built without the script (history rewritten by hand)."""
    out = tmp_path / "rewritten"
    git(tmp_path, "init", "-q", "-b", "main", str(out))
    _write(out, "a.txt", "x\n")
    env = {**ENV, "GIT_AUTHOR_EMAIL": NOREPLY, "GIT_COMMITTER_EMAIL": NOREPLY}
    git(out, "add", "-A")
    git(out, "commit", "-q", "-m", "c", env=env)
    git(out, "config", "--local", "user.email", NOREPLY)
    return out


def test_public_defect_an_author_or_committer_or_tagger_left_behind_is_reported(tmp_path):
    out = _rewritten_copy(tmp_path)
    assert emails(out) == {NOREPLY}
    assert local_email_problem(out, NOREPLY) is None
    # an author left behind
    _write(out, "b.txt", "y\n")
    _commit(out, "b", "2026-02-01T10:00:00+00:00", author=OTHER)
    assert OTHER in emails(out) and emails(out) != {NOREPLY}
    # a tagger left behind (annotated tag), on a repo that is otherwise right
    out2 = _rewritten_copy(tmp_path / "second") if (tmp_path / "second").mkdir() is None else None
    git(out2, "tag", "-a", "-m", "t", "phase-1-done", env={**ENV, "GIT_COMMITTER_EMAIL": OTHER})
    assert emails(out2) == {NOREPLY, OTHER}  # the only other identity is the tagger


def test_public_defect_a_wrong_or_missing_local_user_email_is_reported(tmp_path):
    out = _rewritten_copy(tmp_path)
    git(out, "config", "--local", "user.email", OTHER)
    assert local_email_problem(out, NOREPLY) is not None
    git(out, "config", "--local", "--unset", "user.email")
    assert local_email_problem(out, NOREPLY) is not None


def test_public_defect_a_script_that_pushes_during_a_dry_run_is_caught(tools, tmp_path):
    """Plant the defect in a copy of the script: it pushes to the private origin on a dry run."""
    text = MAKE_PUBLIC.read_text()
    marker = 'print("dry run: nothing pushed (use --push <url> to publish)")'
    assert text.count(marker) == 1, (
        "make_public's dry-run branch changed: update this planted defect"
    )
    origin = "str(source.parent / 'private-origin.git')"
    leak = f'git("push", {origin}, "--tags", cwd=work); '
    bad_script = tmp_path / "make_public_pushing.py"
    bad_script.write_text(text.replace(marker, leak + marker))
    source = build_source(tmp_path / "fresh") if (tmp_path / "fresh").mkdir() is None else None
    assert dry_run_leaks(source, bad_script), "a dry run that pushed was not noticed"
    assert dry_run_leaks(source) == [], "the real script's dry run must leave refs alone"


def test_public_checker_reports_nothing_on_a_correct_output(scratch, dry):
    assert public_problems(scratch, dry["out"]) == []
    assert json.dumps(public_problems(scratch, dry["out"])) == "[]"


@pytest.mark.parametrize("path", REMOVED)
def test_public_defect_a_script_that_forgets_one_removed_path_is_caught(
    path, scratch, tools, tmp_path
):
    """Plant the defect in a copy of the script: one path missing from its list. The script's own
    check uses its own list, so it cannot notice; this checker, with the decided list, must."""
    text = MAKE_PUBLIC.read_text()
    line = f'    "{path}",\n'
    assert text.count(line) == 1, f"{path}: REMOVED_PATHS line not found once"
    bad_script = tmp_path / "make_public_forgetful.py"
    bad_script.write_text(text.replace(line, ""))
    cp = subprocess.run(
        [sys.executable, str(bad_script), "--source", str(scratch), "--keep"],
        capture_output=True,
        text=True,
        env=ENV,
    )
    out = kept_dir(cp)
    try:
        problems = public_problems(scratch, out)
        assert any("removed paths survive" in p for p in problems), (path, problems)
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


# ------------------------------------------------------------------ the address from `gh api user`

FAKE_GH_ADDRESS = "4242+fake-account@users.noreply.github.com"


def _fake_gh(bindir: Path, body: str) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(f"#!/bin/sh\n{body}\n")
    gh.chmod(0o755)
    return bindir


def _run_with_gh(source: Path, bindir: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {**ENV, "PATH": f"{bindir}{os.pathsep}{ENV['PATH']}"}
    return subprocess.run(
        [sys.executable, str(MAKE_PUBLIC), "--source", str(source), *extra],
        capture_output=True,
        text=True,
        env=env,
    )


def test_public_noreply_from_gh_rewrites_everything_and_never_prints_the_address(
    scratch, tools, tmp_path
):
    bindir = _fake_gh(tmp_path / "bin", f"echo '{FAKE_GH_ADDRESS}'")
    cp = _run_with_gh(scratch, bindir, "--keep", "--noreply-from-gh")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = kept_dir(cp)
    try:
        assert emails(out) == {FAKE_GH_ADDRESS}
        assert local_email_problem(out, FAKE_GH_ADDRESS) is None
        assert public_problems(scratch, out, rewritten_email=FAKE_GH_ADDRESS) == []
        assert FAKE_GH_ADDRESS not in cp.stdout + cp.stderr, "the address was printed"
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


def test_public_noreply_email_flag_does_not_print_the_address_either(scratch, tools):
    cp = run_make_public(scratch, "--keep", "--noreply-email", NOREPLY)
    try:
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert NOREPLY not in cp.stdout + cp.stderr
    finally:
        shutil.rmtree(kept_dir(cp).parent, ignore_errors=True)


@pytest.mark.parametrize(
    "body",
    [
        "exit 1",  # gh not logged in
        "echo 'not an address'",  # garbage
        "echo 'someone@example.org'",  # a real-looking address that is not a noreply one
        "echo ''",  # empty
    ],
    ids=["gh-fails", "garbage", "not-a-noreply-address", "empty"],
)
def test_public_noreply_from_gh_refuses_a_bad_answer_and_rewrites_nothing(
    scratch, tools, tmp_path, body
):
    cp = _run_with_gh(scratch, _fake_gh(tmp_path / "bin", body), "--noreply-from-gh", "--keep")
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "kept:" not in cp.stdout, "an output was produced although the address was refused"
    assert "dry run" not in cp.stdout


def test_public_a_plain_email_address_is_refused_as_a_rewrite_target(scratch, tools):
    cp = run_make_public(scratch, "--keep", "--noreply-email", "someone@example.org")
    assert cp.returncode == 1 and "kept:" not in cp.stdout, cp.stdout + cp.stderr


def test_public_the_two_rewrite_flags_cannot_be_combined(scratch, tools):
    cp = run_make_public(scratch, "--noreply-from-gh", "--noreply-email", NOREPLY)
    assert cp.returncode == 2, cp.stdout + cp.stderr
