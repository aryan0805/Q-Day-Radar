"""Security: secrets and environment never reach the web app (task 7, brief table "secret hygiene").

Thresholds, fixed before BUILD: 0 canary hits in out/ and the data; a planted canary in a temp copy
IS caught (text file, binary font, and a bare pattern with no .env at all); no `.env*` under web/;
`process.env` in web/src and next.config.* is only NODE_ENV; no NEXT_PUBLIC_; `git log --all --
.env` is empty. A scan that scanned nothing must not pass.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from .helpers import DATA_DIR, FAKE_AWS_KEY_ID, REPO, WEB, read_dotenv_values, scan_tree

SCAN = WEB / "scripts" / "canary-scan.mjs"
# a value that is clearly fake but long enough to be treated as a secret (>= 8 chars)
FAKE = "zq-FAKE-canary-7Hk2pX9wLm41"
SKIP_DIRS = {"node_modules", ".next", "out", ".vercel", ".turbo"}


def _node(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["node", str(SCAN), *args], capture_output=True, text=True, timeout=60)


def _env_file(tmp: Path, value: str = FAKE) -> Path:
    f = tmp / "canary.env"
    f.write_text(f"# test\nSOME_KEY={value}\nSHORT=abc\n", encoding="utf-8")
    return f


def _copy(out_dir: Path, tmp: Path) -> Path:
    dst = tmp / "out"
    shutil.copytree(out_dir, dst)
    return dst


# ------------------------------------------------------------------ the build's own scanner


def test_security_canary_scan_passes_a_clean_copy_and_reports_what_it_scanned(
    out_dir: Path, tmp_path: Path
) -> None:
    r = _node(str(_copy(out_dir, tmp_path)), "--env", str(_env_file(tmp_path)))
    assert r.returncode == 0, r.stdout + r.stderr
    m = re.search(r"(\d+) files, (\d+) \.env values in memory, (\d+) hits", r.stdout)
    assert m, r.stdout
    assert int(m.group(1)) > 20, "it scanned almost nothing"
    assert int(m.group(2)) == 1, "the 8+ char value was not loaded (the 3-char one must be skipped)"
    assert int(m.group(3)) == 0


def test_security_canary_scan_catches_a_planted_value_in_a_script(
    out_dir: Path, tmp_path: Path
) -> None:
    copy = _copy(out_dir, tmp_path)
    js = next(p for p in sorted(copy.rglob("*.js")))
    js.write_text(js.read_text(encoding="utf-8") + f"\nvar k='{FAKE}';\n", encoding="utf-8")
    r = _node(str(copy), "--env", str(_env_file(tmp_path)))
    assert r.returncode == 1
    assert js.name in r.stdout and "value from .env" in r.stdout
    assert FAKE not in r.stdout + r.stderr, "the scanner printed the secret"


def test_security_canary_scan_catches_a_value_hidden_in_a_binary_font(
    out_dir: Path, tmp_path: Path
) -> None:
    copy = _copy(out_dir, tmp_path)
    font = next(p for p in sorted(copy.rglob("*.woff2")))
    font.write_bytes(font.read_bytes() + b"\x00\x01" + FAKE.encode() + b"\x02")
    r = _node(str(copy), "--env", str(_env_file(tmp_path)))
    assert r.returncode == 1 and font.name in r.stdout
    assert FAKE not in r.stdout + r.stderr


def test_security_canary_scan_catches_a_secret_shaped_string_with_no_env_file(
    out_dir: Path, tmp_path: Path
) -> None:
    copy = _copy(out_dir, tmp_path)
    (copy / "leak.txt").write_text(f"key={FAKE_AWS_KEY_ID}\n", encoding="utf-8")
    r = _node(str(copy), "--env", str(tmp_path / "does-not-exist.env"))
    assert r.returncode == 1 and "AWS access key id" in r.stdout


def test_security_canary_scan_is_not_green_when_it_scans_nothing(tmp_path: Path) -> None:
    # a mistyped or missing out/ must fail, not report "0 files, 0 hits" and exit 0
    r = _node(str(tmp_path / "no-such-dir"), "--env", str(_env_file(tmp_path)))
    assert r.returncode != 0, f"scanned a missing directory and passed: {r.stdout!r}"
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _node(str(empty), "--env", str(_env_file(tmp_path)))
    assert r.returncode != 0, f"scanned an empty directory and passed: {r.stdout!r}"


# ------------------------------------------------ the same check, independently, in Python


def test_security_python_scanner_finds_the_same_planted_value(
    out_dir: Path, tmp_path: Path
) -> None:
    copy = _copy(out_dir, tmp_path)
    assert scan_tree(copy, [FAKE]) == []
    (copy / "data").mkdir(exist_ok=True)
    (copy / "data" / "x.json").write_text('{"v": "' + FAKE + '"}', encoding="utf-8")
    (hit,) = scan_tree(copy, [FAKE])
    assert hit.file.endswith("x.json") and FAKE not in repr(hit)


def test_security_real_env_values_are_absent_from_out_and_the_data(out_dir: Path) -> None:
    # The real values are read in memory only and never printed (a hit reports an index).
    values = read_dotenv_values(REPO / ".env")
    # scanning for nothing proves nothing: with no loadable value this check must not pass
    assert values, "no value of 8+ characters in the root .env: nothing to scan for"
    hits = scan_tree(out_dir, values) + scan_tree(DATA_DIR, values)
    assert hits == [], f"{len(hits)} hit(s); value indexes {sorted({h.detail for h in hits})}"


# -------------------------------------------------------------------- env in the web source


def _web_source_files() -> list[Path]:
    files = [p for p in (WEB / "src").rglob("*") if p.is_file() and p.suffix in SRC_EXT]
    files += [p for p in WEB.glob("next.config.*") if p.is_file()]
    return sorted(files)


SRC_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".json"}
# every use of `process` other than the one allowed read, and every other env access style
_PROCESS = re.compile(r"\bprocess\b")
_ALLOWED_PROCESS = re.compile(r"\bprocess\.env\.NODE_ENV\b")
_OTHER_ENV = re.compile(r"import\.meta\.env|NEXT_PUBLIC_|\bDeno\.env\b|\bBun\.env\b")


def env_violations(text: str) -> list[str]:
    """Reads of the environment other than process.env.NODE_ENV. Strips comments first so a
    sentence about process.env in a comment is not a violation, and a real read is."""
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    code = re.sub(r"(?m)(^|[^:])//.*$", r"\1", code)
    bad = [m.group(0) for m in _OTHER_ENV.finditer(code)]
    stripped = _ALLOWED_PROCESS.sub("", code)
    bad += ["process" for _ in _PROCESS.finditer(stripped)]
    return bad


def test_security_web_source_reads_only_node_env() -> None:
    files = _web_source_files()
    assert len(files) > 5, "found almost no web source: wrong path?"
    found = {str(f.relative_to(WEB)): v for f in files if (v := env_violations(f.read_text()))}
    assert found == {}


def test_security_env_violation_rule_catches_each_way_to_read_the_environment() -> None:
    assert env_violations("const a = process.env.NODE_ENV;") == []
    assert env_violations("// process.env.SECRET is not read\nconst a = 1;") == []
    for bad in (
        "const k = process.env.API_KEY;",
        "const k = process.env['API_KEY'];",
        "const { env } = process;",
        "const k = process.env;",
        "const k = import.meta.env.KEY;",
        "const k = 'NEXT_PUBLIC_X';",
        "const e = process.env.NODE_ENV + process.env.OTHER;",
    ):
        assert env_violations(bad), f"not caught: {bad}"


def test_security_no_env_files_under_web() -> None:
    found = [
        str(p.relative_to(WEB))
        for p in WEB.rglob(".env*")
        if not SKIP_DIRS & set(p.relative_to(WEB).parts)
    ]
    assert found == []


def test_security_the_build_commit_is_read_only_in_scripts_never_in_src() -> None:
    needles = ("VERCEL_GIT_COMMIT_SHA", "rev-parse")
    in_src = [
        str(f.relative_to(WEB))
        for f in (WEB / "src").rglob("*")
        if f.is_file() and f.suffix in SRC_EXT and any(n in f.read_text() for n in needles)
    ]
    assert in_src == []
    assert any(n in (WEB / "scripts" / "postbuild.mjs").read_text() for n in needles)


# ----------------------------------------------------------------------------- git hygiene


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_security_env_was_never_committed_on_any_branch() -> None:
    # the spec's own form: `git log --all -- .env` must be empty
    assert _git("log", "--all", "--oneline", "--", ".env") == ""
    # and no file named .env (or .env.local, .env.production, ...) was ever added at any depth;
    # the committed template .env.example is the one allowed exception
    added = _git("log", "--all", "--diff-filter=A", "--name-only", "--format=").splitlines()
    env_like = {f for f in added if re.match(r"\.env(\.|$)", Path(f).name)}
    assert env_like <= {".env.example"}, sorted(env_like - {".env.example"})


def test_security_no_env_file_is_tracked_and_env_is_ignored() -> None:
    tracked = [f for f in _git("ls-files").splitlines() if Path(f).name.startswith(".env")]
    assert set(tracked) <= {".env.example"}, tracked
    ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=REPO)
    assert ignored.returncode == 0, ".env is not git-ignored"


def test_security_the_committed_env_template_holds_only_placeholders() -> None:
    # read_dotenv_values keeps values of 8+ characters: a real token or CRN would show up here
    assert read_dotenv_values(REPO / ".env.example") == []


def test_security_the_pre_commit_hook_runs_gitleaks_and_is_wired_up() -> None:
    hook = REPO / ".githooks" / "pre-commit"
    assert hook.is_file() and "gitleaks" in hook.read_text()
    assert hook.stat().st_mode & 0o111, "hook is not executable"
    assert _git("config", "--get", "core.hooksPath") == ".githooks"


def test_security_a_github_action_runs_gitleaks_on_push() -> None:
    wf = list((REPO / ".github" / "workflows").glob("*.yml"))
    text = "\n".join(p.read_text() for p in wf)
    assert "gitleaks" in text and re.search(r"(?m)^\s*push\s*:", text)


def test_security_dependabot_covers_npm_and_uv() -> None:
    text = (REPO / ".github" / "dependabot.yml").read_text()
    for eco in ("npm", "uv"):
        assert re.search(rf"package-ecosystem:\s*[\"']?{eco}[\"']?", text), eco


def test_security_the_lockfile_is_committed() -> None:
    assert (WEB / "package-lock.json").is_file()
    assert _git("ls-files", "web/package-lock.json") == "web/package-lock.json"


@pytest.mark.parametrize("name", ["package.json"])
def test_security_the_web_scripts_the_gate_runs_exist(name: str) -> None:
    import json

    scripts = json.loads((WEB / name).read_text())["scripts"]
    assert {"lint", "typecheck", "build"} <= set(scripts)
    assert "--max-warnings 0" in scripts["lint"] or "--max-warnings=0" in scripts["lint"]
