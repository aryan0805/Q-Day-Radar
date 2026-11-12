#!/usr/bin/env python3
"""Phase gate. Owned by lead. Run with:  uv run python scripts/gate.py <phase>

Runs the regression checks every phase must keep green, plus that phase's own
checks, prints a summary and writes a markdown report (.coord/gates/phase-<N>.md in the
dev repo; the system temp dir where that folder does not exist).
Exit code 0 = gate passed.

To add a check for a phase: append to PHASE_CHECKS[N]. A check is either
  Cmd("label", ["argv", ...])          passes when the command exits 0
  Py("label", function)                function returns (ok: bool, detail: str)
"""

from __future__ import annotations

import hashlib
import json
import math
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


def full_suite(paths: list[str] | None = None) -> tuple[bool, str]:
    """Run the non-hardware suite once (or only `paths`, for a sub-phase checkpoint), with a
    JUnit report the keyword checks reuse."""
    xml = Path(tempfile.gettempdir()) / f"qday-gate-{os.getpid()}.xml"
    r = subprocess.run(
        [PY, "-m", "pytest", *(paths or []), "-m", "not hardware", "-p", "no:cacheprovider",
         f"--junitxml={xml}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
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
        hits = [
            s
            for cls, name, s in _SUITE["cases"]
            if cls.startswith(prefix) and expr.lower() in f"{cls}.{name}".lower()
        ]
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
    "name",
    "kind",
    "n_qubits",
    "depth",
    "two_qubit_gates",
    "transpile",
    "success_probability",
    "theoretical_success",
    "shots",
    "seed_simulator",
    "qiskit_version",
    "timestamp",
    "chance_baseline",
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
    "name",
    "kind",
    "noise_model",
    "shots",
    "seed_simulator",
    "success_probability",
    "wilson_95",
    "theoretical_success",
    "chance_baseline",
    "normalized_score",
    "hellinger_vs_ideal",
    "signal",
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
    total = sum(
        json.loads((b / "plan.json").read_text())["total_estimated_seconds"] for b in _p2_batches()
    )
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


# ---------- phase 3: resource estimation ----------

P3_EST = ROOT / "results" / "estimate"
P3_LIT = ROOT / "quantum" / "estimate" / "literature.yaml"
P3_FACTCHECK = ROOT / "tests" / "phase3" / "factcheck.json"
P3_TARGETS = ("rsa2048", "ecc256", "aes128")
P3_SCENARIOS = ("optimistic", "median", "pessimistic")
P3_MAX_RATIO = 3.0
P3_MIN_SIZES = 5
P3_MIN_BASES = 3
P3_MIN_SHARED = 4
P3_MAX_FILE_BYTES = 5_000_000  # stored circuits are gzipped (human decision, gate 3)
P3_POOR_FIT = 0.05  # |signed residual| or holdout rel_error above this needs a caveat
P3_LABELS = ("measured", "extrapolated", "projection", "literature")
P3_PHYSICAL_TARGETS = ("rsa2048", "ecc256")  # the literature gives physical figures for these


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _p3_cases(tool: str) -> dict[str, dict]:
    d = P3_EST / tool
    return {p.stem: _load(p) for p in sorted(d.glob("*.json"))} if d.exists() else {}


def _p3_literature() -> list[dict]:
    import yaml  # pyyaml joins the default deps in P3 task 1

    data = yaml.safe_load(P3_LIT.read_text())
    return data if isinstance(data, list) else data.get("entries", [])


def _order(a: int, n: int) -> int:
    from math import gcd

    if gcd(a, n) != 1:
        raise ValueError(f"base {a} is not coprime to N={n}")
    x, r = a % n, 1
    while x != 1:
        x, r = (x * a) % n, r + 1
    return r


def p3_env() -> tuple[bool, str]:
    import importlib.metadata as md

    path = P3_EST / "env.json"
    if not path.exists():
        return False, "results/estimate/env.json missing"
    env = _load(path)
    problems = []
    for pkg in ("qsharp", "qualtran"):
        try:
            __import__(pkg)
            have = md.version(pkg)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{pkg} does not import: {exc}")
            continue
        if env.get(pkg) != have:
            problems.append(f"{pkg} installed {have}, env.json says {env.get(pkg)}")
    ok_msg = f"qsharp {env.get('qsharp')}, qualtran {env.get('qualtran')}"
    return not problems, "; ".join(problems) or ok_msg


def p3_literature_checked() -> tuple[bool, str]:
    try:
        entries = _p3_literature()
    except Exception as exc:  # noqa: BLE001
        return False, f"literature.yaml: {exc}"
    if not entries:
        return False, "literature.yaml has no entries"
    fc = _load(P3_FACTCHECK) if P3_FACTCHECK.exists() else {}
    problems = []
    for e in entries:
        eid = e.get("id")
        if not str(e.get("source_url", "")).startswith("https://"):
            problems.append(f"{eid}: no https source_url")
        if not e.get("locator"):
            problems.append(f"{eid}: no locator")
        if fc.get(eid, {}).get("status") != "verified":
            problems.append(f"{eid}: fact-check {fc.get(eid, {}).get('status', 'missing')}")
    targets = {e.get("target") for e in entries}
    missing = [t for t in P3_TARGETS if t not in targets]
    if missing:
        problems.append(f"no literature for {missing}")
    return not problems, "; ".join(problems[:6]) or f"{len(entries)} entries, all verified"


def _p3_toffoli_equiv(c: dict, tool: str) -> float:
    k = c["rotation_t_cost"]
    if tool == "qdk":
        lc = c["logical_counts"]
        return lc["ccz_count"] + lc["ccix_count"] + lc["t_count"] / 4 + lc["rotation_count"] * k / 4
    ct = c["counts"]
    return ct["toffoli"] + ct["t"] / 4 + ct["rotations"] * k / 4


def p3_toffoli_equiv_consistent() -> tuple[bool, str]:
    problems, eps, tcost, n = [], set(), set(), 0
    for tool in ("qdk", "qualtran"):
        for case, c in _p3_cases(tool).items():
            n += 1
            try:
                want = _p3_toffoli_equiv(c, tool)
                eps.add(c["rotation_eps"])
                tcost.add(c["rotation_t_cost"])
            except (KeyError, TypeError) as exc:
                problems.append(f"{tool}/{case}: missing {exc}")
                continue
            if abs(c.get("toffoli_equiv", -1) - want) > 1e-6 * max(1.0, want):
                problems.append(f"{tool}/{case}: toffoli_equiv {c.get('toffoli_equiv')} != {want}")
    if len(eps) > 1 or len(tcost) > 1:
        problems.append(f"rotation_eps {sorted(eps)} / rotation_t_cost {sorted(tcost)} differ")
    if n == 0:
        problems.append("no estimate files")
    return not problems, "; ".join(problems[:6]) or f"{n} files consistent"


def p3_qdk_complete() -> tuple[bool, str]:
    qdk = _p3_cases("qdk")
    problems = [f"no QDK file for {name}" for name in P1_REQUIRED if name not in qdk]
    sizes: dict[int, set[int]] = {}
    for case, c in qdk.items():
        if case.startswith(("shor", "beauregard")) and c.get("base_a") is None:
            problems.append(f"{case}: no base_a")
        if case.startswith("beauregard_N"):
            sizes.setdefault(c["N"], set()).add(c["base_a"])
    if len(sizes) < P3_MIN_SIZES:
        problems.append(f"scaling family has {len(sizes)} sizes, need {P3_MIN_SIZES}")
    for N, bases in sorted(sizes.items()):
        if len(bases) < P3_MIN_BASES:
            problems.append(f"N={N}: {len(bases)} bases, need {P3_MIN_BASES}")
        if all(_order(a, N) == 2 for a in bases):
            problems.append(f"N={N}: only order-2 bases")
    return not problems, "; ".join(problems[:6]) or (
        f"7 registry + {sum(map(len, sizes.values()))} scaling cases over N={sorted(sizes)}"
    )


def p3_crosscheck() -> tuple[bool, str]:
    path = P3_EST / "crosscheck.json"
    if not path.exists():
        return False, "crosscheck.json missing"
    qdk, qt = _p3_cases("qdk"), _p3_cases("qualtran")
    decisions = (ROOT / "docs" / "DECISIONS.md").read_text()
    problems, kinds, over = [], {"same_circuit": 0, "same_function": 0}, []
    for row in _load(path).get("cases", []):
        a, b = qdk.get(row.get("qdk")), qt.get(row.get("qualtran"))
        if a is None or b is None:
            problems.append(f"{row.get('case')}: per-case file missing")
            continue
        kinds[row.get("kind")] = kinds.get(row.get("kind"), 0) + 1
        if row.get("kind") == "same_circuit" and (
            not a.get("circuit_sha256") or a.get("circuit_sha256") != b.get("circuit_sha256")
        ):
            problems.append(f"{row.get('case')}: tools costed different circuits (circuit_sha256)")
        pairs = {
            "ratio_logical_qubits": (a["logical_counts"]["num_qubits"], b["logical_qubits"]),
            "ratio_toffoli_equiv": (a["toffoli_equiv"], b["toffoli_equiv"]),
        }
        for key, (x, y) in pairs.items():
            ratio = max(x, y) / min(x, y) if min(x, y) > 0 else float("inf")
            if abs(row.get(key, -1) - ratio) > 1e-6 * ratio:
                problems.append(f"{row['case']}: {key} {row.get(key)} != recomputed {ratio:.4g}")
            if ratio > P3_MAX_RATIO and row["case"] not in decisions:
                over.append(f"{row['case']} {key}={ratio:.3g}")
    for k in ("same_circuit", "same_function"):
        if kinds[k] < P3_MIN_SHARED:
            problems.append(f"{kinds[k]} {k} cases, need {P3_MIN_SHARED}")
    if over:
        problems.append("over 3x, not explained in DECISIONS.md: " + ", ".join(over[:4]))
    return not problems, "; ".join(problems[:6]) or (
        f"{kinds['same_circuit']} same_circuit, {kinds['same_function']} same_function; "
        "every ratio recomputed, every >3x gap explained"
    )


def p3_scaling() -> tuple[bool, str]:
    path = P3_EST / "scaling.json"
    if not path.exists():
        return False, "scaling.json missing"
    fits = _load(path).get("fits", [])
    problems, per_tool = [], {"qdk": 0, "qualtran": 0}
    for f in fits:
        tag = f"{f.get('estimator')}/{f.get('quantity')}"
        pts, res = f.get("points", []), f.get("residuals", [])
        if len(pts) < P3_MIN_SIZES:
            problems.append(f"{tag}: {len(pts)} points")
        if sorted(p["n_bits"] for p in pts) != sorted(r["n_bits"] for r in res):
            problems.append(f"{tag}: residuals don't cover every point")
        for p in pts:
            if p.get("N") and p.get("bases") and all(_order(a, p["N"]) == 2 for a in p["bases"]):
                problems.append(f"{tag}: N={p['N']} fitted from order-2 bases only")
        if not f.get("holdout") or f["holdout"].get("rel_error") is None:
            problems.append(f"{tag}: no holdout")
        if (f.get("extrapolated") or {}).get("n_bits") != 2048:
            problems.append(f"{tag}: no n=2048 extrapolation")
        if f.get("estimator") in per_tool:
            per_tool[f["estimator"]] += 1
    problems += [f"{t}: {n} fits, need 2" for t, n in per_tool.items() if n < 2]
    selected: dict[tuple, int] = {}
    for f in fits:
        key = (f.get("estimator"), f.get("quantity"))
        selected[key] = selected.get(key, 0) + bool(f.get("selected"))
        ext = f.get("extrapolated") or {}
        worst = max((abs(r.get("rel", 0)) for r in f.get("residuals", [])), default=0)
        hold = (f.get("holdout") or {}).get("rel_error") or 0
        poor = f.get("curved") or worst > P3_POOR_FIT or hold > P3_POOR_FIT
        if poor and not (f.get("caveat") and ext.get("low") and ext.get("high")):
            problems.append(
                f"{key} {f.get('model')}: residual {worst:.3f} / holdout {hold:.3f} "
                "needs a caveat and low/high range"
            )
    problems += [f"{k}: {n} selected fits, need exactly 1" for k, n in selected.items() if n != 1]
    return not problems, "; ".join(problems[:6]) or f"{len(fits)} fits, residuals and holdout each"


def p3_calibration() -> tuple[bool, str]:
    path = P3_EST / "calibration.json"
    if not path.exists():
        return False, "calibration.json missing"
    ids = {e.get("id") for e in _p3_literature()}
    rows = _load(path).get("comparisons", [])
    problems = [
        f"{r.get('target')}: unknown literature_id {r.get('literature_id')}"
        for r in rows
        if r.get("literature_id") not in ids
    ]
    problems += [f"{r.get('target')}: no ratio" for r in rows if not r.get("ratio")]
    covered = {r.get("target") for r in rows}
    problems += [f"no calibration for {t}" for t in P3_TARGETS if t not in covered]
    problems += [
        f"{r.get('target')}/{r.get('quantity')}: label {r.get('label')!r}"
        for r in rows
        if r.get("label") not in P3_LABELS
    ]
    for t in P3_PHYSICAL_TARGETS:
        got = {r.get("quantity") for r in rows if r.get("target") == t}
        problems += [
            f"{t}: no physical-model calibration row for {q}"
            for q in ("physical_qubits", "runtime_seconds")
            if q not in got
        ]
    ok_msg = f"{len(rows)} comparisons over {sorted(covered)}"
    return not problems, "; ".join(problems[:6]) or ok_msg


def p3_scenarios() -> tuple[bool, str]:
    path = P3_EST / "scenarios.json"
    if not path.exists():
        return False, "scenarios.json missing"
    s = _load(path)
    ids = {e.get("id") for e in _p3_literature()}
    problems = []
    for name in P3_SCENARIOS:
        sc = s.get("scenarios", {}).get(name)
        if not sc:
            problems.append(f"scenario {name} missing")
            continue
        bad = [i for i in sc.get("source_ids", []) if i not in ids] or (
            [] if sc.get("source_ids") else ["(none)"]
        )
        if bad:
            problems.append(f"{name}: source_ids not in literature {bad}")
    for t in P3_TARGETS:
        tgt = s.get("targets", {}).get(t)
        if not tgt or not tgt.get("logical_source"):
            problems.append(f"target {t} missing or has no logical_source")
            continue
        for name in P3_SCENARIOS:
            r = tgt.get("by_scenario", {}).get(name, {})
            for key in ("logical_qubits", "physical_qubits", "runtime_seconds", "code_distance"):
                if not (isinstance(r.get(key), (int, float)) and r[key] > 0):
                    problems.append(f"{t}/{name}: {key} = {r.get(key)}")
    if s.get("targets", {}).get("aes128", {}).get("peel_last_sbox") is not False:
        problems.append("aes128.peel_last_sbox is not false")
    return not problems, "; ".join(problems[:6]) or "3 scenarios x 3 targets, all positive"


def p3_no_large_files() -> tuple[bool, str]:
    big = [
        f"{p.relative_to(ROOT)} {p.stat().st_size / 1e6:.1f} MB"
        for p in P3_EST.rglob("*")
        if p.is_file() and p.stat().st_size > P3_MAX_FILE_BYTES
    ]
    limit = f"every file under results/estimate <= {P3_MAX_FILE_BYTES / 1e6:.0f} MB"
    return not big, "; ".join(big[:4]) or limit


def p3_strict(expr: str) -> Callable[[], tuple[bool, str]]:
    return pytest_selects(expr, path="tests/phase3", strict=True)


# ---------- phase 4: risk engine ----------

P4_CBOM = ROOT / "quantum" / "risk" / "data" / "demo_cbom.cdx.json"
P4_TIMELINE = ROOT / "results" / "risk" / "timeline.json"
P4_WEB = ROOT / "web" / "public" / "data"
P4_FAMILY_TARGET = {
    "RSA": "rsa2048",
    "ECC": "ecc256",
    "AES": "aes128",
    "SHA": "aes128",
    "ML-KEM": None,
    "ML-DSA": None,
    "SLH-DSA": None,
}
P4_DOUBLING = {"optimistic": 0, "median": None, "pessimistic": 1}  # index into ci95, None = point
P4_YEAR_S = 365.25 * 86400
P4_UNIT_S = {
    "second": 1.0,
    "seconds": 1.0,
    "s": 1.0,
    "minute": 60.0,
    "minutes": 60.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "day": 86400.0,
    "days": 86400.0,
}
P4_QEC_FAMILY = "surface_code_planar"  # every Phase 3 scenario
P4_MAX_SURVEY_GAP = 10.0
P4_REL = 1e-6


def _close(a, b, rel: float = P4_REL) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


def _p4_lit() -> dict[str, dict]:
    return {e.get("id"): e for e in _p3_literature()}


def p4_cbom() -> tuple[bool, str]:
    if not P4_CBOM.exists():
        return False, f"{P4_CBOM.relative_to(ROOT)} missing"
    text = P4_CBOM.read_text()
    problems = []
    try:
        from cyclonedx.schema import SchemaVersion
        from cyclonedx.validation.json import JsonStrictValidator

        err = JsonStrictValidator(SchemaVersion.V1_6).validate_str(text)
        if err:
            problems.append(f"CycloneDX 1.6 schema: {str(err)[:120]}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"schema validation unavailable: {exc}")
    bom = json.loads(text)
    if bom.get("specVersion") != "1.6":
        problems.append(f"specVersion {bom.get('specVersion')}")
    comps = [c for c in bom.get("components", []) if c.get("type") == "cryptographic-asset"]
    if not 35 <= len(comps) <= 50:
        problems.append(f"{len(comps)} cryptographic assets, need 35-50")
    meta = {p.get("name"): p.get("value") for p in bom.get("metadata", {}).get("properties", [])}
    if meta.get("qday:fictional") != "true":
        problems.append("metadata property qday:fictional != 'true'")
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from quantum.risk.models import dump_cbom, parse_cbom

        if json.loads(dump_cbom(parse_cbom(text))) != bom:
            problems.append("round-trip through quantum.risk.models changes the CBOM")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"round-trip: {type(exc).__name__}: {exc}")
    return not problems, "; ".join(problems[:5]) or f"{len(comps)} assets, valid 1.6, round-trips"


def _p4_fit(points: list[dict]) -> tuple[float, list]:
    from scipy import stats

    xs = [p["year"] for p in points]
    ys = [math.log2(p["qubits"]) for p in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    a = my - b * mx
    ssr = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys, strict=True))
    se = math.sqrt(ssr / (n - 2) / sxx)
    t = stats.t.ppf(0.975, n - 2)
    ci = [1 / (b + t * se), 1 / (b - t * se) if b - t * se > 0 else None]
    return 1 / b, ci


def _p4_frontier(points: list[dict]) -> list[dict]:
    """Record so far: for each year, the largest device announced up to that year."""
    out, best = [], 0
    for p in sorted(points, key=lambda p: (p["year"], p["qubits"])):
        best = max(best, p["qubits"])
        if out and out[-1]["year"] == p["year"]:
            out[-1] = {"year": p["year"], "qubits": best}
        else:
            out.append({"year": p["year"], "qubits": best})
    return out


def _p4_expected(t: str, sc: str, model: dict, lit: dict, scen: dict) -> dict:
    """min(model, every applicable paper feed) for qubits and runtime: (value, source, bound)."""
    p_sc = scen["physical_error_rate"]
    best = {
        "physical_qubits": (model["physical_qubits"], "model", None),
        "runtime_seconds": (model["runtime_seconds"], "model", None),
    }
    for eid, e in sorted(lit.items(), key=lambda kv: str(kv[0])):
        f = e.get("feeds") or {}
        if f.get("target") != t or f.get("qec_family") != P4_QEC_FAMILY:
            continue
        if f.get("kind") != "physical_qubits":
            raise ValueError(f"{eid}: feeds kind {f.get('kind')!r}; only physical_qubits may feed")
        if p_sc > f["physical_error_rate"]:
            continue
        key, val = "physical_qubits", float(e["value"])
        if val < best[key][0]:
            best[key] = (val, eid, f.get("bound"))
    return best


def p4_timeline() -> tuple[bool, str]:
    if not P4_TIMELINE.exists():
        return False, "results/risk/timeline.json missing"
    tl, lit = _load(P4_TIMELINE), _p4_lit()
    est_all = _load(P3_EST / "scenarios.json")
    est, scen = est_all["targets"], est_all["scenarios"]
    problems = []
    pts = tl.get("points", [])
    if len(pts) < 6:
        problems.append(f"{len(pts)} timeline points, need 6")
    for p in pts:
        e = lit.get(p.get("literature_id"))
        if not e or e.get("target") != "timeline":
            problems.append(f"point {p.get('literature_id')}: no timeline literature entry")
        elif not (_close(float(e.get("value")), p["qubits"]) and e.get("year") == p["year"]):
            problems.append(f"point {p['literature_id']} != literature value/year")
    if len(pts) >= 3:
        frontier = _p4_frontier(pts)
        d, ci = _p4_fit(frontier)
        fit = tl.get("fit", {})
        if not (
            _close(fit.get("doubling_years"), d)
            and all(_close(x, y) for x, y in zip(fit.get("ci95", [None, None]), ci, strict=False))
        ):
            problems.append(
                f"fit {fit.get('doubling_years')} {fit.get('ci95')} != "
                f"recomputed on the frontier {d:.6g} {ci}"
            )
        if (fit.get("holdout") or {}).get("rel_error") is None:
            problems.append("no holdout")
        record = frontier[-1]
        base = tl.get("baseline", {})
        if base.get("qubits") != record["qubits"]:
            problems.append(f"baseline {base.get('qubits')} is not the record {record['qubits']}")
        cap, as_of = tl.get("runtime_cap_years"), tl.get("as_of_year")
        crqc_by: dict[str, dict] = {}
        for sc, idx in P4_DOUBLING.items():
            s = tl.get("scenarios", {}).get(sc, {})
            want_d = d if idx is None else ci[idx]
            if not _close(s.get("doubling_years"), want_d):
                problems.append(f"{sc}: doubling {s.get('doubling_years')} != {want_d}")
            for t in P3_TARGETS:
                r = s.get("targets", {}).get(t)
                if not r:
                    problems.append(f"{sc}/{t} missing")
                    continue
                want = _p4_expected(t, sc, est[t]["by_scenario"][sc], lit, scen[sc])
                for key in ("physical_qubits", "runtime_seconds"):
                    val, src, bound = want[key]
                    src_key = "physical_source" if key == "physical_qubits" else "runtime_source"
                    if not _close(r.get(key), val) or r.get(src_key) != src:
                        problems.append(
                            f"{sc}/{t}: {key} {r.get(key)} from {r.get(src_key)} "
                            f"!= min rule {val:.4g} from {src}"
                        )
                    if key == "physical_qubits" and r.get("physical_bound") != bound:
                        problems.append(
                            f"{sc}/{t}: physical_bound {r.get('physical_bound')} != {bound}"
                        )
                P, R = want["physical_qubits"][0], want["runtime_seconds"][0]
                feasible = R / P4_YEAR_S <= cap
                doublings = max(0.0, math.log2(P / record["qubits"]))
                crqc = as_of + want_d * doublings if feasible and want_d else None
                crqc_by.setdefault(t, {})[sc] = crqc
                if r.get("feasible") != feasible or not _close(r.get("crqc_year"), crqc):
                    problems.append(f"{sc}/{t}: crqc_year {r.get('crqc_year')} != {crqc}")
        for t, by in crqc_by.items():
            seq = [math.inf if by.get(sc) is None else by[sc] for sc in P4_DOUBLING]
            if seq != sorted(seq):
                problems.append(f"{t}: crqc not ordered optimistic <= median <= pessimistic {seq}")
    sv = tl.get("survey_check") or {}
    if sv.get("literature_id") not in lit:
        problems.append("survey_check has no literature entry")
    elif (
        abs(sv.get("delta_years", 1e9)) > P4_MAX_SURVEY_GAP
        and "survey_check" not in (ROOT / "docs" / "DECISIONS.md").read_text()
    ):
        problems.append(f"survey gap {sv.get('delta_years')} y not explained in DECISIONS.md")
    return not problems, "; ".join(problems[:5]) or (
        f"{len(pts)} points, doubling {tl['fit']['doubling_years']:.3g} y recomputed, "
        "every crqc_year matches"
    )


def _p4_deprecated(a: dict) -> bool:
    """Classical security below 112 bits (SP 800-131A Rev. 2; SHA-1 via SP 800-57 Pt 1 Table 3).

    Plain SHA-1 counts only where collision resistance matters (signature or hash use);
    HMAC/KDF uses of SHA-1 stay acceptable per SP 800-131A, and are a different algorithm string.
    """
    bits, fam = a.get("key_bits"), a.get("family")
    if a.get("algorithm") == "SHA-1":
        return a.get("usage") in ("signature", "hash")
    if bits is None:
        return False
    return (fam == "RSA" and bits < 2048) or (fam == "ECC" and bits < 224)


P4_V2_TOL = 1.5  # fixed at task 15, before BUILD
P4_V2_CONSISTENCY = "g2025_physical_qubits_rsa2048"  # two-sided: within 1.5x
P4_V2_HOLDOUT = "google2026_physical_qubits_ecc256"  # one-sided: <= 1.5x the stated bound


def p4_phase3_still_holds() -> tuple[bool, str]:
    """Phase 3's data checks (not its test run, which gate 4's full suite covers)."""
    fns = [
        p3_env,
        p3_literature_checked,
        p3_qdk_complete,
        p3_toffoli_equiv_consistent,
        p3_crosscheck,
        p3_scaling,
        p3_calibration,
        p3_scenarios,
        p3_no_large_files,
    ]
    bad = []
    for fn in fns:
        ok, detail = fn()
        if not ok:
            bad.append(f"{fn.__name__}: {detail[:80]}")
    return not bad, "; ".join(bad) or f"{len(fns)} phase 3 data checks pass"


P4_V2_REGISTERED = {"code_distance": 25, "hot_patch_qubits": 1352,
                    "cold_fraction": 1280 / 1409, "compute_region_qubits": 170352.0}


def p4_physical_v2() -> tuple[bool, str]:
    """Human decision (2026-11-08): v2 failed its holdout; the gate checks that the result is
    recorded truthfully, the registered parameters were not changed, and no scenario adopts v2."""
    rows = _load(P3_EST / "calibration.json").get("comparisons", [])
    lit = _p4_lit()
    problems, msg = [], []
    for lid, two_sided in ((P4_V2_CONSISTENCY, True), (P4_V2_HOLDOUT, False)):
        hit = [r for r in rows if r.get("estimator") == "physical_v2"
               and r.get("quantity") == "physical_qubits" and r.get("literature_id") == lid]
        if len(hit) != 1 or lid not in lit:
            problems.append(f"{lid}: {len(hit)} physical_v2 rows")
            continue
        r = hit[0]
        ratio = float(r["ours"]) / float(lit[lid]["value"])  # recomputed, not read
        within = (1 / P4_V2_TOL <= ratio <= P4_V2_TOL) if two_sided else ratio <= P4_V2_TOL
        if (r.get("tolerance") or {}).get("within") is not within:
            problems.append(f"{lid}: row says within={r.get('tolerance', {}).get('within')}, "
                            f"recomputed {within} ({ratio:.4g}x)")
        for k, v in P4_V2_REGISTERED.items():
            if not _close((r.get("v2") or {}).get(k), v):
                problems.append(f"{lid}: v2.{k} {(r.get('v2') or {}).get(k)} != registered {v}")
        msg.append(f"{lid} {ratio:.3g}x {'pass' if within else 'FAIL'}")
        v2_value = float(r["ours"])
        est = _load(P3_EST / "scenarios.json")["targets"][r.get("target", "")]["by_scenario"]
        if any(_close(s["physical_qubits"], v2_value) for s in est.values()):
            problems.append(f"{lid}: a scenario uses the v2 value, but v2 failed its holdout")
    return not problems, "; ".join(problems) or (
        "recorded truthfully, registered parameters unchanged, not adopted: " + ", ".join(msg))


def p4_ecc_inputs_current() -> tuple[bool, str]:
    src = _load(P3_EST / "scenarios.json")["targets"]["ecc256"]["logical_source"]
    lit, fc = _p4_lit(), (_load(P3_FACTCHECK) if P3_FACTCHECK.exists() else {})
    ids = src.get("literature_ids", [])
    problems = [
        f"{i}: not a verified literature entry"
        for i in ids
        if i not in lit or fc.get(i, {}).get("status") != "verified"
    ]
    problems += [
        f"{i}: superseded by {lit[i]['superseded_by']}"
        for i in ids
        if i in lit and lit[i].get("superseded_by")
    ]
    if not src.get("history"):
        problems.append("logical_source.history (Roetteler 2017) missing")
    return not problems, "; ".join(problems) or f"ECC-256 logical counts from {ids}"


def p4_inventory() -> tuple[bool, str]:
    path = P4_WEB / "inventory.json"
    if not path.exists() or not P4_TIMELINE.exists():
        return False, "inventory.json or timeline.json missing"
    import yaml

    inv, tl, lit = _load(path), _load(P4_TIMELINE), _p4_lit()
    weights = yaml.safe_load((ROOT / "quantum" / "risk" / "exposure.yaml").read_text())
    weights = weights.get("weights", weights)
    fc = _load(P3_FACTCHECK) if P3_FACTCHECK.exists() else {}
    problems, assets = [], inv.get("assets", [])
    cbom_ids = {
        c.get("bom-ref")
        for c in json.loads(P4_CBOM.read_text()).get("components", [])
        if c.get("type") == "cryptographic-asset"
    }
    if {a.get("id") for a in assets} != cbom_ids:
        problems.append("inventory asset ids != CBOM cryptographic-asset bom-refs")
    as_of = inv.get("as_of_year")
    for a in assets:
        fam = a.get("family")
        if fam not in P4_FAMILY_TARGET or a.get("attack_target") != P4_FAMILY_TARGET[fam]:
            problems.append(f"{a.get('id')}: family {fam} -> {a.get('attack_target')}")
        if not _close(a.get("exposure_weight"), float(weights.get(a.get("exposure"), -1))):
            problems.append(f"{a.get('id')}: exposure_weight != exposure.yaml")
        if P4_FAMILY_TARGET.get(fam) and not isinstance(a.get("key_bits"), int):
            problems.append(f"{a.get('id')}: key_bits missing")
        sid = (a.get("replacement") or {}).get("standard_id")
        if sid not in lit or fc.get(sid, {}).get("status") != "verified":
            problems.append(f"{a.get('id')}: replacement standard {sid!r} not verified")
    for sc in inv.get("scenarios", []):
        targets = tl["scenarios"][sc]["targets"]
        want = {}
        for a in assets:
            t = a.get("attack_target")
            crqc = as_of if _p4_deprecated(a) else (targets[t]["crqc_year"] if t else None)
            margin = (
                None
                if crqc is None
                else crqc - as_of - (a["shelf_life_years"] + a["migration_years"])
            )
            short = a["exposure_weight"] * max(0.0, -margin) if margin is not None else 0.0
            want[a["id"]] = (crqc, margin, short)
            got = a["by_scenario"][sc]
            for k, v in zip(("crqc_year", "margin_years", "shortfall"), want[a["id"]], strict=True):
                if not _close(got.get(k), v):
                    problems.append(f"{a['id']}/{sc}: {k} {got.get(k)} != {v}")
        order = sorted(
            want, key=lambda i: (-want[i][2], math.inf if want[i][1] is None else want[i][1], i)
        )
        for rank, i in enumerate(order, 1):
            got = next(x for x in assets if x["id"] == i)["by_scenario"][sc].get("rank")
            if got != rank:
                problems.append(f"{i}/{sc}: rank {got} != {rank}")

        def _fam_year(f: str, targets: dict = targets) -> float:
            t = P4_FAMILY_TARGET[f]
            y = targets[t]["crqc_year"] if t else None
            return math.inf if y is None else y

        fams = sorted(
            {a["family"] for a in assets if a["family"] in P4_FAMILY_TARGET},
            key=lambda f: (_fam_year(f), f),
        )
        if inv.get("family_order", {}).get(sc) != fams:
            problems.append(f"{sc}: family_order {inv.get('family_order', {}).get(sc)} != {fams}")
    order_msg = ", ".join(
        f"{s}: {' > '.join(inv.get('family_order', {}).get(s, [])[:3])}"
        for s in inv.get("scenarios", [])
    )
    return not problems, "; ".join(problems[:5]) or f"{len(assets)} assets recomputed; {order_msg}"


def p4_web_schemas() -> tuple[bool, str]:
    files = sorted(P4_WEB.glob("*.json")) if P4_WEB.exists() else []
    if not files:
        return False, "no web/public/data/*.json"
    from jsonschema import validators

    problems = []
    for f in files:
        if f.stat().st_size > P3_MAX_FILE_BYTES:
            problems.append(f"{f.name} over 5 MB")
        sch = P4_WEB / "schema" / f"{f.stem}.schema.json"
        if not sch.exists():
            problems.append(f"{f.name}: no schema")
            continue
        schema = _load(sch)
        cls = validators.validator_for(schema)
        cls.check_schema(schema)
        errs = sorted(cls(schema).iter_errors(_load(f)), key=lambda e: list(e.path))
        if errs:
            problems.append(f"{f.name}: {errs[0].message[:80]}")
    return not problems, "; ".join(problems[:5]) or f"{len(files)} data files valid against schemas"


def p4_strict(expr: str) -> Callable[[], tuple[bool, str]]:
    return pytest_selects(expr, path="tests/phase4", strict=True)


# ---------- phase 5: front end ----------
# Every threshold below was fixed at /phase-start 5, before BUILD (P5 process rule).

P5_WEB = ROOT / "web"
P5_OUT = P5_WEB / "out"
P5_SRC = P5_WEB / "src"
P5_SITES = ROOT / ".coord" / "gates" / "phase-5-sites.json"  # lead fills: urls, not secrets
# Used where that file does not exist (the public repo): URLs, not secrets.
P5_SITES_DEFAULT = {"project": "q-day-web", "production": "https://q-day-web-q-day.vercel.app"}
P5_SCREENS = ["/", "/lab/", "/scaling/", "/inventory/"]
P5_TOKENS_CSS = P5_SRC / "styles" / "tokens.css"
P5_BG_TOKENS = ["bg-0", "bg-1", "bg-2"]
P5_TEXT_TOKENS = ["text-1", "text-2", "q", "threat", "warn", "pqc", "sim-text"]
P5_GRAPHIC_TOKENS = ["sim", "line"]
P5_MIN_TEXT_CONTRAST = 4.5  # WCAG 2.2 AA, 1.4.3
P5_MIN_GRAPHIC_CONTRAST = 3.0  # WCAG 2.2 AA, 1.4.11 (sim only; line is decorative, reported)
P5_LH_MIN = {"performance": 0.90, "accessibility": 1.00}
P5_LH_MAX_LCP_MS = 2000.0
P5_LH_MAX_CLS = 0.05
P5_LH_RUNS = 3  # median of 3 per screen, Lighthouse mobile defaults
P5_HOME_JS_GZ_MAX = 200_000  # bytes, gzip -9, scripts index.html loads before any interaction
P5_TWEAK_SENTINEL = "QDAY_TWEAK_PANEL"
P5_TWEAK_UI_STRINGS = ["Copy tokens"]  # visible panel text; survives minification if shipped
P5_BYPASS_ENV = "VERCEL_AUTOMATION_BYPASS_SECRET"  # in the root .env only, never in web/
P5_SKIP_DIRS = {"node_modules", ".next", "out"}
P5_SECRET_PATTERNS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"ghp_[A-Za-z0-9]{36}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"xox[abprs]-[A-Za-z0-9-]{10,}",
    r"sk-[A-Za-z0-9_-]{20,}",
    r"crn:v1:",
    r"QISKIT_IBM_",
    r"/Users/[A-Za-z]",
    r"/home/[a-z]",
]
P5_FORBIDDEN_KEYS = r"(token|secret|password|passwd|api_?key|crn|instance|credential|local_path)"
P5_REQUIRED_HEADERS = {
    "strict-transport-security": ["max-age=63072000", "includesubdomains", "preload"],
    "x-content-type-options": ["nosniff"],
    "referrer-policy": ["strict-origin-when-cross-origin"],
    "permissions-policy": ["camera=()", "microphone=()", "geolocation=()"],
    "cross-origin-opener-policy": ["same-origin"],
}
P5_CSP_DIRECTIVES = {
    "default-src": "'self'",
    "img-src": "'self' data:",
    "font-src": "'self'",
    "connect-src": "'self'",
    "frame-ancestors": "'none'",
    "base-uri": "'self'",
    "form-action": "'none'",
}


