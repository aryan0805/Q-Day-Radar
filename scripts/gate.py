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


def full_suite() -> tuple[bool, str]:
    """Run the non-hardware suite once, with a JUnit report the keyword checks reuse."""
    xml = Path(tempfile.gettempdir()) / f"qday-gate-{os.getpid()}.xml"
    r = subprocess.run(
        [PY, "-m", "pytest", "-m", "not hardware", "-p", "no:cacheprovider", f"--junitxml={xml}"],
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
        retro = prev[prev.index("## Retro") :]  # keep a retro already written
    lines += ["", retro]
    out.write_text("\n".join(lines))
    print(f"report: {out.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
