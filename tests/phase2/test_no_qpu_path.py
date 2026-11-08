"""No QPU path outside scripts/submit_hardware.py (names contain `budget`: the gate runs them).

Lead's rule: M3 calibration goes through the same `service.submit`, and nothing calls
`backend.run`. The unit tests prove the submit script never does; these source checks prove no
other module can reach the device or build a real service.
"""

import ast
import importlib
import os
from pathlib import Path

import pytest

from tests.phase2.guards import ROOT

SOURCES = sorted(
    p
    for d in ("quantum", "scripts")
    for p in (ROOT / d).rglob("*.py")
    if "__pycache__" not in p.parts
)
# only the real-service adapter may build the runtime service, sampler, batch or run M3 calibration
ADAPTER = ROOT / "quantum" / "run" / "hardware.py"
ALLOWED_SERVICE = {ADAPTER, ROOT / "quantum" / "backends.py"}  # backends.get_real_backend (Phase 0)
FORBIDDEN_CALLS = {"QiskitRuntimeService", "SamplerV2", "Sampler", "Batch", "Session", "IBMBackend"}
M3_DEVICE_CALIBRATION = {"cals_from_system", "cals_from_backend"}


def _calls(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                yield f.id, node.lineno
            elif isinstance(f, ast.Attribute):
                yield f.attr, node.lineno


def test_budget_no_module_builds_a_runtime_service_or_sampler_outside_the_adapter():
    offenders = [
        f"{p.relative_to(ROOT)}:{line} {name}"
        for p in SOURCES
        if p not in ALLOWED_SERVICE
        for name, line in _calls(p)
        if name in FORBIDDEN_CALLS
    ]
    assert not offenders, offenders


def test_budget_m3_calibration_never_runs_circuits_on_the_device_itself():
    # mthree.M3.cals_from_system() submits its own calibration jobs: that would bypass the budget
    offenders = [
        f"{p.relative_to(ROOT)}:{line} {name}"
        for p in SOURCES
        for name, line in _calls(p)
        if name in M3_DEVICE_CALIBRATION
    ]
    assert not offenders, offenders


def test_budget_nothing_calls_run_on_a_backend_or_device_object():
    offenders = []
    for p in SOURCES:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
            ):
                recv = ast.unparse(node.func.value).lower()
                if any(w in recv for w in ("backend", "device", "real", "service")):
                    where = f"{p.relative_to(ROOT)}:{node.lineno}"
                    offenders.append(f"{where} {ast.unparse(node.func)}")
    # simulators are named sim/ideal/noisy; pass-manager `.run(` receivers are fine
    offenders = [o for o in offenders if "pm" not in o.split()[-1].split(".")[0]]
    assert not offenders, offenders


def test_budget_the_default_service_factory_is_used_only_by_submit_and_plan():
    users = {
        p.relative_to(ROOT).as_posix()
        for p in SOURCES
        if p != ADAPTER and "default_service_factory" in p.read_text()
    }
    # plan_hardware may fetch a real backend to read its properties (no job, no QPU time)
    assert users <= {"scripts/submit_hardware.py", "scripts/plan_hardware.py"}, users


def test_budget_plan_script_only_fetches_a_backend_and_never_submits():
    path = ROOT / "scripts" / "plan_hardware.py"
    if not path.exists():
        pytest.skip("plan_hardware.py not written yet")
    tree = ast.parse(path.read_text())
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"submit", "job", "cancel", "usage"}, attrs & {"submit", "job", "cancel"}
    assert "record_job" not in path.read_text() and "check_job" not in path.read_text()


@pytest.mark.parametrize(
    "module",
    [
        "quantum.run.hardware",
        "scripts.plan_hardware",
        "scripts.submit_hardware",
        "scripts.analyze_hardware",
    ],
)
def test_budget_import_has_no_service_network_or_env_side_effects(module):
    pytest.importorskip(module)
    before = dict(os.environ)
    mod = importlib.import_module(module)
    importlib.reload(mod)  # the autouse guards raise if import builds a service or connects
    assert os.environ.get("QISKIT_IBM_TOKEN") is None, "importing must not load .env"
    assert {k for k in os.environ if k.startswith("QISKIT_IBM")} == {
        k for k in before if k.startswith("QISKIT_IBM")
    }