def _p5_walk(base: Path):
    for p in base.rglob("*"):
        if p.is_file() and not (set(p.relative_to(base).parts[:-1]) & P5_SKIP_DIRS):
            yield p


def _p5_env_values() -> list[str]:
    env = ROOT / ".env"
    vals = []
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                v = line.split("=", 1)[1].strip().strip("'\"")
                if len(v) >= 8:
                    vals.append(v)
    return vals


def _p5_env(key: str) -> str | None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    return os.environ.get(key)


def p5_no_env_in_web() -> tuple[bool, str]:
    """No .env* under web/; no env reads in web/src or next.config (NODE_ENV only)."""
    import re

    if not P5_SRC.exists():
        return False, "web/src missing"
    problems = [str(p.relative_to(ROOT)) for p in _p5_walk(P5_WEB) if p.name.startswith(".env")]
    bad = re.compile(r"process\.env(?!\.NODE_ENV\b)|import\.meta\.env|NEXT_PUBLIC_")
    targets = list(_p5_walk(P5_SRC)) + list(P5_WEB.glob("next.config.*"))
    for p in targets:
        if p.suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if bad.search(line):
                    problems.append(f"{p.relative_to(ROOT)}:{i}")
    return not problems, "; ".join(problems[:5]) or f"{len(targets)} files scanned, no env reads"


