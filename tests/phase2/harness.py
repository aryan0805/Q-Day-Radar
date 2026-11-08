"""Drive scripts/submit_hardware.main with fakes. Owned by reviewer."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path

from tests.phase2.fakes import Clock, FakeService, FakeStdin, JobScript, plan_hash

REASON_CODES = {"not_a_tty": 2, "hash_mismatch": 2, "plan_changed": 2,
                "not_approved": 2, "resume_refused": 8}  # fmt: skip


@dataclass
class Outcome:
    code: int
    reason: str | None
    stdout: str
    sleeps: list
    factory_calls: int
    clock: Clock
    stdin: FakeStdin
    raised: BaseException | None = None
    ledger_at_submit: list = field(default_factory=list)


def write_ledger(path: Path, used: float = 0.0, *, label: str = "earlier") -> Path:
    """A ledger with ``used`` seconds already spent an hour ago (inside the 28-day window)."""
    entries = []
    if used:
        ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        entries.append(
            {
                "job_id": "old-1",
                "timestamp": ts,
                "seconds": float(used),
                "backend": "b",
                "label": label,
            }  # fmt: skip
        )
    path.write_text(
        json.dumps({"version": 1, "cap_seconds": 540.0, "window_days": 28, "entries": entries})
    )
    return path


def ledger(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text())["entries"]


def ledger_total(path: Path) -> float:
    return sum(e["seconds"] for e in ledger(path))


def read_json(p: Path):
    return json.loads(Path(p).read_text())


def raw_files(batch: Path) -> dict[int, dict]:
    d = batch / "jobs"
    return {int(f.stem): read_json(f) for f in sorted(d.glob("*.json"))} if d.exists() else {}


def snapshot(batch: Path) -> dict[str, bytes]:
    return {
        str(f.relative_to(batch)): f.read_bytes() for f in sorted(batch.rglob("*")) if f.is_file()
    }


def run_submit(
    batch: Path,
    service: FakeService,
    *,
    budget_path: Path,
    typed: str | None = "__ok__",
    tty: bool = True,
    args: tuple[str, ...] = (),
    max_usage_polls: int = 3,
    poll_seconds: float = 7,
    clock: Clock | None = None,
) -> Outcome:
    sm = import_module("scripts.submit_hardware")
    prefix = plan_hash(batch)[:8]
    lines = [prefix if typed == "__ok__" else (typed or "")]
    stdin = FakeStdin(lines, tty=tty)
    out, sleeps, calls = io.StringIO(), [], []
    clock = clock or Clock()

    def factory(*a, **k):
        calls.append(1)
        return service

    try:
        code = sm.main(
            [str(batch), *args],
            stdin=stdin,
            stdout=out,
            service_factory=factory,
            budget_path=budget_path,
            clock=clock,
            sleep=sleeps.append,
            max_usage_polls=max_usage_polls,
            poll_seconds=poll_seconds,
        )
        reason = None
    except Exception as exc:
        reason = getattr(exc, "reason", None)
        if reason not in REASON_CODES:
            raise
        code, reason = REASON_CODES[reason], reason
    return Outcome(code, reason, out.getvalue(), sleeps, len(calls), clock, stdin)


def good_scripts(n: int, usage: float = 1.0) -> list[JobScript]:
    return [JobScript(counts={"00": 2000, "11": 2096}, usage=[usage]) for _ in range(n)]


def late(n: int, usage: float = 1.0) -> list[JobScript]:
    """Jobs that never finish on their own (they only end if cancelled)."""
    return [
        JobScript(counts={"00": 4096}, usage=[usage], statuses_before_final=10_000)
        for _ in range(n)
    ]
