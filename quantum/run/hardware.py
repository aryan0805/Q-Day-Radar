"""Hardware plumbing for the single human-approved IBM batch.

Nothing here runs at import time: no ``.env`` loading, no service construction, no network.
The real IBM adapter (``RuntimeAdapter``) is built ONLY by ``default_service_factory()``, which
``scripts/submit_hardware.py`` calls after every approval guard has passed. Tests inject a fake
service that implements the same small surface:

    service.backend(name)                                    -> backend
    service.submit(backend, isa, *, shots, config)           -> job
    service.job(job_id)                                      -> job   (reconcile; never submits)
    service.close()                                          -> None
    job.job_id() / job.status() / job.counts() / job.usage() / job.error_message() / job.cancel()

Mitigation configs (``CONFIGS``): ``raw``, ``dd`` (XY4), ``dd_twirl`` (XY4 + gate and
measurement twirling), ``control`` (raw options, Beauregard only), ``m3_cal`` (readout
calibration, raw options). M3 correction is applied in analysis, never as a job config.
Dynamic circuits (Beauregard) are incompatible with dynamical decoupling, so they get raw only.
"""

from __future__ import annotations

import hashlib
import io
import math
import os
from typing import Any

import numpy as np
from qiskit import QuantumCircuit, qpy

SAFETY = 1.5
OVERHEAD_S = 2.0  # IBM: ~2 s per sub-job
REP_DELAY_S = 250e-6  # backend.default_rep_delay on most IBM backends
MEAS_PAD_S = 5e-6  # reset / init time per shot
MID_CIRCUIT_S = 2e-6  # extra per mid-circuit measure or reset
DEFAULT_SHOTS = 4096
NUM_RANDOMIZATIONS = 32

CONFIGS = ("raw", "dd", "dd_twirl", "control", "m3_cal")
TWIRLED_CONFIGS = ("dd_twirl",)
TERMINAL_STATES = ("DONE", "ERROR", "CANCELLED")


