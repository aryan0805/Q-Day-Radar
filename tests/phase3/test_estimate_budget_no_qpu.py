"""Phase 3 uses no QPU: checks on IMPORTS, CONSTRUCTED TYPES and RUNTIME behaviour.

The name-based guard in tests/phase2/test_no_qpu_path.py (receiver text contains 'backend') stays.
A rename can dodge a name check, so these look at what the code imports and builds, and then run
the estimators with every IBM entry point booby-trapped. Test names contain `budget`.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import textwrap

from tests.phase3 import reference as ref

ROOT = ref.ROOT
SOURCES = sorted(
    p
    for d in ("quantum", "scripts")
    for p in (ROOT / d).rglob("*.py")
    if "__pycache__" not in p.parts
)
# only these modules may touch IBM runtime (Phase 0 backends, Phase 2 adapter, submit script)
IBM_ADAPTERS = {"quantum/backends.py", "quantum/run/hardware.py", "scripts/submit_hardware.py"}
ESTIMATE_SOURCES = [
    p
    for p in SOURCES
    if p.relative_to(ROOT).as_posix().startswith(("quantum/estimate/", "scripts/estimate_"))
]
IBM_ROOTS = ("qiskit_ibm_runtime", "qiskit_ibm_provider")
DEVICE_NAMES = {
    "get_real_backend",
    "default_service_factory",
    "QiskitRuntimeService",
    "IBMBackend",
    "record_job",
    "check_job",
}


def _rel(p) -> str:
    return p.relative_to(ROOT).as_posix()


def _imports(path):
    """(module, line) for every import, including `from x import y` as x.y."""
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, node.lineno
            for a in node.names:
                yield f"{node.module}.{a.name}", node.lineno


BAD_CONSTRUCT = re.compile(
    r"(Backend|Service|Sampler|SamplerV2|EstimatorV2|Session|Batch|AerSimulator)$|^Fake|"
    r"^get_\w*(backend|service)\w*$"
)


def ibm_violations(src: str) -> list[str]:
    """IBM runtime imports, dynamic imports or package-name strings in `src`."""
    out = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module]
        out += [f"line {node.lineno} imports {m}" for m in mods if m.split(".")[0] in IBM_ROOTS]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(r in node.value for r in IBM_ROOTS):
                out.append(f"line {node.lineno} mentions {node.value[:40]!r}")
    return out


def ledger_or_device_imports(src: str) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(src)):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        for m in mods:
            if m.startswith(("quantum.run.hardware", "quantum.budget")) or (
                m.split(".")[-1] in DEVICE_NAMES
            ):
                out.append(f"line {node.lineno} imports {m}")
    return out


def non_local_constructions(src: str) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            f = node.func
            name = (
                f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            )
            if BAD_CONSTRUCT.search(name) and name != "ResourceEstimatorBackend":
                out.append(f"line {node.lineno} constructs {name}")
    return out


def test_estimate_budget_ibm_runtime_is_imported_only_by_the_allowed_adapters():
    offenders = [
        f"{_rel(p)}: {v}"
        for p in SOURCES
        if _rel(p) not in IBM_ADAPTERS
        for v in ibm_violations(p.read_text())
    ]
    assert not offenders, offenders


def test_estimate_budget_the_estimate_code_imports_nothing_that_reaches_a_device_or_the_ledger():
    assert ESTIMATE_SOURCES, "no estimate sources found"
    offenders = [
        f"{_rel(p)}: {v}" for p in ESTIMATE_SOURCES for v in ledger_or_device_imports(p.read_text())
    ]
    assert not offenders, offenders


def test_estimate_budget_estimate_code_constructs_no_backend_but_the_local_resource_estimator():
    offenders = [
        f"{_rel(p)}: {v}" for p in ESTIMATE_SOURCES for v in non_local_constructions(p.read_text())
    ]
    assert not offenders, offenders


def test_estimate_budget_the_scanners_catch_a_renamed_device_and_other_known_bad_code():
    """Teeth: the same scanners applied to code that should be flagged."""
    renamed = "from quantum.backends import get_real_backend\nestimator = get_real_backend()\n"
    assert ledger_or_device_imports(renamed) and non_local_constructions(renamed)
    assert ibm_violations("from qiskit_ibm_runtime import QiskitRuntimeService")
    assert ibm_violations("import importlib\nimportlib.import_module('qiskit_ibm_runtime')")
    assert non_local_constructions("svc = QiskitRuntimeService()")
    assert non_local_constructions("b = AerSimulator.from_backend(x)\ns = SamplerV2(mode=b)")
    assert ledger_or_device_imports("from quantum.budget import record_job")
    clean = (
        "from qsharp.interop.qiskit import ResourceEstimatorBackend\n"
        "estimator = ResourceEstimatorBackend()"
    )
    assert not (
        ibm_violations(clean) or ledger_or_device_imports(clean) or non_local_constructions(clean)
    )


def test_estimate_budget_the_local_estimator_really_is_qsharps_not_a_device():
    """ResourceEstimatorBackend must resolve to the qsharp/qdk package, not an IBM class."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from qsharp.interop.qiskit import ResourceEstimatorBackend
    module = ResourceEstimatorBackend.__module__
    assert module.split(".")[0] in {"qsharp", "qdk"}, module
    assert not any(
        c.__module__.split(".")[0] in IBM_ROOTS for c in ResourceEstimatorBackend.__mro__
    )