def p5_canary_scan() -> tuple[bool, str]:
    """No .env value (held in memory, never printed) and no secret pattern in web/out or data."""
    import re

    if not P5_OUT.exists():
        return False, "web/out missing (build first)"
    values = _p5_env_values()
    pats = [re.compile(p) for p in P5_SECRET_PATTERNS]
    hits, n = [], 0
    for base in (P5_OUT, P4_WEB):
        for p in _p5_walk(base):
            n += 1
            text = p.read_bytes().decode("utf-8", errors="replace")
            if any(v in text for v in values):
                hits.append(f"{p.relative_to(ROOT)}: an .env value")
            hits += [f"{p.relative_to(ROOT)}: /{r.pattern}/" for r in pats if r.search(text)]
    if not values:
        hits.append("no .env values loaded, so the canary half of the scan did not run")
    n_out = sum(1 for _ in _p5_walk(P5_OUT))
    if not n_out or not any(P5_OUT.glob("*.html")):
        hits.append(f"out/ has {n_out} files and no top-level html, so the scan proves nothing")
    return not hits, "; ".join(hits[:5]) or f"{n} files, {len(values)} canaries, 0 hits"


def p5_data_keys_allowed() -> tuple[bool, str]:
    """No key in web/public/data that names a secret, a credential or a local path."""
    import re

    bad = re.compile(P5_FORBIDDEN_KEYS, re.I)
    hits = []

    def walk(x, where):
        if isinstance(x, dict):
            for k, v in x.items():
                if bad.search(str(k)):
                    hits.append(f"{where}.{k}")
                walk(v, f"{where}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{where}[{i}]")

    files = sorted(P4_WEB.glob("*.json"))
    for f in files:
        walk(_load(f), f.stem)
    return not hits, "; ".join(hits[:5]) or f"{len(files)} data files, no forbidden keys"