class ApprovalRefused(RuntimeError):
    """Raised when a submit guard refuses; ``reason`` names the guard."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# --- estimate model -----------------------------------------------------------------------


def shots_per_randomization(shots: int) -> int:
    return math.ceil(shots / NUM_RANDOMIZATIONS)


def estimate_from_duration(
    duration_s: float, shots: int, n_mid_circuit: int = 0, config: str = "raw"
) -> float:
    """Conservative QPU-seconds estimate for one job of ``shots`` shots.

    ``SAFETY * max(own model, IBM baseline)``, rounded up to 0.1 s. IBM baseline:
    ``2 + (rep_delay + circuit_length) * executions``. Twirling keeps total executions at
    ``num_randomizations * shots_per_randomization >= shots``, so it is counted on that product.
    """
    if config not in CONFIGS:
        raise ValueError(f"unknown config {config!r}")
    if duration_s < 0 or shots <= 0 or n_mid_circuit < 0:
        raise ValueError("need duration >= 0, shots > 0, n_mid_circuit >= 0")
    executions = shots
    if config in TWIRLED_CONFIGS:
        executions = NUM_RANDOMIZATIONS * shots_per_randomization(shots)
    own = OVERHEAD_S + executions * (
        REP_DELAY_S + duration_s + MID_CIRCUIT_S * n_mid_circuit + MEAS_PAD_S
    )
    ibm = OVERHEAD_S + executions * (REP_DELAY_S + duration_s)
    return math.ceil(SAFETY * max(own, ibm) * 10 - 1e-9) / 10


def count_mid_circuit(isa: QuantumCircuit) -> int:
    """Measures that are followed by more operations on the same qubit, plus resets."""
    n = 0
    last_use: dict[int, str] = {}
    for inst in isa.data:
        name = inst.operation.name
        for q in inst.qubits:
            idx = isa.find_bit(q).index
            if name == "reset":
                n += 1
            if last_use.get(idx) == "measure" and name != "measure":
                n += 1
            last_use[idx] = name
    return n


def _inline_conditionals(isa: QuantumCircuit) -> QuantumCircuit:
    """Copy of ``isa`` with every if_else body applied unconditionally (worst-case duration)."""
    out = isa.copy_empty_like()
    for inst in isa.data:
        op = inst.operation
        if op.name != "if_else":
            out.append(op, inst.qubits, inst.clbits)
            continue
        body = op.params[0]
        qmap = dict(zip(body.qubits, inst.qubits, strict=True))
        for b in body.data:
            if not b.clbits:
                out.append(b.operation, [qmap[q] for q in b.qubits])
    return out


def estimate_seconds(isa: QuantumCircuit, shots: int, *, target: Any, config: str) -> float:
    """``estimate_from_duration`` with the circuit's duration on ``target``.

    The device target has no duration for ``if_else``, so conditional bodies are counted as if
    always executed (an upper bound) and the feed-forward latency is covered by MID_CIRCUIT_S.
    """
    timed = _inline_conditionals(isa) if "if_else" in isa.count_ops() else isa
    duration = float(timed.estimate_duration(target))
    return estimate_from_duration(duration, shots, count_mid_circuit(isa), config)


# --- job options --------------------------------------------------------------------------


def config_options(config: str, shots: int) -> dict[str, dict[str, Any]]:
    """SamplerV2 option overrides (plain dict) for a config."""
    if config not in CONFIGS:
        raise ValueError(f"unknown config {config!r}")
    if config in ("raw", "control", "m3_cal"):
        return {}
    options: dict[str, dict[str, Any]] = {
        "dynamical_decoupling": {"enable": True, "sequence_type": "XY4"}
    }
    if config == "dd_twirl":
        options["twirling"] = {
            "enable_gates": True,
            "enable_measure": True,
            "num_randomizations": NUM_RANDOMIZATIONS,
            "shots_per_randomization": shots_per_randomization(shots),
        }
    return options


# --- QPY helpers --------------------------------------------------------------------------


def qpy_bytes(circuit: QuantumCircuit) -> bytes:
    buf = io.BytesIO()
    qpy.dump(circuit, buf)
    return buf.getvalue()


def load_qpy(data: bytes) -> QuantumCircuit:
    return qpy.load(io.BytesIO(data))[0]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- M3 readout calibration (circuits go through our submit path only) ---------------------


def measured_qubits(isa: QuantumCircuit) -> list[int]:
    """Physical qubit measured into each classical bit, ordered by classical bit index."""
    mapping: dict[int, int] = {}
    for inst in isa.data:
        if inst.operation.name == "measure":
            mapping[isa.find_bit(inst.clbits[0]).index] = isa.find_bit(inst.qubits[0]).index
    return [mapping[i] for i in sorted(mapping)]


def m3_calibration_circuit(
    n_device_qubits: int, qubits: list[int], *, ones: bool
) -> QuantumCircuit:
    """ISA-ready circuit preparing |0..0> (or |1..1>) on ``qubits`` and measuring them."""
    qc = QuantumCircuit(
        n_device_qubits, len(qubits), name="m3_cal_ones" if ones else "m3_cal_zeros"
    )
    if ones:
        for q in qubits:
            qc.x(q)
    for i, q in enumerate(qubits):
        qc.measure(q, i)
    qc.metadata = {"name": qc.name, "kind": "calibration", "qubits": list(qubits)}
    return qc


def readout_matrices(
    zeros_counts: dict[str, int], ones_counts: dict[str, int], qubits: list[int]
) -> dict[int, np.ndarray]:
    """Per-qubit assignment matrices ``[[P(0|0), P(0|1)], [P(1|0), P(1|1)]]`` by physical qubit."""
    out: dict[int, np.ndarray] = {}
    n0, n1 = sum(zeros_counts.values()), sum(ones_counts.values())
    for i, q in enumerate(qubits):
        p1_given_0 = sum(v for b, v in zeros_counts.items() if b[::-1][i] == "1") / n0
        p0_given_1 = sum(v for b, v in ones_counts.items() if b[::-1][i] == "0") / n1
        out[q] = np.array([[1 - p1_given_0, p0_given_1], [p1_given_0, 1 - p0_given_1]])
    return out


# --- real adapter (built only by default_service_factory) ---------------------------------


class RuntimeJob:
    """Thin wrapper over a qiskit-ibm-runtime job with the small surface submit needs."""

    def __init__(self, job: Any):
        self._job = job

    def job_id(self) -> str:
        return self._job.job_id()

    def status(self) -> str:
        state = str(getattr(self._job.status(), "name", self._job.status())).upper()
        return {"INITIALIZING": "QUEUED", "VALIDATING": "QUEUED"}.get(state, state)

    def counts(self) -> dict[str, int]:
        data = self._job.result()[0].data
        register = next(iter(data.values()))
        return dict(register.get_counts())

    def usage(self) -> float:
        return float(self._job.usage())

    def error_message(self) -> str | None:
        try:
            return self._job.error_message()
        except Exception:  # noqa: BLE001 - best effort; a missing message is not fatal
            return None

    def cancel(self) -> None:
        self._job.cancel()


class RuntimeAdapter:
    """Real IBM Runtime service in batch mode (Open Plan: job or batch only, no sessions)."""

    def __init__(self, service: Any):
        self._service = service
        self._batch: Any = None

    @property
    def service(self) -> Any:
        """The underlying QiskitRuntimeService (read-only use, e.g. backend status)."""
        return self._service

    def backend(self, name: str) -> Any:
        return self._service.backend(name)

    def submit(self, backend: Any, isa: QuantumCircuit, *, shots: int, config: str) -> RuntimeJob:
        from qiskit_ibm_runtime import Batch, SamplerV2

        if self._batch is None:
            self._batch = Batch(backend=backend)
        sampler = SamplerV2(mode=self._batch)
        for group, values in config_options(config, shots).items():
            for key, value in values.items():
                setattr(getattr(sampler.options, group), key, value)
        return RuntimeJob(sampler.run([isa], shots=shots))

    def job(self, job_id: str) -> RuntimeJob:
        return RuntimeJob(self._service.job(job_id))

    def close(self) -> None:
        if self._batch is not None:
            self._batch.close()
            self._batch = None


def default_service_factory() -> RuntimeAdapter:
    """Build the real adapter. Only submit_hardware.py calls this, after the guards pass."""
    from dotenv import load_dotenv
    from qiskit_ibm_runtime import QiskitRuntimeService

    from quantum.backends import TOKEN_ENV, MissingTokenError

    load_dotenv()
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise MissingTokenError(f"No IBM Quantum token: set {TOKEN_ENV} in .env")
    kwargs: dict[str, Any] = {"channel": "ibm_quantum_platform", "token": token}
    if os.environ.get("QISKIT_IBM_INSTANCE"):
        kwargs["instance"] = os.environ["QISKIT_IBM_INSTANCE"]
    return RuntimeAdapter(QiskitRuntimeService(**kwargs))
