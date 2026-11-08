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

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
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


_SUITE: dict = {}


def full_suite() -> tuple[bool, str]:
    """Run the non-hardware suite once, with a JUnit report the keyword checks reuse."""
    xml = Path(tempfile.gettempdir()) / f"qday-gate-{os.getpid()}.xml"
    r = subprocess.run(
        [PY, "-m", "pytest", "-m", "not hardware", "-p", "no:cacheprovider",
         f"--junitxml={xml}"],
        cwd=ROOT, capture_output=True, text=True,
    )
    cases = []
    if xml.exists():
        for tc in ET.parse(xml).getroot().iter("testcase"):
            status = "passed"
            for child in tc:
                if child.tag in ("failure", "error"):
                    status = "failed"
                elif child.tag == "skipped":
                    status = "xfailed" if "xfail" in (child.get("type") or "") else "skipped"
            cases.append((tc.get("classname", ""), tc.get("name", ""), status))
        xml.unlink()
    _SUITE.update(ok=r.returncode == 0, cases=cases)
    out = [ln for ln in (r.stdout + r.stderr).strip().splitlines() if ln.strip()]
    return r.returncode == 0, " | ".join(out[-2:]) if out else "(no output)"


def pytest_selects(
    expr: str, minimum: int = 1, path: str | None = None, strict: bool = False
) -> Callable[[], tuple[bool, str]]:
    """At least `minimum` tests whose name contains `expr` (case-insensitive, like -k
    with one word; under `path`, if given) ran in the full suite, and all passed.

    strict=True also fails on any xfailed or skipped match: a known gap parked
    behind a marker must not count as a pass.
    """

    def _check() -> tuple[bool, str]:
        if "cases" not in _SUITE:
            full_suite()
        prefix = path.strip("/").replace("/", ".") + "." if path else ""
        hits = [s for cls, name, s in _SUITE["cases"]
                if cls.startswith(prefix) and expr.lower() in f"{cls}.{name}".lower()]
        n = {k: hits.count(k) for k in ("passed", "failed", "skipped", "xfailed")}
        ok = n["failed"] == 0 and n["passed"] >= minimum
        if strict and (n["skipped"] or n["xfailed"]):
            ok = False
        where = f" in {path}" if path else ""
        return ok, f"{expr!r}{where}: " + ", ".join(f"{v} {k}" for k, v in n.items() if v)

    return _check


# ---------- phase 1: circuits ----------

P1_REQUIRED = {
    "shor15_textbook": "compiled",
    "shor15_beauregard": "generic",
    "shor21_beauregard": "generic",
    **{f"grover_present_k{k}": "generic" for k in range(2, 6)},
}
P1_METRIC_KEYS = {
    "name", "kind", "n_qubits", "depth", "two_qubit_gates", "transpile",
    "success_probability", "theoretical_success", "shots", "seed_simulator",
    "qiskit_version", "timestamp", "chance_baseline",
}
P1_TOLERANCE = 0.02
P1_MIN_SHOTS = 8192


def _p1_circuits() -> dict:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from quantum.circuits.registry import build_all

    return build_all()


def _p1_metrics(name: str) -> dict:
    return json.loads((ROOT / "results" / "metrics" / f"{name}.json").read_text())


def p1_registry_complete() -> tuple[bool, str]:
    circuits = _p1_circuits()
    problems = []
    for name, want_kind in P1_REQUIRED.items():
        if name not in circuits:
            problems.append(f"{name} missing")
            continue
        md = circuits[name].metadata or {}
        if md.get("kind") != want_kind:
            problems.append(f"{name} kind={md.get('kind')!r}, want {want_kind}")
        ts = md.get("theoretical_success")
        if not isinstance(ts, int | float) or not 0.0 <= ts <= 1.0:
            problems.append(f"{name} theoretical_success={ts!r}")
    for name, qc in circuits.items():
        if (qc.metadata or {}).get("kind") not in ("generic", "compiled"):
            problems.append(f"{name} has no valid kind")
    return not problems, "; ".join(problems) or f"{len(circuits)} circuits, all labeled"