def p5_web_tracked() -> tuple[bool, str]:
    """Every non-ignored file under web/ is tracked: Vercel builds from git, so an untracked
    input the local build reads would make the deployed site differ (or fail to build)."""
    r = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "web"],
                       cwd=ROOT, capture_output=True, text=True)
    files = r.stdout.split()
    if files:
        return False, "untracked: " + ", ".join(files[:5])
    return True, "no untracked files in web/"


def p5_no_source_maps() -> tuple[bool, str]:
    if not P5_OUT.exists():
        return False, "web/out missing"
    maps = [p for p in _p5_walk(P5_OUT) if p.suffix == ".map"]
    refs = [
        p
        for p in _p5_walk(P5_OUT)
        if p.suffix in {".js", ".css"} and b"sourceMappingURL=" in p.read_bytes()
    ]
    bad = [str(p.relative_to(P5_OUT)) for p in maps + refs]
    return not bad, "; ".join(bad[:5]) or "no .map files, no sourceMappingURL"


def p5_no_third_party() -> tuple[bool, str]:
    """No page or stylesheet loads anything from another origin."""
    import re

    if not P5_OUT.exists():
        return False, "web/out missing"
    html_ref = re.compile(
        r"<(?:script|link|img|iframe|source|video|audio)\b[^>]*\b(?:src|href|srcset)="
        r"[\"']?(?:https?:)?//",
        re.I,
    )
    css_ref = re.compile(r"(?:url\(|@import)\s*[\"']?(?:https?:)?//", re.I)
    hosts = re.compile(r"fonts\.googleapis|fonts\.gstatic|googletagmanager|google-analytics|"
                       r"cdn\.jsdelivr|unpkg\.com|cdnjs\.", re.I)
    bad = []
    for p in _p5_walk(P5_OUT):
        if p.suffix in {".html", ".css", ".js"}:
            t = p.read_text(errors="replace")
            if (p.suffix == ".html" and html_ref.search(t)) or (
                p.suffix == ".css" and css_ref.search(t)
            ) or hosts.search(t):
                bad.append(str(p.relative_to(P5_OUT)))
    return not bad, "; ".join(bad[:5]) or "no third-party scripts, styles, fonts or images"


def p5_tweak_panel_absent() -> tuple[bool, str]:
    """The dev tweak panel exists in source (sentinel) and is absent from the production build."""
    if not P5_OUT.exists() or not P5_SRC.exists():
        return False, "web/src or web/out missing"
    import re

    # The sentinel must be a runtime string (quoted, outside comments): the production build
    # strips comments, so a comment sentinel would be absent from out/ even if the panel shipped.
    lit = re.compile(rf"[\"'`]{P5_TWEAK_SENTINEL}[\"'`]")
    in_src = False
    for p in _p5_walk(P5_SRC):
        if p.suffix in {".ts", ".tsx", ".js", ".jsx"}:
            code = re.sub(r"/\*.*?\*/", "", p.read_text(errors="replace"), flags=re.S)
            code = re.sub(r"//[^\n]*", "", code)
            in_src = in_src or bool(lit.search(code))
    if not in_src:
        why = "is not a runtime string in web/src, so its absence proves nothing"
        return False, f"{P5_TWEAK_SENTINEL} {why}"
    markers = [P5_TWEAK_SENTINEL.encode(), *(m.encode() for m in P5_TWEAK_UI_STRINGS)]
    leaked = [
        f"{p.relative_to(P5_OUT)}: {m.decode()}"
        for p in _p5_walk(P5_OUT)
        for m in markers
        if m in p.read_bytes()
    ]
    ok_msg = "runtime sentinel in src; it and the panel's UI strings absent from out/"
    return not leaked, "; ".join(leaked[:5]) or ok_msg


def _p5_hex(name: str, css: str) -> str | None:
    import re

    m = re.search(rf"--{re.escape(name)}\s*:\s*(#[0-9A-Fa-f]{{6}})\b", css)
    return m.group(1) if m else None


