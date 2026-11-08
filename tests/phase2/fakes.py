"""A scripted fake IBM service and batch-directory builder for the submit/analyze tests.

Nothing here talks to a network. The fake implements ONLY the calls builder's [INTERFACE]
allows on the injected service (backend, submit, close) and on a job (job_id, status, counts,
usage, error_message, cancel). It records every call so tests can assert what was and was not
done, and `FakeBackend.run` raises: nothing may bypass `service.submit`.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from qiskit import QuantumCircuit, qpy


@dataclass
class JobScript:
    """What one fake job does. ``usage`` is the sequence usage() returns (last value repeats)."""

    counts: dict[str, int] | None = None
    usage: list[float] = field(default_factory=lambda: [1.0])
    final_status: str = "DONE"  # DONE | ERROR | CANCELLED
    error: str | None = None
    submit_raises: Exception | None = None
    statuses_before_final: int = 1  # how many status() polls return RUNNING first
    on_usage_final: object = None  # callable run once, when usage() first returns a final value
    crash_on_status: bool = False  # status() raises RuntimeError (simulates a crash after submit)


class FakeBackend:
    name = "fake_backend"

    def __init__(self, service: FakeService):
        self._service = service

    def run(self, *args, **kwargs):  # pragma: no cover - must never be reached
        self._service.calls.append(("backend.run", args, kwargs))
        raise AssertionError("backend.run was called: every QPU path must go through submit()")


class FakeJob:
    def __init__(self, service: FakeService, index: int, script: JobScript):
        self._service, self.index, self.script = service, index, script
        self._status_polls = 0
        self._usage_polls = 0
        self._cancelled = False
        self._id = f"{service.id_prefix}-{index:03d}"

    def job_id(self) -> str:
        return self._id

    def status(self) -> str:
        self._service.calls.append(("job.status", self._id))
        if self.script.crash_on_status:
            raise RuntimeError("simulated crash after submit")
        if self._cancelled:
            return "CANCELLED"
        self._status_polls += 1
        if self._status_polls <= self.script.statuses_before_final:
            return "RUNNING" if self._status_polls > 1 else "QUEUED"
        return self.script.final_status

    def counts(self) -> dict[str, int]:
        self._service.calls.append(("job.counts", self._id))
        if self.script.final_status != "DONE" or self._cancelled:
            raise RuntimeError("no counts: the job did not finish")
        return dict(self.script.counts or {})

    def usage(self) -> float:
        self._service.calls.append(("job.usage", self._id))
        seq = self.script.usage
        if self._cancelled and not self._status_polls_done():
            return 0.0
        value = seq[min(self._usage_polls, len(seq) - 1)]
        self._usage_polls += 1
        if value > 0 and self.script.on_usage_final is not None:
            hook, self.script.on_usage_final = self.script.on_usage_final, None
            hook()
        return value

    def _status_polls_done(self) -> bool:
        return self._status_polls > self.script.statuses_before_final

    def error_message(self) -> str | None:
        return self.script.error

    def cancel(self) -> None:
        self._service.calls.append(("job.cancel", self._id))
        self._cancelled = True


class FakeService:
    """Hands out FakeJobs in submission order from ``scripts`` (extra submissions are an error)."""

    def __init__(self, scripts: list[JobScript], id_prefix: str = "fake-job"):
        self.id_prefix = id_prefix  # a second service (a resume) must not reuse earlier job ids
        self.scripts = list(scripts)
        self.calls: list[tuple] = []
        self.jobs: list[FakeJob] = []
        self.submitted_hashes: list[str] = []
        self.submitted_configs: list[str] = []
        self.known: list[FakeJob] = []  # jobs the "IBM side" already has (for reconcile)
        self.closed = False

    def backend(self, name: str) -> FakeBackend:
        self.calls.append(("service.backend", name))
        return FakeBackend(self)

    def submit(self, backend, isa_circuit, *, shots: int, config: str) -> FakeJob:
        self.calls.append(("service.submit", config, shots))
        idx = len(self.jobs)
        if idx >= len(self.scripts):
            raise AssertionError(f"unexpected submission #{idx}: only {len(self.scripts)} scripted")
        script = self.scripts[idx]
        if script.submit_raises is not None:
            raise script.submit_raises
        buf = io.BytesIO()
        qpy.dump(isa_circuit, buf)
        self.submitted_hashes.append(hashlib.sha256(buf.getvalue()).hexdigest())
        self.submitted_configs.append(config)
        job = FakeJob(self, idx, script)
        self.jobs.append(job)
        return job

    def job(self, job_id: str) -> FakeJob:
        """Re-fetch a job by id (used by reconcile); it must never create a new one."""
        self.calls.append(("service.job", job_id))
        for job in list(self.jobs) + self.known:
            if job.job_id() == job_id:
                return job
        raise KeyError(job_id)

    def close(self) -> None:
        self.closed = True

    @property
    def n_submitted(self) -> int:
        return len(self.jobs)

    def call_names(self) -> list[str]:
        return [c[0] for c in self.calls]


class FakeStdin:
    """A scriptable stdin: ``tty`` controls isatty(); ``lines`` are what the human types."""

    def __init__(self, lines: list[str] | str = "", *, tty: bool = True):
        self._lines = [lines] if isinstance(lines, str) else list(lines)
        self._tty = tty
        self.reads = 0

    def isatty(self) -> bool:
        return self._tty

    def readline(self) -> str:
        self.reads += 1
        return (self._lines.pop(0) + "\n") if self._lines else ""


class Clock:
    """A tz-aware clock that advances one second per call (so created > approved_at)."""

    def __init__(self, start: datetime | None = None, step_seconds: float = 1.0):
        self.t = start or datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
        self.step = timedelta(seconds=step_seconds)

    def __call__(self) -> datetime:
        self.t += self.step
        return self.t


@dataclass
class JobSpec:
    name: str = "grover_present_k2"
    config: str = "raw"
    estimated_seconds: float = 4.0
    shots: int = 4096
    kind: str = "generic"
    pilot: bool = False


def tiny_circuit(i: int) -> QuantumCircuit:
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    for _ in range(i):  # make every circuit's QPY bytes (hence hash) different
        qc.x(1)
        qc.x(1)
    qc.measure([0, 1], [0, 1])
    return qc


def qpy_bytes(qc: QuantumCircuit) -> bytes:
    buf = io.BytesIO()
    qpy.dump(qc, buf)
    return buf.getvalue()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def make_batch(root: Path, specs: list[JobSpec], *, batch_id: str = "test-batch") -> Path:
    """Write plan.json and circuits/<i>.qpy the way plan_hardware.py does (no QPU, no network)."""
    batch = root / batch_id
    (batch / "circuits").mkdir(parents=True)
    jobs = []
    for i, spec in enumerate(specs):
        data = qpy_bytes(tiny_circuit(i))
        (batch / "circuits" / f"{i}.qpy").write_bytes(data)
        jobs.append(
            {
                "index": i,
                "name": spec.name,
                "kind": spec.kind,
                "config": spec.config,
                "shots": spec.shots,
                "isa_sha256": sha(data),
                "estimated_seconds": spec.estimated_seconds,
                "pilot": spec.pilot,
                "prediction": {
                    "model": "aer_from_backend:fake",
                    "counts": {"00": spec.shots // 2, "11": spec.shots - spec.shots // 2},
                    "success_probability": 0.5,
                },
            }
        )
    plan = {
        "batch_id": batch_id,
        "created": datetime(2026, 11, 8, 11, 0, tzinfo=UTC).isoformat(),
        "backend": "fake_backend",
        "total_estimated_seconds": round(sum(s.estimated_seconds for s in specs), 6),
        "jobs": jobs,
    }
    (batch / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return batch


def plan_hash(batch: Path) -> str:
    return sha((batch / "plan.json").read_bytes())