def p1_metrics_complete() -> tuple[bool, str]:
    circuits = _p1_circuits()
    problems = []
    for name, qc in circuits.items():
        try:
            m = _p1_metrics(name)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: {type(exc).__name__}")
            continue
        missing = P1_METRIC_KEYS - m.keys()
        if missing:
            problems.append(f"{name} missing {sorted(missing)}")
        if m.get("kind") != (qc.metadata or {}).get("kind"):
            problems.append(f"{name} kind mismatch")
        if not isinstance(m.get("shots"), int) or m["shots"] < P1_MIN_SHOTS:
            problems.append(f"{name} shots={m.get('shots')!r}")
        if (m.get("transpile") or {}).get("backend") != "fake_kingston":
            problems.append(f"{name} not transpiled for fake_kingston")
    return not problems, "; ".join(problems) or f"{len(circuits)} metrics files complete"


def p1_success_within_tolerance() -> tuple[bool, str]:
    """Two-sided (P004): a leaking circuit overshoots theory and must fail too."""
    rows, problems = [], []
    for name in _p1_circuits():
        m = _p1_metrics(name)
        got, want = m["success_probability"], m["theoretical_success"]
        chance = m.get("chance_baseline")
        rows.append(f"{name} {got:.3f}/{want:.3f} (chance {chance})")
        dev = got - want
        if abs(dev) > P1_TOLERANCE:
            side = "above" if dev > 0 else "below"
            problems.append(f"{name} {got:.3f} is {abs(dev):.3f} {side} theory {want:.3f}")
        if isinstance(chance, int | float) and want > chance and got <= chance:
            problems.append(f"{name} {got:.3f} not above chance {chance:.3f}")
    return not problems, "; ".join(problems) or ", ".join(rows)


def p1_strict(expr: str) -> Callable[[], tuple[bool, str]]:
    return pytest_selects(expr, path="tests/phase1", strict=True)


def glob_nonempty(pattern: str) -> Callable[[], tuple[bool, str]]:
    def _check() -> tuple[bool, str]:
        hits = sorted(ROOT.glob(pattern))
        return bool(hits), f"{len(hits)} match {pattern}"

    return _check


# ---------- phase 2: noisy sim + hardware ----------

P2_NOISY_KEYS = {
    "name", "kind", "noise_model", "shots", "seed_simulator", "success_probability",
    "wilson_95", "theoretical_success", "chance_baseline", "normalized_score",
    "hellinger_vs_ideal", "signal",
}
P2_PLAN_CAP_SECONDS = 300.0
P2_REDUCED_MIN_SHOTS = 1024
P2_HW = ROOT / "results" / "hardware"


def _p2_batches() -> list[Path]:
    if not P2_HW.exists():
        return []
    return sorted(
        d for d in P2_HW.glob("*") if (d / "plan.json").exists() and not _p2_superseded(d)
    )


def _p2_superseded(batch: Path) -> bool:
    """A replaced plan is skipped only if nothing was ever approved or submitted from it."""
    untouched = not any(
        (batch / f).exists() for f in ("approval.json", "submitted.jsonl", "jobs", "stopped.json")
    )
    return (batch / "SUPERSEDED.md").exists() and untouched


def _p2_jobs(batch: Path) -> list[dict]:
    return [json.loads(f.read_text()) for f in sorted((batch / "jobs").glob("*.json"))]


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def p2_noisy_complete() -> tuple[bool, str]:
    problems, signal = [], []
    for name in _p1_circuits():
        f = ROOT / "results" / "noisy" / f"{name}.json"
        try:
            m = json.loads(f.read_text())
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{name}: {type(exc).__name__}")
            continue
        missing = P2_NOISY_KEYS - m.keys()
        if missing:
            problems.append(f"{name} missing {sorted(missing)}")
            continue
        # Fewer shots only with a recorded reason (human's 22:00 rule for shor21), floor 1024.
        floor = P2_REDUCED_MIN_SHOTS if m.get("reduced_shots_reason") else P1_MIN_SHOTS
        if not isinstance(m["shots"], int) or m["shots"] < floor:
            problems.append(f"{name} shots={m['shots']!r} (min {floor})")
        if m["signal"] != (m["wilson_95"][0] > m["chance_baseline"]):
            problems.append(f"{name} signal flag disagrees with wilson_95[0] > chance")
        if m["signal"]:
            signal.append(name)
    return not problems, "; ".join(problems) or f"7 files; signal: {', '.join(signal) or 'none'}"


