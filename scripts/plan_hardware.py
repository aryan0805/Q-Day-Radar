"""Build the hardware plan: transpile, estimate QPU seconds, pre-register predictions. No QPU.

Writes ``results/hardware/<batch_id>/plan.json`` plus ``circuits/<index>.qpy`` (the exact ISA
circuit; ``isa_sha256`` is the sha256 of those bytes). May read backend properties; never
creates a job. Each job's prediction is a noisy simulation of the IDENTICAL ISA circuit on
``AerSimulator.from_backend(<device>)``, so it is on file before anyone approves the batch.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qiskit import QuantumCircuit, qasm3  # noqa: E402
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager  # noqa: E402
from qiskit_aer import AerSimulator  # noqa: E402

from quantum.run.hardware import (  # noqa: E402
    DEFAULT_SHOTS,
    NUM_RANDOMIZATIONS,
    TWIRLED_CONFIGS,
    count_mid_circuit,
    estimate_seconds,
    m3_calibration_circuit,
    measured_qubits,
    qpy_bytes,
    sha256_hex,
    shots_per_randomization,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_ROOT = ROOT / "results" / "hardware"
NOISY_DIR = ROOT / "results" / "noisy"
STATIC_CONFIGS = ("raw", "dd", "dd_twirl")
MAX_TOTAL_SECONDS = 300.0
# Human decision (DECISIONS.md): N=21 stays off the hardware batch whatever its noisy result is.
DEFAULT_EXCLUDE = {
    "shor21_beauregard": "human decision: N=21 stays off the hardware batch "
    "(excluded explicitly, not by the signal rule)"
}


def _two_qubit_count(isa: QuantumCircuit) -> int:
    return isa.num_nonlocal_gates()


def _predict(isa: QuantumCircuit, backend: Any, shots: int, seed: int) -> Any:
    sim = AerSimulator.from_backend(backend, shot_branching_enable=True)
    return sim.run(isa, shots=shots, seed_simulator=seed).result().get_counts()


def build_plan(
    circuits: dict[str, QuantumCircuit],
    backend: Any,
    *,
    shots: int = DEFAULT_SHOTS,
    out_root: Path = DEFAULT_OUT_ROOT,
    batch_id: str | None = None,
    now: Callable[[], datetime] | None = None,
    configs: tuple[str, ...] = STATIC_CONFIGS,
    noisy_dir: Path = NOISY_DIR,
    control_names: tuple[str, ...] = ("shor15_beauregard",),
    repeats: int = 2,
    max_total_seconds: float = MAX_TOTAL_SECONDS,
    seed_transpiler: int = 1234,
    seed_simulator: int = 1234,
    backend_choice_reason: str = "",
    exclude: dict[str, str] | None = None,
    first_pilot: str | None = None,
) -> Path:
    """Write the plan for one batch and return the batch directory."""
    from quantum.circuits.registry import SUCCESS_FN

    created = (now or (lambda: datetime.now(UTC)))()
    batch_id = batch_id or created.strftime("batch-%Y%m%dT%H%M%SZ")
    pm = generate_preset_pass_manager(
        optimization_level=3, backend=backend, seed_transpiler=seed_transpiler
    )

    # 1. choose circuits by the noisy-sim signal rule
    exclude = DEFAULT_EXCLUDE if exclude is None else exclude
    circuits = {n: c for n, c in circuits.items() if n not in exclude}
    isa_by_name: dict[str, QuantumCircuit] = {}
    static: list[str] = []
    controls: list[str] = []
    dynamic_raw: list[str] = []
    for name, circuit in circuits.items():
        noisy_file = noisy_dir / f"{name}.json"
        if not noisy_file.exists():  # the signal rule must not be bypassable by a missing file
            raise FileNotFoundError(f"{noisy_file}: run scripts/run_noisy.py first")
        signal = json.loads(noisy_file.read_text())["signal"]
        isa = pm.run(circuit)
        isa_by_name[name] = isa
        if count_mid_circuit(isa) > 0:  # dynamic: no DD / twirling, raw options only
            if signal:
                dynamic_raw.append(name)  # unexpected signal: a normal raw job
            elif name in control_names and len(controls) < 2:
                controls.append(name)  # no signal expected: a control run
        elif signal:
            static.append(name)
    static.sort(key=lambda n: (_two_qubit_count(isa_by_name[n]), n))
    if not static:
        raise ValueError("no static circuit with signal: nothing to plan")

    # 2. job list: pilots first (smallest circuit under each config, then m3_cal zeros)
    qubits = sorted({q for n in static for q in measured_qubits(isa_by_name[n])})
    n_dev = backend.num_qubits
    cal = {
        "m3_cal_zeros": m3_calibration_circuit(n_dev, qubits, ones=False),
        "m3_cal_ones": m3_calibration_circuit(n_dev, qubits, ones=True),
    }
    # identity layout: the calibration must measure exactly the qubits the experiments measure
    pm_cal = generate_preset_pass_manager(
        optimization_level=0, backend=backend, initial_layout=list(range(n_dev))
    )
    cal_isa = {k: pm_cal.run(v) for k, v in cal.items()}
    for k, v in cal_isa.items():
        if measured_qubits(v) != qubits:
            raise ValueError(f"{k} measures {measured_qubits(v)}, expected {qubits}")
    specs: list[tuple[str, str, QuantumCircuit, bool]] = []
    smallest = static[0]
    for cfg in configs:
        specs.append((smallest, cfg, isa_by_name[smallest], True))
    specs.append(("m3_cal_zeros", "m3_cal", cal_isa["m3_cal_zeros"], True))
    for rep in range(
        repeats
    ):  # repeats give a run-to-run spread (same circuit; each saved file has its own hash)
        for name in static:
            for cfg in configs:
                if not (name == smallest and rep == 0):
                    specs.append((name, cfg, isa_by_name[name], False))
    for name in dynamic_raw:
        specs.append((name, "raw", isa_by_name[name], False))
    for name in controls:
        specs.append((name, "control", isa_by_name[name], False))
    specs.append(("m3_cal_ones", "m3_cal", cal_isa["m3_cal_ones"], False))

    if first_pilot:  # human choice: this circuit's raw job is submitted first, as a pilot
        hit = next(
            (
                i
                for i, (n, cfg, _, _) in enumerate(specs)
                if n == first_pilot and cfg in ("raw", "control")
            ),
            None,
        )
        if hit is None:
            raise ValueError(f"first_pilot {first_pilot!r} has no raw job in this plan")
        if specs[hit][1] == "control":
            raise ValueError(
                f"first_pilot {first_pilot!r} is planned as a control job; "
                "a control keeps its label and cannot become a pilot"
            )
        name_, cfg_, isa_, _ = specs.pop(hit)
        specs.insert(0, (name_, "raw", isa_, True))

    # 3. estimate, pre-register predictions, write files
    batch_dir = out_root / batch_id
    qpy_files: dict[int, bytes] = {}
    jobs: list[dict[str, Any]] = []
    predicted: dict[str, Any] = {}
    estimates = [
        estimate_seconds(isa, shots, target=backend.target, config=cfg) for _, cfg, isa, _ in specs
    ]
    if round(sum(estimates), 1) > max_total_seconds:
        raise ValueError(
            f"total estimate {round(sum(estimates), 1)} s exceeds {max_total_seconds} s"
        )
    for index, (name, cfg, isa, pilot) in enumerate(specs):
        data = qpy_bytes(isa)
        qpy_files[index] = data
        if name not in predicted:  # same ISA circuit => one pre-registered simulation per name
            predicted[name] = _predict(isa, backend, shots, seed_simulator)
        counts = predicted[name]
        if name in SUCCESS_FN:
            check = SUCCESS_FN[name]
            success = sum(v for b, v in counts.items() if check(b)) / shots
            kind = circuits[name].metadata["kind"]
        else:
            target = "1" if name.endswith("ones") else "0"
            success = sum(v for b, v in counts.items() if set(b) <= {target}) / shots
            kind = "calibration"
        job: dict[str, Any] = {
            "index": index,
            "name": name,
            "kind": kind,
            "config": cfg,
            "pilot": pilot,
            "shots": shots,
            "isa_sha256": sha256_hex(data),  # of the saved .qpy bytes (not deterministic)
            "content_sha256": sha256_hex(qasm3.dumps(isa).encode()),  # of the circuit itself
            "estimated_seconds": estimates[index],
            "measured_qubits": measured_qubits(isa),
            "prediction": {
                "model": f"aer_from_backend:{backend.name} (noise only; dd/twirl not modelled)",
                "counts": {k: int(v) for k, v in counts.items()},
                "success_probability": success,
                "seed_simulator": seed_simulator,
            },
        }
        if cfg in TWIRLED_CONFIGS:
            job["num_randomizations"] = NUM_RANDOMIZATIONS
            job["shots_per_randomization"] = shots_per_randomization(shots)
        jobs.append(job)

    total = round(sum(j["estimated_seconds"] for j in jobs), 1)
    if total > max_total_seconds:
        raise ValueError(f"total estimate {total} s exceeds {max_total_seconds} s")
    plan = {
        "batch_id": batch_id,
        "created": created.isoformat(),
        "backend": backend.name,
        "backend_choice_reason": backend_choice_reason,
        "first_pilot": first_pilot,
        "excluded": [{"name": n, "reason": r} for n, r in exclude.items()],
        "shots": shots,
        "seed_transpiler": seed_transpiler,
        "m3_qubits": qubits,
        "total_estimated_seconds": total,
        "jobs": jobs,
    }
    # everything is computed and checked: only now touch the disk
    (batch_dir / "circuits").mkdir(parents=True, exist_ok=False)
    for index, data in qpy_files.items():
        (batch_dir / "circuits" / f"{index}.qpy").write_bytes(data)
    (batch_dir / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return batch_dir


def _choose_backend(service: Any, wanted: str) -> tuple[Any, str]:
    """Read-only: use ``wanted`` if the instance sees it and it is operational, else least busy."""
    try:
        backend = service.backend(wanted)
        status = backend.status()
        if status.operational:
            return (
                backend,
                f"{wanted} visible and operational (pending jobs: {status.pending_jobs})",
            )
        why = f"{wanted} not operational: {status.status_msg}"
    except Exception as exc:  # noqa: BLE001 - any failure to see it means fall back
        why = f"{wanted} not usable on this instance: {type(exc).__name__}: {exc}"
    backend = service.least_busy(operational=True, simulator=False, min_num_qubits=133)
    return backend, f"{why}; fell back to least-busy {backend.name}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--backend", help="IBM backend name (reads properties, no job)")
    group.add_argument("--fake", action="store_true", help="use FakeKingston (offline dry plan)")
    ap.add_argument("--shots", type=int, default=DEFAULT_SHOTS)
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    ap.add_argument("--batch-id")
    ap.add_argument(
        "--first-pilot",
        help="circuit whose raw job becomes pilot index 0 (submitted first)",
    )
    args = ap.parse_args(argv)

    from quantum.backends import get_fake_backend
    from quantum.circuits.registry import REQUIRED_NAMES, build_circuit

    reason = "FakeKingston (offline dry plan)"
    if args.fake:
        backend = get_fake_backend()
    else:
        from quantum.run.hardware import default_service_factory

        backend, reason = _choose_backend(default_service_factory().service, args.backend)
    circuits = {name: build_circuit(name) for name in REQUIRED_NAMES}
    batch_dir = build_plan(
        circuits,
        backend,
        shots=args.shots,
        out_root=args.out_root,
        batch_id=args.batch_id,
        backend_choice_reason=reason,
        first_pilot=args.first_pilot,
    )
    plan = json.loads((batch_dir / "plan.json").read_text())
    print(f"plan: {batch_dir / 'plan.json'}")
    print(f"jobs: {len(plan['jobs'])}  total_estimated_seconds: {plan['total_estimated_seconds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
