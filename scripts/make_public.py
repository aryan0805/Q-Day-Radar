"""Make the public copy of this repository: the product and its evidence, nothing else.

What it does (all in a temporary directory; this checkout is never touched):

1. fresh ``git clone --no-local`` of one branch (default ``main``) plus the ``phase-*-done`` tags;
2. ``git filter-repo --invert-paths`` for every path in ``REMOVED_PATHS``, in every commit;
3. optional rewrite of every author and committer e-mail (``--noreply-email``, off by default);
4. checks on the result: no removed path in any commit, gitleaks finds nothing;
5. a summary: removed paths, kept refs, commit count.

It pushes only when given ``--push <url>``. Without it the run is a dry run and nothing leaves the
machine. A re-publish of the same history gives the same commit ids (the filter is deterministic),
so tags added later can be pushed on top of an already public ``main``.

Needs ``git-filter-repo`` (``brew install git-filter-repo``) and ``gitleaks``.

    uv run python scripts/make_public.py                     # dry run, prints the summary
    uv run python scripts/make_public.py --keep              # ... and keeps the temp directory
    uv run python scripts/make_public.py --push <url>        # publish (only with the human's OK)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Paths that exist in the private development repository and not in the public one.
REMOVED_PATHS: list[str] = [
    ".claude",
    "docs",
    "CLAUDE.md",
    ".coord",
    "setup/claude",
    "scripts/coord.py",
    "scripts/team.sh",
    "scripts/install-claude-config.sh",
]
PUBLIC_BRANCH = "main"
TAG_GLOB = "phase-*-done"


class PublishError(RuntimeError):
    pass


def git(*args: str, cwd: Path, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise PublishError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def have_filter_repo() -> bool:
    r = subprocess.run(["git", "filter-repo", "--version"], capture_output=True, text=True)
    return r.returncode == 0


def history_paths(repo: Path) -> set[str]:
    """Every path that appears in any commit of any ref."""
    out = git("log", "--all", "--name-only", "--format=", "--no-renames", cwd=repo)
    return {line for line in out.splitlines() if line}


def removed_in(paths: set[str]) -> list[str]:
    return sorted(p for p in paths if any(p == r or p.startswith(r + "/") for r in REMOVED_PATHS))


def clone_fresh(source: Path, branch: str, dest: Path) -> list[str]:
    """Fresh clone of one branch and the phase-N-done tags. Returns the tag names."""
    git("clone", "--no-local", "--no-tags", "--single-branch", "--branch", branch, str(source),
        str(dest), cwd=source)
    git("fetch", "--no-tags", str(source), f"refs/tags/{TAG_GLOB}:refs/tags/{TAG_GLOB}", cwd=dest,
        check=False)
    if branch != PUBLIC_BRANCH:
        git("branch", "-M", PUBLIC_BRANCH, cwd=dest)
    git("remote", "remove", "origin", cwd=dest)
    return sorted(git("tag", "--list", TAG_GLOB, cwd=dest).split())


def filter_history(repo: Path, noreply_email: str | None) -> None:
    cmd = ["git", "filter-repo", "--invert-paths", "--force"]
    for p in REMOVED_PATHS:
        cmd += ["--path", p]
    if noreply_email:
        cb = f'return b"{noreply_email}"'
        cmd += ["--email-callback", cb]
    r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        raise PublishError(f"git filter-repo failed: {r.stderr.strip()[:500]}")


def gitleaks_history(repo: Path) -> tuple[bool, str]:
    if shutil.which("gitleaks") is None:
        raise PublishError("gitleaks is not installed (brew install gitleaks)")
    cmd = ["gitleaks", "git", "--redact", "--no-banner", "--exit-code", "1", str(repo)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, lines[-1] if lines else ""


def emails(repo: Path) -> set[str]:
    out = git("log", "--all", "--format=%ae%n%ce", cwd=repo)
    return {e for e in out.split() if e}


def push(repo: Path, url: str, tags: list[str]) -> None:
    git("push", url, f"refs/heads/{PUBLIC_BRANCH}:refs/heads/{PUBLIC_BRANCH}", cwd=repo)
    for t in tags:
        git("push", url, f"refs/tags/{t}:refs/tags/{t}", cwd=repo)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", type=Path, default=ROOT, help="repository to publish from")
    ap.add_argument("--branch", default=PUBLIC_BRANCH,
                    help="source branch that becomes public main (default main)")
    ap.add_argument("--noreply-email", metavar="ADDRESS",
                    help="rewrite every author and committer e-mail to this address "
                         "(off by default; the human decides)")
    ap.add_argument("--push", metavar="URL", help="push the result to this URL; omit for a dry run")
    ap.add_argument("--keep", action="store_true", help="keep the temporary directory and print it")
    args = ap.parse_args(argv)

    if not have_filter_repo():
        print("git-filter-repo is not installed: brew install git-filter-repo", file=sys.stderr)
        return 2
    source = args.source.resolve()
    tmp = Path(tempfile.mkdtemp(prefix="qday-public-"))
    work = tmp / "public"
    try:
        tags = clone_fresh(source, args.branch, work)
        before = history_paths(work)
        had = removed_in(before)
        filter_history(work, args.noreply_email)
        after = history_paths(work)
        left = removed_in(after)
        clean, leak_line = gitleaks_history(work)
        n_commits = len(git("rev-list", "--all", cwd=work).split())
        refs = [r.split()[-1] for r in git("for-each-ref", cwd=work).splitlines()]
        addrs = emails(work)

        print(f"source         : {source} ({args.branch})")
        print(f"removed paths  : {', '.join(REMOVED_PATHS)}")
        print(f"  present before the filter: {len(had)} file paths; after: {len(left)}")
        print(f"kept refs      : {', '.join(refs)}")
        print(f"commits        : {n_commits}")
        print(f"author e-mails : {len(addrs)} distinct"
              + (" (all rewritten)" if args.noreply_email else " (unchanged)"))
        print(f"gitleaks       : {'clean' if clean else 'FINDINGS'} {leak_line}")
        if left:
            print(f"FAIL: removed paths survive in history: {left[:5]}", file=sys.stderr)
            return 1
        if not clean:
            print("FAIL: gitleaks found something in the filtered history", file=sys.stderr)
            return 1
        if args.push:
            if args.push.rstrip("/") == git("remote", "get-url", "origin", cwd=source,
                                            check=False).strip().rstrip("/"):
                print("FAIL: refusing to push to the private repository", file=sys.stderr)
                return 1
            push(work, args.push, tags)
            print(f"pushed {PUBLIC_BRANCH} and {len(tags)} tags to {args.push}")
        else:
            print("dry run: nothing pushed (use --push <url> to publish)")
        if args.keep:
            print(f"kept: {work}")
        return 0
    except PublishError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