def _p5_contrast(a: str, b: str) -> float:
    def lum(h: str) -> float:
        c = [int(h[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    hi, lo = sorted([lum(a), lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def p5_token_contrast() -> tuple[bool, str]:
    """Every text token >= 4.5:1 and --sim >= 3:1 on every background, from the hex fallbacks."""
    if not P5_TOKENS_CSS.exists():
        return False, f"{P5_TOKENS_CSS.relative_to(ROOT)} missing"
    css = P5_TOKENS_CSS.read_text()
    problems, worst = [], {}
    for group, need in ((P5_TEXT_TOKENS, P5_MIN_TEXT_CONTRAST), (["sim"], P5_MIN_GRAPHIC_CONTRAST)):
        for fg in group:
            fh = _p5_hex(fg, css)
            if not fh:
                problems.append(f"--{fg} has no #rrggbb fallback")
                continue
            for bg in P5_BG_TOKENS:
                bh = _p5_hex(bg, css)
                if not bh:
                    problems.append(f"--{bg} has no #rrggbb fallback")
                    continue
                r = _p5_contrast(fh, bh)
                worst[fg] = min(worst.get(fg, 99.0), r)
                if r < need:
                    problems.append(f"--{fg} on --{bg} {r:.2f} < {need}")
    detail = ", ".join(f"{k} {v:.2f}" for k, v in worst.items())
    return not problems, "; ".join(sorted(set(problems))[:5]) or f"min ratios: {detail}"


def _p5_local_server():
    import functools
    import http.server
    import threading

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(P5_OUT))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def p5_lighthouse() -> tuple[bool, str]:
    """Lighthouse (mobile defaults) on the built site, median of 3 runs per screen."""
    import statistics

    if not P5_OUT.exists():
        return False, "web/out missing"
    srv, base = _p5_local_server()
    problems, rows = [], []
    try:
        for screen in P5_SCREENS:
            runs = []
            for _ in range(P5_LH_RUNS):
                out = Path(tempfile.gettempdir()) / f"qday-lh-{os.getpid()}.json"
                r = subprocess.run(
                    ["npm", "--prefix", "web", "exec", "--", "lighthouse", base + screen,
                     "--output=json", f"--output-path={out}", "--quiet",
                     "--only-categories=performance,accessibility",
                     "--chrome-flags=--headless=new"],
                    cwd=ROOT, capture_output=True, text=True,
                )
                if r.returncode != 0 or not out.exists():
                    return False, f"lighthouse failed on {screen}: {(r.stderr or '')[-200:]}"
                lh = json.loads(out.read_text())
                out.unlink()
                runs.append({
                    "performance": lh["categories"]["performance"]["score"],
                    "accessibility": lh["categories"]["accessibility"]["score"],
                    "lcp": lh["audits"]["largest-contentful-paint"]["numericValue"],
                    "cls": lh["audits"]["cumulative-layout-shift"]["numericValue"],
                })
            med = {k: statistics.median(x[k] for x in runs) for k in runs[0]}
            rows.append(f"{screen} perf {med['performance']:.2f} a11y {med['accessibility']:.2f} "
                        f"LCP {med['lcp']:.0f}ms CLS {med['cls']:.3f}")
            for k, need in P5_LH_MIN.items():
                if med[k] < need:
                    problems.append(f"{screen} {k} {med[k]:.2f} < {need}")
            if med["lcp"] >= P5_LH_MAX_LCP_MS:
                problems.append(f"{screen} LCP {med['lcp']:.0f} >= {P5_LH_MAX_LCP_MS:.0f} ms")
            if med["cls"] >= P5_LH_MAX_CLS:
                problems.append(f"{screen} CLS {med['cls']:.3f} >= {P5_LH_MAX_CLS}")
    finally:
        srv.shutdown()
    return not problems, "; ".join(problems + rows)


def p5_home_js_budget() -> tuple[bool, str]:
    """Gzipped size of every script out/index.html names (src, modulepreload and inline).
    A static lower bound only: chunks fetched after hydration are measured in a browser by
    reviewer's `bundle` tests (DECISIONS 2026-11-08 P5, GSAP fetched at load)."""
    import gzip
    import re

    idx = P5_OUT / "index.html"
    if not idx.exists():
        return False, "web/out/index.html missing"
    html = idx.read_text()
    srcs = re.findall(r"<script\b[^>]*\bsrc=[\"']([^\"']+)", html)
    srcs += re.findall(r"<link\b[^>]*rel=[\"']modulepreload[\"'][^>]*href=[\"']([^\"']+)", html)
    total, missing = 0, []
    for s in sorted(set(srcs)):
        f = P5_OUT / s.split("?")[0].lstrip("/")
        if not f.exists():
            missing.append(s)
            continue
        total += len(gzip.compress(f.read_bytes(), 9))
    for body in re.findall(r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S):
        total += len(gzip.compress(body.encode(), 9))
    if missing:
        return False, f"index.html references missing files: {missing[:3]}"
    ok = total <= P5_HOME_JS_GZ_MAX
    return ok, f"home JS {total:,} B gzipped (limit {P5_HOME_JS_GZ_MAX:,}), {len(set(srcs))} files"


# --- provenance: every figure on a pre-rendered page traces to web/public/data ---

_P5_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_P5_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
            "param", "source", "track", "wbr"}
_P5_SKIP_TAGS = {"script", "style", "title", "template"}


def _p5_figures(text: str) -> list[str]:
    """Figures in text, after removing identifiers like RSA-2048, ML-KEM-768, ibm_kingston, k2."""
    import re

    t = re.sub(r"[A-Za-z][\w]*(?:-[\w]+)*\d[\w-]*", " ", text)
    t = re.sub(r"\|[^|⟩]*⟩", " ", t)  # ket labels
    return re.findall(r"\d[\d,.]*", t)


def _p5_parse_number(text: str) -> tuple[float, float] | None:
    """(value, tolerance): tolerance is half a unit of the last digit shown."""
    import re

    t = text.replace("−", "-").replace(" ", "").replace(" ", "").replace(",", "")
    t = t.translate(_P5_SUP)
    m = re.search(r"([-+]?\d+(?:\.(\d+))?)\s*(?:(?:[×x]\s*10\^?|e)([-+]?\d+))?", t)
    if not m:
        return None
    mant, dec, exp = float(m.group(1)), m.group(2) or "", int(m.group(3) or 0)
    return mant * 10**exp, 0.5 * 10 ** (-len(dec)) * 10**exp


def _p5_resolve(ref: str):
    import re

    name, _, path = ref.partition(":")
    f = P4_WEB / f"{name}.json"
    if not f.exists():
        raise KeyError(f"no data file {name}.json")
    x = _load(f)
    for tok in re.findall(r"\[(\d+)\]|([^.\[\]]+)", path):
        x = x[int(tok[0])] if tok[0] else x[tok[1]]
    return x


def _p5_value_ok(ref: str, text: str, scale: float) -> str | None:
    """None if the displayed text matches the data value, else a reason."""
    try:
        v = _p5_resolve(ref)
    except (KeyError, IndexError, TypeError) as exc:
        return f"{ref}: does not resolve ({exc})"
    shown = " ".join(text.split())
    if v is None or isinstance(v, bool):
        return None if not _p5_figures(shown) else f"{ref}: null/bool shown as {shown!r}"
    if isinstance(v, str):
        return None if " ".join(v.split()) in shown else f"{ref}: {v!r} shown as {shown!r}"
    if isinstance(v, int | float):
        got = _p5_parse_number(shown)
        if got is None:
            return f"{ref}: no number in {shown!r}"
        val, tol = got
        want = v * scale
        if abs(val - want) > tol + 1e-9 * max(1.0, abs(want)):
            return f"{ref}: shown {shown!r}, data {want:g}"
        return None
    return f"{ref}: is a {type(v).__name__}, point data-src at a scalar"


def p5_provenance_static() -> tuple[bool, str]:
    """Every figure in out/*.html sits in a data-src element whose value matches the data,
    a data-axis group (chart ticks) or a data-literal element (reason listed in the report)."""
    from html.parser import HTMLParser

    pages = sorted(P5_OUT.rglob("*.html")) if P5_OUT.exists() else []
    if not pages:
        return False, "no web/out/*.html"
    stats = {"src": 0, "literal": []}
    problems: list[str] = []
    per_page: dict[str, int] = {}

    class Walker(HTMLParser):
        def __init__(self, page: str):
            super().__init__(convert_charrefs=True)
            self.page, self.stack = page, []  # [tag, attrs, buffer or None]

        def handle_starttag(self, tag, attrs):
            if tag in _P5_VOID:
                return
            a = dict(attrs)
            buf = [] if "data-src" in a else None
            self.stack.append([tag, a, buf])
            if "data-literal" in a:
                stats["literal"].append(f"{self.page}: {a.get('data-literal') or '(no reason)'}")

        def handle_endtag(self, tag):
            while self.stack:
                t, a, buf = self.stack.pop()
                if buf is not None:
                    stats["src"] += 1
                    per_page[self.page] = per_page.get(self.page, 0) + 1
                    why = _p5_value_ok(a["data-src"], "".join(buf), float(a.get("data-scale", 1)))
                    if why:
                        problems.append(f"{self.page}: {why}")
                if t == tag:
                    return

        def handle_data(self, data):
            for t, a, buf in reversed(self.stack):
                if buf is not None:
                    buf.append(data)
                    return
                if t in _P5_SKIP_TAGS or "data-literal" in a or "data-axis" in a:
                    return
            figs = _p5_figures(data)
            if figs:
                snippet = data.strip()[:40]
                problems.append(f"{self.page}: untraced figure {figs[0]!r} in {snippet!r}")

    for p in pages:
        rel = str(p.relative_to(P5_OUT))
        Walker(rel).feed(p.read_text(errors="replace"))
    for screen in P5_SCREENS:
        page = (screen.strip("/") + "/index.html").lstrip("/")
        if not per_page.get(page):
            problems.append(f"{page}: no data-src element, so nothing is traced")
    lits = stats["literal"]
    detail = f"{stats['src']} traced values, {len(lits)} literals"
    if lits:
        detail += " [" + "; ".join(lits[:12]) + ("; …" if len(lits) > 12 else "") + "]"
    return not problems, "; ".join(problems[:5] + [detail])


# --- readability (human tweak round 1, thresholds fixed before BUILD) ---

P5_FK_MAX_GRADE = 9.0  # Flesch-Kincaid grade, textstat
P5_MAX_WORDS_PER_SENTENCE = 20.0
P5_MIN_PLAIN_WORDS = 50  # fewer and the score means nothing
P5_PLAIN_TAGS = {"p", "li", "figcaption", "dd", "blockquote"}


def _p5_plain_text(html: str) -> tuple[str, int]:
    """Text of running-prose elements inside <main>, outside any data-layer="technical"
    element; also returns how many technical layers the page has."""
    from html.parser import HTMLParser

    out: list[str] = []
    n_tech = 0

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack: list[tuple[str, dict]] = []

        def handle_starttag(self, tag, attrs):
            nonlocal n_tech
            if tag in _P5_VOID:
                return
            a = dict(attrs)
            if a.get("data-layer") == "technical":
                n_tech += 1
            self.stack.append((tag, a))

        def handle_endtag(self, tag):
            while self.stack:
                t, a = self.stack.pop()
                if t in P5_PLAIN_TAGS and not any(x[0] in P5_PLAIN_TAGS for x in self.stack):
                    out.append("\n")
                if t == tag:
                    return

        def handle_data(self, data):
            tags = [t for t, _ in self.stack]
            if "main" not in tags or any(t in _P5_SKIP_TAGS for t in tags):
                return
            if any(a.get("data-layer") == "technical" for _, a in self.stack):
                return
            if any(t in P5_PLAIN_TAGS for t in tags):
                out.append(data)

    P().feed(html)
    return " ".join("".join(out).split("\n")).strip(), n_tech


def p5_readability() -> tuple[bool, str]:
    """Plain layer of each screen: Flesch-Kincaid grade <= 9 and <= 20 words per sentence
    (textstat); each screen has >= 1 technical layer (the two-layer structure)."""
    try:
        import textstat
    except ImportError:
        return False, "textstat not installed (builder adds it to pyproject)"
    problems, rows = [], []
    for screen in P5_SCREENS:
        f = P5_OUT / (screen.strip("/") + "/index.html").lstrip("/")
        if not f.exists():
            problems.append(f"{screen}: not built")
            continue
        text, n_tech = _p5_plain_text(f.read_text(errors="replace"))
        words = textstat.lexicon_count(text)
        sents = max(1, textstat.sentence_count(text))
        grade = textstat.flesch_kincaid_grade(text) if text else float("nan")
        wps = words / sents
        rows.append(f"{screen} grade {grade:.1f}, {wps:.1f} w/s, {words} words, {n_tech} tech")
        if words < P5_MIN_PLAIN_WORDS:
            problems.append(f"{screen}: only {words} plain words")
        elif grade > P5_FK_MAX_GRADE:
            problems.append(f"{screen}: grade {grade:.1f} > {P5_FK_MAX_GRADE}")
        if words and wps > P5_MAX_WORDS_PER_SENTENCE:
            problems.append(f"{screen}: {wps:.1f} words/sentence > {P5_MAX_WORDS_PER_SENTENCE}")
        if n_tech < 1:
            problems.append(f"{screen}: no data-layer=\"technical\" detail")
    return not problems, "; ".join(problems + rows)


# --- git hygiene ---


def p5_env_never_committed() -> tuple[bool, str]:
    r = subprocess.run(["git", "log", "--all", "--name-only", "--format="],
                       cwd=ROOT, capture_output=True, text=True)
    bad = sorted({p for p in r.stdout.split() if Path(p).name.startswith(".env")
                  and Path(p).name != ".env.example"})
    return not bad, ", ".join(bad) or "no .env file in any commit (only .env.example)"


def p5_hooks_and_ci() -> tuple[bool, str]:
    """gitleaks runs in a versioned pre-commit hook and in a GitHub Action on every push."""
    problems = []
    hp = subprocess.run(["git", "config", "core.hooksPath"], cwd=ROOT,
                        capture_output=True, text=True).stdout.strip()
    hook = ROOT / (hp or ".git/hooks") / "pre-commit"
    if hp != ".githooks":
        problems.append(f"core.hooksPath is {hp or 'unset'}, expected .githooks")
    if not hook.exists() or "gitleaks" not in hook.read_text() or not os.access(hook, os.X_OK):
        problems.append(f"{hook.relative_to(ROOT)} missing, not executable or not running gitleaks")
    wf = list((ROOT / ".github" / "workflows").glob("*.y*ml"))
    if not any("gitleaks" in f.read_text() and "push" in f.read_text() for f in wf):
        problems.append("no .github/workflows file runs gitleaks on push")
    return not problems, "; ".join(problems) or "pre-commit hook and GitHub Action run gitleaks"


def p5_github_secret_scanning(repo: str | None = None,
                              need_public: bool = False) -> tuple[bool, str]:
    target = [repo] if repo else []
    r = subprocess.run(["gh", "repo", "view", *target, "--json", "nameWithOwner"], cwd=ROOT,
                       capture_output=True, text=True) if _which("gh") else None
    if r is None or r.returncode != 0:
        return False, "gh CLI missing or not logged in (brew install gh && gh auth login)"
    repo = json.loads(r.stdout)["nameWithOwner"]
    vis = subprocess.run(["gh", "repo", "view", repo, "--json", "visibility", "--jq",
                          ".visibility"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if need_public and vis != "PUBLIC":
        return False, f"{repo} is {vis or 'unknown'}, expected PUBLIC"
    r = subprocess.run(["gh", "api", f"repos/{repo}", "--jq", ".security_and_analysis"],
                       cwd=ROOT, capture_output=True, text=True)
    raw = r.stdout.strip()
    sa = json.loads(raw) if raw and raw != "null" else {}  # private repos may return none
    # GitHub secret scanning needs a public repo (or paid GHAS); for a private repo the
    # gitleaks checks above are the secret check (DECISIONS 2026-11-08 P5, human task 1).
    need = [] if vis == "PRIVATE" else ["secret_scanning", "secret_scanning_push_protection"]
    off = [k for k in need if (sa.get(k) or {}).get("status") != "enabled"]
    dep = subprocess.run(["gh", "api", f"repos/{repo}/vulnerability-alerts", "-i"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    status_line = dep.splitlines()[0] if dep else ""
    if " 204" not in status_line:  # 204 = enabled, 404 = disabled
        off.append("dependabot alerts")
    scope = "private: Dependabot only, gitleaks covers secrets" if vis == "PRIVATE" else "public"
    return not off, f"{repo} ({scope}): " + (", ".join(off) + " not enabled" if off else "on")


def _which(cmd: str) -> bool:
    import shutil

    return shutil.which(cmd) is not None


# --- live site (URLs in P5_SITES, else P5_SITES_DEFAULT; bypass secret in root .env) ---


def _p5_sites() -> dict:
    return _load(P5_SITES) if P5_SITES.exists() else P5_SITES_DEFAULT


def _p5_fetch(url: str, bypass: bool = False, follow: bool = True):
    import urllib.error
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    headers = {"User-Agent": "qday-gate"}
    if bypass:
        secret = _p5_env(P5_BYPASS_ENV)
        if not secret:
            raise RuntimeError(f"{P5_BYPASS_ENV} not in the root .env")
        headers["x-vercel-protection-bypass"] = secret
    opener = urllib.request.build_opener(*([] if follow else [NoRedirect()]))
    try:
        r = opener.open(urllib.request.Request(url, headers=headers), timeout=30)
        return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def _p5_csp_problems(csp: str, pages: dict[str, bytes]) -> list[str]:
    import base64
    import re

    d = {}
    for part in csp.split(";"):
        bits = part.split()
        if bits:
            d[bits[0].lower()] = " ".join(bits[1:])
    problems = [f"CSP {k} is {d.get(k)!r}, expected {v!r}"
                for k, v in P5_CSP_DIRECTIVES.items() if d.get(k) != v]
    if "upgrade-insecure-requests" not in d:
        problems.append("CSP lacks upgrade-insecure-requests")
    script = d.get("script-src", d.get("default-src", ""))
    if "'unsafe-inline'" in script:
        dec = (ROOT / "docs" / "DECISIONS.md").read_text()
        if not any("P5" in ln and "unsafe-inline" in ln for ln in dec.splitlines()):
            problems.append("script-src has 'unsafe-inline' and no P5 decision records why")
        return problems
    for screen, body in pages.items():
        html = body.decode("utf-8", errors="replace")
        for attrs, code in re.findall(r"<script\b((?:(?!\bsrc=)[^>])*)>(.*?)</script>", html, re.S):
            if re.search(r"type=[\"']application/(?:ld\+)?json", attrs):
                continue
            h = base64.b64encode(hashlib.sha256(code.encode()).digest()).decode()
            if f"'sha256-{h}'" not in script:
                problems.append(f"{screen}: inline script sha256-{h[:10]}… not in script-src")
    return problems


def p5_live(kind: str, expected: Callable[[], str] | None = None) -> Callable[[], tuple[bool, str]]:
    """The deployed site (preview or production) serves HEAD, every screen returns 200 with the
    required headers, and every inline script's hash is in the CSP. With `expected`, the site
    must serve exactly that commit (phase 6: the public repo's main, whose SHAs differ)."""

    def _check() -> tuple[bool, str]:
        base = _p5_sites()[kind].rstrip("/")
        bypass = kind == "preview"
        head = expected() if expected else subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        problems, pages = [], {}
        st, _, body = _p5_fetch(base + "/build.json", bypass)
        commit = json.loads(body).get("commit") if st == 200 else None
        if expected and commit != head:
            problems.append(f"build.json commit {str(commit)[:10]} is not {head[:10]}")
        elif commit != head:
            # Vercel builds only web/ (its root directory), so a deployment of an ancestor
            # commit with an identical web/ tree serves exactly what HEAD would build.
            anc = commit and subprocess.run(["git", "merge-base", "--is-ancestor", commit, head],
                                            cwd=ROOT, capture_output=True).returncode == 0
            same = anc and subprocess.run(["git", "diff", "--quiet", commit, head, "--", "web"],
                                          cwd=ROOT).returncode == 0
            if not same:
                problems.append(f"build.json commit {str(commit)[:10]} is not HEAD {head[:10]} "
                                "or an ancestor with the same web/ tree")
        hdrs = {}
        for screen in P5_SCREENS:
            st, hdrs, body = _p5_fetch(base + screen, bypass)
            if st != 200:
                problems.append(f"{screen} -> HTTP {st}")
                continue
            pages[screen] = body
            for h, parts in P5_REQUIRED_HEADERS.items():
                got = hdrs.get(h, "").lower().replace(" ", "")
                problems += [f"{screen} {h} lacks {p}" for p in parts if p not in got]
        st, _, _ = _p5_fetch(base + "/no-such-page-qday/", bypass)
        if st != 404:
            problems.append(f"unknown path -> HTTP {st}, expected 404")
        if pages:
            problems += _p5_csp_problems(hdrs.get("content-security-policy", ""), pages)
        return not problems, "; ".join(problems[:6]) or f"{kind} {base}: HEAD, headers, CSP ok"

    return _check


def p5_preview_protected() -> tuple[bool, str]:
    base = _p5_sites()["preview"].rstrip("/")
    st, hdrs, _ = _p5_fetch(base + "/", bypass=False, follow=False)
    loc = hdrs.get("location", "")
    ok = st in (401, 403) or (300 <= st < 400 and "vercel.com" in loc)
    return ok, f"preview without login -> HTTP {st}" + (f" to {loc[:40]}" if loc else "")


def p5_observatory() -> tuple[bool, str]:
    import urllib.parse
    import urllib.request

    host = urllib.parse.urlparse(_p5_sites()["production"]).hostname
    url = f"https://observatory-api.mdn.mozilla.net/api/v2/scan?host={host}"
    req = urllib.request.Request(url, method="POST", headers={"User-Agent": "qday-gate"})
    res = json.loads(urllib.request.urlopen(req, timeout=60).read())
    grade = res.get("grade")
    return grade == "A+", f"{host}: Observatory {grade} (score {res.get('score')})"


P5_SSL_OK_GRADES = {"A", "A+"}  # human decision 2026-11-08: A accepted (scanner gets a 403)


def _p5_hsts_at(ip: str, host: str) -> str:
    """The Strict-Transport-Security header served by one server address (SNI = host)."""
    import http.client
    import socket
    import ssl

    ctx = ssl.create_default_context()
    raw = socket.create_connection((ip, 443), timeout=20)
    conn = http.client.HTTPConnection(host, 443, timeout=20)
    conn.sock = ctx.wrap_socket(raw, server_hostname=host)
    conn.request("GET", "/", headers={"Host": host, "User-Agent": "qday-gate"})
    return conn.getresponse().getheader("Strict-Transport-Security") or ""


def p5_ssllabs() -> tuple[bool, str]:
    """SSL Labs grades every endpoint A or A+ with no warnings, and the gate itself reads the
    required HSTS header on each endpoint's address. (Vercel's bot protection answers the SSL
    Labs HTTP probe with 403, so SSL Labs cannot see HSTS and caps the grade at A.)"""
    import urllib.parse
    import urllib.request

    host = urllib.parse.urlparse(_p5_sites()["production"]).hostname
    api = f"https://api.ssllabs.com/api/v3/analyze?host={host}&fromCache=on&maxAge=24&all=done"
    deadline = time.time() + 600
    while time.time() < deadline:
        req = urllib.request.Request(api, headers={"User-Agent": "qday-gate"})
        res = json.loads(urllib.request.urlopen(req, timeout=60).read())
        if res.get("status") in ("READY", "ERROR"):
            break
        time.sleep(20)
    else:
        return False, f"{host}: SSL Labs did not finish in 10 min"
    eps = res.get("endpoints", [])
    if res.get("status") != "READY" or not eps:
        return False, f"{host}: SSL Labs {res.get('status')}, {len(eps)} endpoints"
    problems, rows = [], []
    need = P5_REQUIRED_HEADERS["strict-transport-security"]
    for e in eps:
        ip, g = e.get("ipAddress"), e.get("grade")
        code = (e.get("details") or {}).get("httpStatusCode")
        if g not in P5_SSL_OK_GRADES or e.get("hasWarnings"):
            problems.append(f"{ip}: grade {g}, warnings {e.get('hasWarnings')}")
        hsts = _p5_hsts_at(ip, host).lower().replace(" ", "")
        problems += [f"{ip}: HSTS lacks {p}" for p in need if p not in hsts]
        rows.append(f"{ip} {g} (probe HTTP {code}), HSTS read directly")
    return not problems, f"{host}: " + "; ".join(problems or rows)


def p5_strict(expr: str) -> Callable[[], tuple[bool, str]]:
    return pytest_selects(expr, path="tests/phase5", strict=True)


# ---------- phase 6: public repo and READMEs ----------

# Human decisions 2026-11-08 (first three) and 2026-11-11 (the other five, the repo name).
P6_PUBLIC_REPO = "aryan0805/q-day-radar"
P6_REMOVED = [".claude", "docs", "CLAUDE.md", ".coord", "setup/claude", "scripts/coord.py",
              "scripts/team.sh", "scripts/install-claude-config.sh"]
# Commit author e-mail in the public history (human, 2026-11-11): every author and committer
# address is rewritten to the account's own GitHub noreply address, read from `gh api user`.
P6_NOREPLY_ONLY: bool | None = True
P6_READMES = ["README.md", "quantum/README.md", "web/README.md", "tests/README.md",
              "results/README.md", "scripts/README.md", "benchmarks/README.md"]
# A kept file that names a removed file is a dead pointer in the public repo.
P6_REF_PATTERN = (r"(?<![\w.])\.coord\b|(?<![\w./-])docs/|\bCLAUDE\.md\b|(?<![\w.])\.claude\b"
                  r"|\bcoord\.py\b|\bteam\.sh\b|install-claude-config|setup/claude"
                  r"|\b(?:STATE|PLAN|DECISIONS|WORKFLOW|TWEAKS|PHASE5-DESIGN)\.md\b|\bDECISIONS\b")
# Allowed to name them: the list of removed paths itself and the tests of it. results/ is
# immutable (raw files are never edited); its README is checked like any other file.
P6_REF_ALLOWED = [".gitignore", "scripts/gate.py", "scripts/make_public.py",
                  "tests/phase6/test_public_*.py", "tests/phase6/test_norefs*.py"]
P6_BANNED = r"hackathon|submission|advanced track|judg(?:e|es|ed|ing)\b"
P6_HOW_BUILT = "How this was built"
_P6: dict = {}


def _p6_git(*args: str, cwd: Path = ROOT) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
    return r.stdout


def _p6_removed(path: str) -> bool:
    return any(path == r or path.startswith(r + "/") for r in P6_REMOVED)


def _p6_kept_files() -> list[str]:
    return [p for p in _p6_git("ls-files").splitlines() if not _p6_removed(p)]


def p6_no_refs_to_removed() -> tuple[bool, str]:
    import fnmatch
    import re

    pat, hits = re.compile(P6_REF_PATTERN), []
    for rel in _p6_kept_files():
        if any(fnmatch.fnmatch(rel, g) for g in P6_REF_ALLOWED) or rel.endswith(".lock") \
                or rel.endswith("package-lock.json") or (rel.startswith("results/")
                                                         and rel != "results/README.md"):
            continue
        try:
            text = (ROOT / rel).read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if m := pat.search(line):
                hits.append(f"{rel}:{i} ({m.group(0)})")
    return not hits, f"{len(hits)} references: " + "; ".join(hits[:8]) if hits else \
        "no kept file names a removed path"


def p6_make_public_list() -> tuple[bool, str]:
    """The publish script removes exactly the decided paths (gate's own list, not the script's)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_public", ROOT / "scripts/make_public.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    got = sorted(getattr(mod, "REMOVED_PATHS", []))
    return got == sorted(P6_REMOVED), f"make_public.REMOVED_PATHS {got} vs decided {P6_REMOVED}"


def p6_readmes_exist() -> tuple[bool, str]:
    tracked = set(_p6_git("ls-files").splitlines())
    problems = [f"{r} missing or not tracked" for r in P6_READMES
                if r not in tracked or not (ROOT / r).read_text().strip()]
    root = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
    if not any(ln.startswith("#") and P6_HOW_BUILT.lower() in ln.lower()
               for ln in root.splitlines()):
        problems.append(f"README.md has no '{P6_HOW_BUILT}' heading")
    if _p5_sites()["production"].rstrip("/") not in root:
        problems.append("README.md does not link the production site")
    return not problems, "; ".join(problems) or f"{len(P6_READMES)} READMEs, how-built, live link"


def _p6_readme_lines(text: str):
    """(line number, text) outside fenced code and generated blocks, link targets removed."""
    import re

    fence, gen = False, None
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if m := re.search(r"<!--\s*gen:([\w.-]+)\s*-->", line):
            gen = m.group(1)
        if gen:
            if re.search(rf"<!--\s*/gen:{re.escape(gen)}\s*-->", line):
                gen = None
            continue
        if not fence:
            yield i, re.sub(r"\]\([^)]*\)|<https?://[^>]*>|https?://\S+", "]", line)


def p6_readme_figures() -> tuple[bool, str]:
    """Every figure in a README is inside a generated block, or on a line marked
    <!-- literal: reason --> (listed for lead to read)."""
    import re

    bad, literal = [], []
    for rel in P6_READMES:
        f = ROOT / rel
        if not f.exists():
            continue
        for i, line in _p6_readme_lines(f.read_text()):
            m = re.search(r"<!--\s*literal:\s*(.+?)\s*-->", line)
            figs = _p5_figures(re.sub(r"<!--.*?-->", " ", line))
            if figs and m:
                literal.append(f"{rel}:{i} {figs[:3]} ({m.group(1)})")
            elif figs:
                bad.append(f"{rel}:{i} {figs[:3]}")
    detail = (f"{len(bad)} untraced: " + "; ".join(bad[:6]) + " · ") if bad else ""
    return not bad, detail + f"{len(literal)} literal lines: " + "; ".join(literal)


def _p6_slug(heading: str) -> str:
    import re

    h = re.sub(r"[^\w\- ]", "", heading.strip().lstrip("#").strip().lower())
    return h.replace(" ", "-")


def p6_readme_links() -> tuple[bool, str]:
    """Relative links point at a kept tracked file or folder (and an existing heading anchor);
    external links answer below 400. 401/403/429 count as reachable (bot walls) and are listed."""
    import re
    import urllib.error
    import urllib.request

    kept = _p6_kept_files()
    dirs = {str(Path(p).parent) for p in kept} | {
        str(q) for p in kept for q in Path(p).parents}
    bad, walled, n = [], [], 0
    for rel in P6_READMES:
        f = ROOT / rel
        if not f.exists():
            continue
        text = f.read_text()
        anchors = {_p6_slug(ln) for ln in text.splitlines() if ln.startswith("#")}
        for target in re.findall(r"\]\(([^)\s]+)", text) + re.findall(r"<(https?://[^>]+)>", text):
            n += 1
            if target.startswith(("http://", "https://")):
                try:
                    req = urllib.request.Request(target, headers={"User-Agent": "qday-gate"})
                    urllib.request.urlopen(req, timeout=30)
                except urllib.error.HTTPError as e:
                    (walled if e.code in (401, 403, 429) else bad).append(f"{target} {e.code}")
                except Exception as e:  # noqa: BLE001
                    bad.append(f"{target} {type(e).__name__}")
                continue
            if target.startswith("mailto:"):
                bad.append(f"{rel}: mailto link {target}")
                continue
            path, _, anchor = target.partition("#")
            if path:
                dest = (f.parent / path).resolve().relative_to(ROOT).as_posix()
                if _p6_removed(dest) or (dest not in kept and dest not in dirs):
                    bad.append(f"{rel} -> {target}")
                    continue
                if anchor and dest.endswith(".md"):
                    other = (ROOT / dest).read_text().splitlines()
                    if anchor not in {_p6_slug(ln) for ln in other if ln.startswith("#")}:
                        bad.append(f"{rel} -> {target} (no such heading)")
            elif anchor and anchor not in anchors:
                bad.append(f"{rel} -> #{anchor} (no such heading)")
    detail = f"{n} links, {len(bad)} broken" + (": " + "; ".join(bad[:6]) if bad else "")
    return not bad, detail + (f"; bot-walled (reachable): {', '.join(walled)}" if walled else "")


def p6_wording() -> tuple[bool, str]:
    """No hackathon, submission or judging language in any README or in the site."""
    import re

    pat, hits = re.compile(P6_BANNED, re.I), []
    files = [ROOT / r for r in P6_READMES] + [
        p for base in (P5_SRC, P5_OUT) if base.exists() for p in base.rglob("*")
        if p.is_file() and p.suffix in {".ts", ".tsx", ".md", ".mdx", ".html", ".txt", ".json"}]
    for f in files:
        if f.exists():
            for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                if m := pat.search(line):
                    hits.append(f"{f.relative_to(ROOT)}:{i} ({m.group(0)})")
    return not hits, "; ".join(hits[:8]) or f"{len(files)} files clean"


# --- the public repo (cloned fresh; nothing here trusts a file the producer wrote) ---


def _p6_clone() -> Path:
    if "dir" not in _P6:
        d = Path(tempfile.mkdtemp(prefix="qday-public-"))
        url = f"https://github.com/{P6_PUBLIC_REPO}.git"
        _p6_git("clone", "--mirror", "-q", url, str(d / "mirror.git"), cwd=d)
        _p6_git("clone", "-q", str(d / "mirror.git"), str(d / "work"), cwd=d)
        _P6["dir"] = d
    return _P6["dir"]


def p6_public_main_sha() -> str:
    return _p6_git("rev-parse", "HEAD", cwd=_p6_clone() / "work").strip()


def p6_public_history() -> tuple[bool, str]:
    """No removed path in any commit of any ref of the public repo."""
    mirror = _p6_clone() / "mirror.git"
    names = set(_p6_git("log", "--all", "--name-only", "--format=", cwd=mirror).split())
    found = sorted({p for p in names if _p6_removed(p)})
    refs = len(_p6_git("for-each-ref", "--format=%(refname)", cwd=mirror).split())
    commits = len(_p6_git("rev-list", "--all", cwd=mirror).split())
    return not found, (f"{len(found)} removed paths in history: {found[:6]}" if found else
                       f"{commits} commits, {refs} refs: no removed path in any of them")


def p6_public_tree() -> tuple[bool, str]:
    """Public main = this repo's HEAD minus the removed paths, blob for blob."""
    def tree(ref: str, cwd: Path) -> dict[str, str]:
        rows = (ln.split("\t", 1) for ln in _p6_git("ls-tree", "-r", ref, cwd=cwd).splitlines())
        return {path: meta for meta, path in rows if not _p6_removed(path)}

    pub, mine = tree("HEAD", _p6_clone() / "work"), tree("HEAD", ROOT)
    diff = sorted(set(pub) ^ set(mine)) + sorted(p for p in set(pub) & set(mine)
                                                if pub[p] != mine[p])
    return not diff, (f"{len(diff)} paths differ: {diff[:6]}" if diff else
                      f"{len(pub)} files identical to this HEAD minus removed paths")


def p6_public_gitleaks() -> tuple[bool, str]:
    r = subprocess.run(["gitleaks", "git", "--redact", "--no-banner", str(_p6_clone() / "work")],
                       capture_output=True, text=True)
    out = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()]
    return r.returncode == 0, " | ".join(out[-2:])


def p6_public_emails() -> tuple[bool, str]:
    if P6_NOREPLY_ONLY is None:
        return False, "human decision pending: keep commit e-mails or rewrite to noreply"
    mails = set(_p6_git("log", "--all", "--format=%ae%n%ce", cwd=_p6_clone() / "mirror.git")
                .split())
    if not P6_NOREPLY_ONLY:
        return True, f"human kept commit e-mails as they are ({len(mails)} distinct)"
    mine = subprocess.run(["gh", "api", "user", "--jq",
                           '"\\(.id)+\\(.login)@users.noreply.github.com"'],
                          capture_output=True, text=True).stdout.strip()
    if not mine.endswith("@users.noreply.github.com"):
        return False, "could not read the account's noreply address with gh api user"
    other = [m for m in mails if m not in (mine, "noreply@github.com")]  # web merges: GitHub
    return not other, (f"{len(other)} author/committer addresses other than the account's "
                       "noreply" if other else
                       f"{len(mails)} distinct addresses, all the account's noreply (or GitHub)")


def _p6_clean_env() -> dict:
    drop = {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "QDAY_WEB_ROOT", "PYTHONPATH"}
    return {k: v for k, v in os.environ.items() if k not in drop}


def _p6_run(argv: list[str], cwd: Path) -> tuple[bool, str]:
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=_p6_clean_env())
    out = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()]
    return r.returncode == 0, f"{' '.join(argv[:4])}: " + " | ".join(out[-2:])


def p6_public_web_build() -> tuple[bool, str]:
    work = _p6_clone() / "work"
    for argv in (["npm", "--prefix", "web", "ci", "--no-audit", "--no-fund"],
                 ["npm", "--prefix", "web", "run", "build"]):
        ok, detail = _p6_run(argv, work)
        if not ok:
            return False, detail
    return True, "clean clone: npm ci && npm run build exit 0"


def p6_public_tests() -> tuple[bool, str]:
    """A clean clone (no .env, no dev-only folders) passes the non-hardware suite."""
    work = _p6_clone() / "work"
    if not (work / "web" / "out").exists():
        ok, detail = p6_public_web_build()
        if not ok:
            return False, detail
    for argv in (["uv", "sync", "--frozen"],
                 ["uv", "run", "python", "-m", "playwright", "install", "chromium"],
                 ["uv", "run", "pytest", "-m", "not hardware", "-q", "-p", "no:cacheprovider"]):
        ok, detail = _p6_run(argv, work)
        if not ok:
            return False, detail
    return True, detail


def p6_strict(expr: str) -> Callable[[], tuple[bool, str]]:
    return pytest_selects(expr, path="tests/phase6", strict=True)


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
        Py(
            ".env is git-ignored",
            lambda: (".env" in (ROOT / ".gitignore").read_text().split(), ".gitignore checked"),
        ),
    ],
    # Lead: at /phase-start N, turn every command-checkable exit criterion
    # in the plan into a check here before BUILD starts.
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
        Cmd(
            "raw hardware files unchanged",
            ["git", "diff", "--quiet", "HEAD", "--", "results/hardware"],
        ),
        Py("approval tests pass (no xfail/skip)", p2_strict("approval")),
        Py("immutable tests pass (no xfail/skip)", p2_strict("immutable")),
        Py("budget tests pass (no xfail/skip)", pytest_selects("budget", strict=True)),
        Py("phase 2 honesty audit written", file_exists("tests/phase2/AUDIT.md")),
    ],
    3: [
        Py("phase 3 tests exist", has_tests(3)),
        Py("qsharp and qualtran import, versions recorded", p3_env),
        Py("every literature number has a URL and is fact-checked", p3_literature_checked),
        Py("QDK: 7 registry circuits + scaling family over >= 3 bases", p3_qdk_complete),
        Py("toffoli_equiv matches its raw counts, one eps", p3_toffoli_equiv_consistent),
        Py("QDK vs Qualtran within 3x or gap explained", p3_crosscheck),
        Py("scaling fits with residuals, holdout, n=2048", p3_scaling),
        Py("calibrated against literature (RSA, ECC, AES)", p3_calibration),
        Py("physical scenarios complete", p3_scenarios),
        Cmd("estimates reproduce", [PY, "scripts/estimate_all.py", "--verify"]),
        Py("no result file over 5 MB (circuits gzipped)", p3_no_large_files),
        Cmd(
            "no QPU used since phase 2",
            [
                "git",
                "diff",
                "--quiet",
                "phase-2-done",
                "--",
                "results/budget.json",
                "results/hardware",
            ],
        ),
        Py("estimate tests pass (no xfail/skip)", p3_strict("estimate")),
        Py("scaling tests pass (no xfail/skip)", p3_strict("scaling")),
        Py("crosscheck tests pass (no xfail/skip)", p3_strict("crosscheck")),
        Py("phase 3 honesty audit written", file_exists("tests/phase3/AUDIT.md")),
    ],
    4: [
        Py("phase 4 tests exist", has_tests(4)),
        Py("every literature number has a URL and is fact-checked", p3_literature_checked),
        Py("demo CBOM: valid CycloneDX 1.6, 35-50 assets, fictional, round-trips", p4_cbom),
        Py("timeline refit, holdout, crqc_year recomputed", p4_timeline),
        Py("margins, ranks, family order recomputed; replacements verified", p4_inventory),
        Py("web data files valid against their schemas, <= 5 MB", p4_web_schemas),
        Py(
            "ECC-256 inputs are the newest verified estimate (Roetteler as history)",
            p4_ecc_inputs_current,
        ),
        Py(
            "v2 recorded truthfully (holdout FAILED, not tuned, not adopted)",
            p4_physical_v2,
        ),
        Py("phase 3 data checks still pass after the ECC rerun", p4_phase3_still_holds),
        Cmd("phase 3 estimates still reproduce", [PY, "scripts/estimate_all.py", "--verify"]),
        Cmd("web data reproduces", [PY, "scripts/build_data.py", "--verify"]),
        Cmd(
            "no QPU used since phase 3",
            [
                "git",
                "diff",
                "--quiet",
                "phase-3-done",
                "--",
                "results/budget.json",
                "results/hardware",
            ],
        ),
        Py("cbom tests pass (no xfail/skip)", p4_strict("cbom")),
        Py("mosca tests pass (no xfail/skip)", p4_strict("mosca")),
        Py("timeline tests pass (no xfail/skip)", p4_strict("timeline")),
        Py("phase 4 honesty audit written", file_exists("tests/phase4/AUDIT.md")),
    ],
    # Labels carry the sub-phase; lead runs the gate at the end of 5a and 5b too and
    # expects that sub-phase's checks (and the earlier ones) to pass.
    5: [
        Py("[5a] phase 5 tests exist", has_tests(5)),
        Py("[5a] web/package-lock.json committed",
           lambda: (bool(subprocess.run(["git", "ls-files", "web/package-lock.json"], cwd=ROOT,
                                        capture_output=True, text=True).stdout.strip()),
                    "git ls-files web/package-lock.json")),
        Cmd("[5a] npm ci", ["npm", "--prefix", "web", "ci", "--no-audit", "--no-fund"]),
        Cmd("[5a] lint (eslint, 0 warnings)", ["npm", "--prefix", "web", "run", "lint"]),
        Cmd("[5a] typecheck", ["npm", "--prefix", "web", "run", "typecheck"]),
        Cmd("[5a] npm run build (static export)", ["npm", "--prefix", "web", "run", "build"]),
        Cmd("[5a] npm audit: no high/critical", ["npm", "--prefix", "web", "audit",
                                                 "--audit-level=high"]),
        Py("[5a] no .env or env reads in web/ (NODE_ENV only)", p5_no_env_in_web),
        Py("[5a] canary scan: no .env value or secret pattern in out/ or data", p5_canary_scan),
        Py("[5a] data files carry no secret-, credential- or path-named key",
           p5_data_keys_allowed),
        Py("[5a] no untracked files under web/ (Vercel builds from git)", p5_web_tracked),
        Py("[5a] no source maps in out/", p5_no_source_maps),
        Py("[5a] no third-party script, style, font or image", p5_no_third_party),
        Py("[5a] tweak panel in source, absent from out/", p5_tweak_panel_absent),
        Py("[5a] text tokens >= 4.5:1, --sim >= 3:1 on every background", p5_token_contrast),
        Py("[5a] .env never committed", p5_env_never_committed),
        Cmd("[5a] gitleaks: no secret in git history",
            ["gitleaks", "git", "--redact", "--no-banner", "."]),
        Py("[5a] gitleaks pre-commit hook and GitHub Action", p5_hooks_and_ci),
        Py("[5a] GitHub Dependabot on (+ secret scanning, push protection if public)",
           p5_github_secret_scanning),
        Py("[5a] preview needs a Vercel login", p5_preview_protected),
        Py("[5a] preview serves HEAD with required headers and hash CSP", p5_live("preview")),
        Py("[5a] security tests pass (no xfail/skip)", p5_strict("security")),
        Py("[5a] tweak tests pass (no xfail/skip)", p5_strict("tweak")),
        Py("[5b] every figure on a page traces to web/public/data", p5_provenance_static),
        Py("[5b] provenance tests pass (no xfail/skip)", p5_strict("provenance")),
        Py("[5b] scenario tests pass (no xfail/skip)", p5_strict("scenario")),
        Py("[5b] keyboard tests pass (no xfail/skip)", p5_strict("keyboard")),
        Py("[5b] smoke tests pass (no xfail/skip)", p5_strict("smoke")),
        Py("[5b] plain layer: FK grade <= 9, <= 20 words/sentence, technical layer per screen",
           p5_readability),
        Py("[5b] justify tests pass (no xfail/skip)", p5_strict("justify")),
        Py("[5b] glossary tests pass (no xfail/skip)", p5_strict("glossary")),
        Py("[5c] scripts named by index.html <= 200,000 B gzipped", p5_home_js_budget),
        Py("[5c] bundle tests pass: JS fetched before first interaction <= 200,000 B gz",
           p5_strict("bundle")),
        Py("[5c] reducedmotion tests pass (no xfail/skip)", p5_strict("reducedmotion")),
        Py("[5c] longtask tests pass (no xfail/skip)", p5_strict("longtask")),
        Py("[5c] easteregg tests pass (no xfail/skip)", p5_strict("easteregg")),
        Py("[5c] motionscale tests pass (no xfail/skip)", p5_strict("motionscale")),
        Py("[5d] Lighthouse mobile: perf >= 0.90, a11y = 1.00, LCP < 2 s, CLS < 0.05",
           p5_lighthouse),
        Py("[5d] web data files valid against their schemas, <= 5 MB", p4_web_schemas),
        Py("[5d] margins, ranks, family order still recomputed from data", p4_inventory),
        Cmd("[5d] web data reproduces", [PY, "scripts/build_data.py", "--verify"]),
        Cmd("[5d] no QPU used since phase 4",
            ["git", "diff", "--quiet", "phase-4-done", "--", "results/budget.json",
             "results/hardware"]),
        Py("[5d] phase 5 honesty audit written", file_exists("tests/phase5/AUDIT.md")),
        # run after the merge to main has deployed to production:
        Py("[live] production serves HEAD with required headers and hash CSP",
           p5_live("production")),
        Py("[live] Mozilla HTTP Observatory grade A+", p5_observatory),
        Py("[live] SSL Labs A or A+ on every endpoint, no warnings; HSTS read on each", p5_ssllabs),
    ],
    # 6a runs in this repo on phase-6 / main; 6b clones the public repo fresh; [live] last.
    6: [
        Py("[6a] phase 6 tests exist", has_tests(6)),
        Py("[6a] no kept file names a removed path (dead pointers in the public repo)",
           p6_no_refs_to_removed),
        Py("[6a] make_public removes exactly the decided paths", p6_make_public_list),
        Py("[6a] READMEs: root + 6 folders, 'How this was built', live link", p6_readmes_exist),
        Cmd("[6a] README numbers regenerate byte-exact from data",
            [PY, "scripts/build_readme.py", "--verify"]),
        Py("[6a] every README figure is generated or marked literal (list read by lead)",
           p6_readme_figures),
        Py("[6a] every README link resolves (relative, anchors, external)", p6_readme_links),
        Py("[6a] no hackathon, submission or judging wording in READMEs or the site",
           p6_wording),
        Cmd("[6a] npm audit: no high/critical", ["npm", "--prefix", "web", "audit",
                                                 "--audit-level=high"]),
        Py("[6a] .env never committed", p5_env_never_committed),
        Cmd("[6a] gitleaks: no secret in git history",
            ["gitleaks", "git", "--redact", "--no-banner", "."]),
        Cmd("[6a] no QPU used since phase 5",
            ["git", "diff", "--quiet", "phase-5-done", "--", "results/budget.json",
             "results/hardware"]),
        Py("[6a] readme tests pass (no xfail/skip)", p6_strict("readme")),
        Py("[6a] links tests pass (no xfail/skip)", p6_strict("links")),
        Py("[6a] wording tests pass (no xfail/skip)", p6_strict("wording")),
        Py("[6a] norefs tests pass (no xfail/skip)", p6_strict("norefs")),
        Py("[6a] public (make_public on a scratch repo) tests pass (no xfail/skip)",
           p6_strict("public")),
        Py("[6b] public repo: no removed path in any commit of any ref", p6_public_history),
        Py("[6b] public main = this HEAD minus removed paths, blob for blob", p6_public_tree),
        Py("[6b] public repo: gitleaks history scan clean", p6_public_gitleaks),
        Py("[6b] public repo: commit e-mails per the human's decision", p6_public_emails),
        Py("[6b] public repo: public, secret scanning, push protection, Dependabot",
           lambda: p5_github_secret_scanning(P6_PUBLIC_REPO, need_public=True)),
        Py("[6b] clean clone: npm ci && npm run build", p6_public_web_build),
        Py("[6b] clean clone: uv sync && pytest -m 'not hardware'", p6_public_tests),
        # after Vercel builds production from the public repo's main:
        Py("[live] production serves public main with required headers and hash CSP",
           p5_live("production", expected=p6_public_main_sha)),
        Py("[live] Mozilla HTTP Observatory grade A+", p5_observatory),
        Py("[live] SSL Labs A or A+ on every endpoint, no warnings; HSTS read on each", p5_ssllabs),
    ],
}

# Run before the regression checks (the full suite reads web/out, so build it fresh first).
PHASE_PRE: dict[int, list[Check]] = {
    6: [
        Cmd("npm ci", ["npm", "--prefix", "web", "ci", "--no-audit", "--no-fund"]),
        Cmd("npm run build (fresh web/out for the suite)", ["npm", "--prefix", "web", "run",
                                                            "build"]),
    ],
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
    if len(sys.argv) not in (2, 3) or not sys.argv[1].isdigit():
        print("usage: uv run python scripts/gate.py <phase> [<sub-phase, e.g. 5a>]")
        return 2
    phase = int(sys.argv[1])
    if phase not in PHASE_CHECKS:
        print(f"no checks defined for phase {phase}")
        return 2

    checks = PHASE_PRE.get(phase, []) + REGRESSION + PHASE_CHECKS[phase]
    upto = sys.argv[2] if len(sys.argv) == 3 else None
    if upto:  # a sub-phase checkpoint: its checks and every earlier sub-phase's, never [live].
        # Checkpoints run only this phase's tests; the final gate runs the full suite.
        checks = PHASE_PRE.get(phase, []) + [
            REGRESSION[0],
            Py(f"phase {phase} tests only (checkpoint; full suite at the final gate)",
               lambda: full_suite([f"tests/phase{phase}"])),
        ] + [
            c for c in PHASE_CHECKS[phase]
            if c.label.startswith("[") and c.label[1:].split("]")[0] <= upto
            and not c.label.startswith("[live]")
        ]
    rows = []
    for c in checks:
        ok, detail, secs = run(c)
        rows.append((c.label, ok, detail, secs))
        print(f"{'PASS' if ok else 'FAIL'}  {c.label}  ({secs:.1f}s)  {detail}")

    passed = all(ok for _, ok, _, _ in rows)
    verdict = "PASSED" if passed else "FAILED"
    print(f"\nGate {phase}: {verdict} ({sum(ok for _, ok, _, _ in rows)}/{len(rows)} checks)")

    reports = ROOT / ".coord" / "gates"
    if not reports.parent.is_dir():  # public repo: no .coord/, so the report goes to temp
        reports = Path(tempfile.gettempdir()) / "qday-gate"
    out = reports / f"phase-{phase}{'-' + upto if upto else ''}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Gate report — phase {phase}" + (f" (checkpoint {upto})" if upto else ""),
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
        retro = prev[prev.index("## Retro") :]  # keep a retro already written
    lines += ["", retro]
    out.write_text("\n".join(lines))
    print(f"report: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