_TRAP = textwrap.dedent(
    """
    import sys, warnings
    warnings.filterwarnings("ignore")
    import qiskit_ibm_runtime as ibm

    def boom(*a, **k):
        raise AssertionError("QPU PATH: an IBM entry point was called")

    for cls_name in ("QiskitRuntimeService", "Session", "Batch", "SamplerV2", "EstimatorV2"):
        getattr(ibm, cls_name).__init__ = boom
    ibm.IBMBackend.run = boom

    # positive control: the trap bites
    try:
        ibm.QiskitRuntimeService()
    except AssertionError:
        pass
    else:
        raise SystemExit("trap did not fire")

    from qiskit import QuantumCircuit, qasm2
    from quantum.estimate import common, physical, qdk, qualtran_est, scaling

    qc = QuantumCircuit(5)
    qc.ccx(0, 1, 2); qc.t(3); qc.rz(0.3, 3); qc.mcx([0, 1, 2], 3)
    form = common.estimation_form(qc)
    counts = qdk.qdk_logical_counts(form)
    qualtran_est.qualtran_counts_from_qasm(qasm2.dumps(form))
    qualtran_est.qualtran_modexp_counts(15, 7)
    physical.physical_estimate(
        {"numQubits": 10, "cczCount": 1000, "tCount": 0, "rotationCount": 0,
         "ccixCount": 0, "measurementCount": 1000},
        {"physical_error_rate": 1e-3, "cycle_time_seconds": 1e-6,
         "qec_scheme": "surface_code", "error_budget": 0.01})
    scaling.fit_power_law([4, 5, 6, 7, 8], [10, 30, 70, 150, 250])
    print("OK", counts["ccz_count"])
    """
)


def test_estimate_budget_estimators_run_with_every_ibm_entry_point_booby_trapped():
    r = subprocess.run(
        [sys.executable, "-c", _TRAP],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert r.returncode == 0 and "OK" in r.stdout, (r.stdout[-300:], r.stderr[-600:])


def test_estimate_budget_importing_the_estimate_modules_never_loads_the_ibm_runtime():
    code = (
        "import sys, warnings; warnings.filterwarnings('ignore');"
        "import quantum.estimate.common, quantum.estimate.qdk, quantum.estimate.qualtran_est,"
        "quantum.estimate.scaling, quantum.estimate.physical;"
        "bad=[m for m in sys.modules if m.split('.')[0] in "
        f"{IBM_ROOTS!r}];"
        "print('LOADED', bad)"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert r.returncode == 0 and "LOADED []" in r.stdout, (r.stdout[-300:], r.stderr[-400:])


def test_estimate_budget_results_and_ledger_are_untouched_by_phase_3():
    for path in ("results/hardware", "results/budget.json"):
        r = subprocess.run(
            ["git", "diff", "--quiet", "phase-2-done", "--", path], cwd=ROOT, check=False
        )
        assert r.returncode == 0, f"{path} changed since phase-2-done"
    untracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "results/hardware",
            "results/budget.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert not untracked, f"new files under the QPU ledger paths: {untracked}"


def test_estimate_budget_the_ai_transpiler_is_imported_only_by_transpile_compare_in_local_mode():
    """qiskit_ibm_transpiler can call IBM's cloud service; the Open Plan allows local mode only."""
    users = {}
    for p in SOURCES:
        if any(m.split(".")[0] == "qiskit_ibm_transpiler" for m, _ in _imports(p)):
            users[_rel(p)] = p
    assert set(users) <= {"scripts/transpile_compare.py"}, sorted(users)
    for rel, p in users.items():
        calls = [
            n
            for n in ast.walk(ast.parse(p.read_text()))
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", "")) == "generate_ai_pass_manager"
        ]
        assert calls, f"{rel}: imports the AI transpiler but never calls generate_ai_pass_manager"
        for c in calls:
            kw = {k.arg: k.value for k in c.keywords}
            assert (
                isinstance(kw.get("local_mode"), ast.Constant) and kw["local_mode"].value is True
            ), f"{rel}:{c.lineno} must pass local_mode=True"
