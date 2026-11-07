#!/usr/bin/env python3
"""Phase gate. Owned by lead. Run with:  uv run python scripts/gate.py <phase>

Runs the regression checks every phase must keep green, plus that phase's own
checks, prints a summary and writes .coord/gates/phase-<N>.md.
Exit code 0 = gate passed.

To add a check for a phase: append to PHASE_CHECKS[N]. A check is either
  Cmd("label", ["argv", ...])          passes when the command exits 0
  Py("label", function)                function returns (ok: bool, detail: str)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


@dataclass
class Cmd:
    label: str
    argv: list[str]


@dataclass
class Py:
    label: str
    fn: Callable[[], tuple[bool, str]]


Check = Cmd | Py


# ---------- reusable check functions ----------

def qiskit_major_is_2() -> tuple[bool, str]:
    import qiskit

    return qiskit.__version__.startswith("2."), f"qiskit {qiskit.__version__}"


def file_exists(rel: str) -> Callable[[], tuple[bool, str]]:
    def _check() -> tuple[bool, str]:
        p = ROOT / rel
        return p.exists(), f"{rel} {'found' if p.exists() else 'missing'}"

    return _check


def json_valid(rel: str) -> Callable[[], tuple[bool, str]]:
    def _check() -> tuple[bool, str]:
        p = ROOT / rel
        try:
            json.loads(p.read_text())
            return True, f"{rel} is valid JSON"
        except Exception as exc:  # noqa: BLE001
            return False, f"{rel}: {exc}"

    return _check


def has_tests(phase: int) -> Callable[[], tuple[bool, str]]:
    def _check() -> tuple[bool, str]:
        d = ROOT / "tests" / f"phase{phase}"
        files = sorted(d.glob("test_*.py")) if d.exists() else []
        return bool(files), f"{len(files)} test file(s) in tests/phase{phase}"

    return _check


def pytest_selects(expr: str, minimum: int = 1) -> Callable[[], tuple[bool, str]]:
    """At least `minimum` tests match -k expr, and they pass."""

    def _check() -> tuple[bool, str]:
        r = subprocess.run(
            [PY, "-m", "pytest", "-m", "not hardware", "-k", expr, "-p", "no:cacheprovider"],
            cwd=ROOT, capture_output=True, text=True,
        )
        out = (r.stdout + r.stderr).strip().splitlines()
        last = out[-1] if out else ("no tests matched" if r.returncode == 5 else "(no output)")
        m = re.search(r"(\d+) passed", last)
        passed = int(m.group(1)) if m else 0
        ok = r.returncode == 0 and passed >= minimum
        return ok, f"-k {expr!r}: {last}"

    return _check


# ---------- checks ----------

REGRESSION: list[Check] = [
    Cmd("ruff lint", [PY, "-m", "ruff", "check", "."]),
    Cmd("full test suite (no hardware)", [PY, "-m", "pytest", "-m", "not hardware",
                                          "-p", "no:cacheprovider"]),
]

PHASE_CHECKS: dict[int, list[Check]] = {
    0: [
        Py("Qiskit major version is 2", qiskit_major_is_2),
        Py("phase 0 tests exist", has_tests(0)),
        Py("results/budget.json exists", file_exists("results/budget.json")),
        Py("results/budget.json is valid JSON", json_valid("results/budget.json")),
        Py("budget guard is tested and passes", pytest_selects("budget")),
        Py(".env is git-ignored", lambda: (
            ".env" in (ROOT / ".gitignore").read_text().split(), ".gitignore checked")),
    ],
    # Lead: at /phase-start N, turn every command-checkable exit criterion
    # in docs/PLAN.md into a check here before BUILD starts.
    1: [Py("phase 1 tests exist", has_tests(1))],
    2: [Py("phase 2 tests exist", has_tests(2))],
    3: [Py("phase 3 tests exist", has_tests(3))],
    4: [Py("phase 4 tests exist", has_tests(4))],
    5: [],
    6: [],
}


def run(check: Check) -> tuple[bool, str, float]:
    t0 = time.perf_counter()
    if isinstance(check, Cmd):
        r = subprocess.run(check.argv, cwd=ROOT, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip().splitlines()
        out = [ln for ln in out if ln.strip() and not ln.startswith("warning:")]
        detail = " | ".join(out[-3:]) if out else "(no output)"
        ok = r.returncode == 0
    else:
        try:
            ok, detail = check.fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
    return ok, detail, time.perf_counter() - t0


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("usage: uv run python scripts/gate.py <phase>")
        return 2
    phase = int(sys.argv[1])
    if phase not in PHASE_CHECKS:
        print(f"no checks defined for phase {phase}")
        return 2

    checks = REGRESSION + PHASE_CHECKS[phase]
    rows = []
    for c in checks:
        ok, detail, secs = run(c)
        rows.append((c.label, ok, detail, secs))
        print(f"{'PASS' if ok else 'FAIL'}  {c.label}  ({secs:.1f}s)  {detail}")

    passed = all(ok for _, ok, _, _ in rows)
    verdict = "PASSED" if passed else "FAILED"
    print(f"\nGate {phase}: {verdict} ({sum(ok for _, ok, _, _ in rows)}/{len(rows)} checks)")

    out = ROOT / ".coord" / "gates" / f"phase-{phase}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Gate report — phase {phase}",
        "",
        f"{datetime.now():%Y-%m-%d %H:%M} · **{verdict}**",
        "",
        "| Check | Result | Time (s) | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for label, ok, detail, secs in rows:
        safe = detail.replace("|", "/")
        lines.append(f"| {label} | {'pass' if ok else 'FAIL'} | {secs:.1f} | {safe} |")
    lines += ["", "## Retro", "(lead fills in at /phase-close)", ""]
    out.write_text("\n".join(lines))
    print(f"report: {out.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