def p2_batches_approved() -> tuple[bool, str]:
    batches = _p2_batches()
    if not batches:
        return False, "no batch with plan.json under results/hardware/"
    problems = []
    for b in batches:
        try:
            a = json.loads((b / "approval.json").read_text())
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{b.name}: approval {type(exc).__name__}")
            continue
        digest = hashlib.sha256((b / "plan.json").read_bytes()).hexdigest()
        if a.get("approved_by") != "human":
            problems.append(f"{b.name}: approved_by={a.get('approved_by')!r}")
        if a.get("plan_sha256") != digest:
            problems.append(f"{b.name}: plan.json changed after approval")
        approved = _ts(a["approved_at"])
        late = [j["index"] for j in _p2_jobs(b) if _ts(j["created"]) <= approved]
        if late:
            problems.append(f"{b.name}: jobs {late} created before approval")
        problems += _p2_resume_problems(b, digest)
    return not problems, "; ".join(problems) or f"{len(batches)} batch(es) human-approved"


def _p2_resume_problems(batch: Path, digest: str) -> list[str]:
    """Each resume is its own human TTY approval of the same plan hash, made before its jobs."""
    path = batch / "resumes.jsonl"
    if not path.exists():
        return []
    problems = []
    created = {j["index"]: _ts(j["created"]) for j in _p2_jobs(batch)}
    for k, line in enumerate(path.read_text().splitlines()):
        r = json.loads(line)
        if r.get("approved_by") != "human" or r.get("plan_sha256") != digest:
            problems.append(f"{batch.name}: resume {k} not a human approval of this plan")
            continue
        at = _ts(r["resumed_at"])
        early = [i for i in r.get("indices", []) if i in created and created[i] <= at]
        if early:
            problems.append(f"{batch.name}: resume {k} jobs {early} created before it")
    return problems


def p2_plan_within_cap() -> tuple[bool, str]:
    total = sum(json.loads((b / "plan.json").read_text())["total_estimated_seconds"]
                for b in _p2_batches())
    return total <= P2_PLAN_CAP_SECONDS, f"planned {total:.1f} s of {P2_PLAN_CAP_SECONDS:.0f} s"


def p2_jobs_match_plan() -> tuple[bool, str]:
    problems, n = [], 0
    for b in _p2_batches():
        plan = {j["index"]: j for j in json.loads((b / "plan.json").read_text())["jobs"]}
        for job in _p2_jobs(b):
            n += 1
            entry = plan.get(job["index"])
            if entry is None:
                problems.append(f"{b.name}/{job['index']} not in plan")
            elif entry.get("isa_sha256") != job.get("isa_sha256"):
                problems.append(f"{b.name}/{job['index']} circuit differs from plan")
            elif not (entry.get("prediction") or {}).get("counts"):
                problems.append(f"{b.name}/{job['index']} has no prediction")
    if n == 0:
        problems.append("no hardware jobs")
    return not problems, "; ".join(problems) or f"{n} jobs, each matches a predicted plan entry"


