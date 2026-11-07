"""QPU-seconds ledger and guard (IBM Open Plan: 10 min per 28 days; we cap at 540 s).

The ledger is a rolling window over appended entries in ``results/budget.json``.
Every hardware submission must call ``check_job`` / ``record_job`` first.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

CAP_SECONDS: float = 540.0
WINDOW_DAYS: int = 28
DEFAULT_PATH: Path = Path("results/budget.json")
SCHEMA_VERSION = 1


class BudgetExceeded(RuntimeError):
    """Raised when a job would push QPU usage past the cap."""


def _now(now: datetime | None) -> datetime:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware")
    return now


def _check_seconds(value: float, name: str) -> float:
    if not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite number >= 0, got {value!r}")
    return float(value)


def _empty() -> dict:
    return {
        "version": SCHEMA_VERSION,
        "cap_seconds": CAP_SECONDS,
        "window_days": WINDOW_DAYS,
        "entries": [],
    }


def _write(data: dict, path: Path) -> None:
    """Atomic write: temp file in the same directory, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".budget-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_budget(path: Path = DEFAULT_PATH) -> dict:
    """Read the ledger, creating an empty one if the file does not exist."""
    path = Path(path)
    if not path.exists():
        data = _empty()
        _write(data, path)
        return data
    return json.loads(path.read_text())


def used_seconds(path: Path = DEFAULT_PATH, now: datetime | None = None) -> float:
    """QPU seconds in entries with ``timestamp > now - window``.

    There is no upper bound: a future-dated (clock-skewed) entry still counts, so the
    guard fails closed rather than open (P002).
    """
    now = _now(now)
    data = load_budget(path)
    start = now - timedelta(days=data.get("window_days", WINDOW_DAYS))
    total = 0.0
    for e in data["entries"]:
        if start < datetime.fromisoformat(e["timestamp"]):
            total += float(e["seconds"])
    return total


def _cap(data: dict) -> float:
    return float(data.get("cap_seconds", CAP_SECONDS))


def remaining_seconds(path: Path = DEFAULT_PATH, now: datetime | None = None) -> float:
    """Seconds left under the cap, never below 0."""
    cap = _cap(load_budget(path))
    return max(0.0, cap - used_seconds(path, now))


def check_job(
    estimated_seconds: float, path: Path = DEFAULT_PATH, now: datetime | None = None
) -> None:
    """Raise ``BudgetExceeded`` if used + estimated > cap. Writes nothing to the ledger."""
    est = _check_seconds(estimated_seconds, "estimated_seconds")
    cap = _cap(load_budget(path))
    used = used_seconds(path, now)
    if used + est > cap:
        raise BudgetExceeded(
            f"job of {est:.1f}s refused: {used:.1f}s already used of {cap:.0f}s "
            f"in the last {WINDOW_DAYS} days"
        )


def record_job(
    job_id: str,
    seconds: float,
    backend: str,
    label: str = "",
    path: Path = DEFAULT_PATH,
    now: datetime | None = None,
) -> dict:
    """Check the cap, then append the job to the ledger. Returns the new entry.

    The whole check -> load -> append -> write sequence holds an exclusive ``flock`` on
    ``<path>.lock`` so overlapping writers cannot overspend (P001). POSIX only
    (macOS and Linux are the targets). ``check_job`` stays lock-free.
    """
    now = _now(now)
    seconds = _check_seconds(seconds, "seconds")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        check_job(seconds, path, now)
        data = load_budget(path)
        entry = {
            "job_id": job_id,
            "timestamp": now.astimezone(UTC).isoformat(),
            "seconds": seconds,
            "backend": backend,
            "label": label,
        }
        data["entries"].append(entry)
        _write(data, path)
    return entry