def p2_ledger() -> tuple[bool, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from quantum.run.budget import DEFAULT_PATH, load_budget, used_seconds

    used = used_seconds(DEFAULT_PATH)
    ledger = {e["job_id"] for e in load_budget(DEFAULT_PATH)["entries"]}
    jobs = {j["job_id"] for b in _p2_batches() for j in _p2_jobs(b)}
    missing = sorted(jobs - ledger)
    ok = used <= 540.0 and not missing
    return ok, f"used {used:.1f} / 540 s" + (f"; not in ledger: {missing}" if missing else "")


def p2_analysis_complete() -> tuple[bool, str]:
    """Every job has an analysis file; every DONE job has both Hellinger values.

    Failed or canceled jobs keep a file (null values) so none is silently dropped.
    m3_cal jobs are calibration, not results, and need no Hellinger value.
    """
    problems, n, done = [], 0, 0
    for b in _p2_batches():
        for job in _p2_jobs(b):
            n += 1
            f = ROOT / "results" / "analysis" / "phase2" / b.name / f"{job['index']}.json"
            try:
                a = json.loads(f.read_text())
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{b.name}/{job['index']}: {type(exc).__name__}")
                continue
            if job.get("status") != "DONE" or job.get("config") == "m3_cal":
                continue
            done += 1
            for k in ("hellinger_vs_ideal", "hellinger_vs_prediction"):
                v = a.get(k)
                if not isinstance(v, int | float) or not 0.0 <= v <= 1.0:
                    problems.append(f"{b.name}/{job['index']} {k}={v!r}")
    if done == 0:
        problems.append("no DONE result job")
    summary = f"{n} jobs with analysis, {done} DONE with Hellinger"
    return not problems, "; ".join(problems) or summary


def p2_strict(expr: str) -> Callable[[], tuple[bool, str]]:
    return pytest_selects(expr, path="tests/phase2", strict=True)


# ---------- checks ----------

REGRESSION: list[Check] = [
    Cmd("ruff lint", [PY, "-m", "ruff", "check", "."]),
    Py("full test suite (no hardware)", full_suite),
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
    1: [
        Py("phase 1 tests exist", has_tests(1)),
        Cmd("metrics regenerate", [PY, "scripts/record_metrics.py"]),
        Py("registry has all 7 circuits, labeled", p1_registry_complete),
        Py("metrics JSON complete for every circuit", p1_metrics_complete),
        Py("|success - theoretical| <= 0.02", p1_success_within_tolerance),
        Py("leak tests pass (no xfail/skip)", p1_strict("leak")),
        Py("shor tests pass (no xfail/skip)", p1_strict("shor")),
        Py("grover tests pass (no xfail/skip)", p1_strict("grover")),
        Py("honesty audit written", file_exists("tests/phase1/AUDIT.md")),
        Py("2q-gate benchmark recorded", glob_nonempty("benchmarks/phase1-*")),
    ],
    2: [
        Py("phase 2 tests exist", has_tests(2)),
        Py("noisy-sim results for all 7 circuits", p2_noisy_complete),
        Py("transpile comparison recorded", glob_nonempty("benchmarks/phase2-transpile*")),
        Py("every batch human-approved before its jobs", p2_batches_approved),
        Py("planned QPU time <= 300 s", p2_plan_within_cap),
        Py("every job matches a pre-registered prediction", p2_jobs_match_plan),
        Py("ledger <= 540 s and records every job", p2_ledger),
        Py("Hellinger fidelity for every job", p2_analysis_complete),
        Cmd("raw hardware files unchanged",
            ["git", "diff", "--quiet", "HEAD", "--", "results/hardware"]),
        Py("approval tests pass (no xfail/skip)", p2_strict("approval")),
        Py("immutable tests pass (no xfail/skip)", p2_strict("immutable")),
        Py("budget tests pass (no xfail/skip)", pytest_selects("budget", strict=True)),
        Py("phase 2 honesty audit written", file_exists("tests/phase2/AUDIT.md")),
    ],
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
    retro = "## Retro\n(lead fills in at /phase-close)\n"
    if out.exists() and "## Retro" in (prev := out.read_text()):
        retro = prev[prev.index("## Retro"):]  # keep a retro already written
    lines += ["", retro]
    out.write_text("\n".join(lines))
    print(f"report: {out.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
