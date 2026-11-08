"""Phase 0: the QPU budget guard (quantum/run/budget.py).

Contract agreed in the builder's [INTERFACE] message:
  - cap 540 s in a rolling 28-day window; exactly 540 is allowed, 540.01 is not
  - window is  now - 28d < timestamp <= now
  - check_job writes nothing; record_job checks first, then appends
  - `now` is injectable, so window expiry is tested without sleeping

Every test uses tmp_path. None of them touches the real results/budget.json.
"""

import json
import math
import multiprocessing as mp
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quantum.run import budget
from quantum.run.budget import (
    CAP_SECONDS,
    WINDOW_DAYS,
    BudgetExceeded,
    check_job,
    load_budget,
    record_job,
    remaining_seconds,
    used_seconds,
)

T0 = datetime(2026, 11, 7, 16, 0, tzinfo=UTC)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "budget.json"


def _write_ledger(path: Path, entries: list[dict], cap: float = 540) -> None:
    path.write_text(
        json.dumps({"version": 1, "cap_seconds": cap, "window_days": 28, "entries": entries})
    )


def _entry(ts: datetime, seconds: float, job_id: str = "j") -> dict:
    return {
        "job_id": job_id,
        "timestamp": ts.isoformat(),
        "seconds": seconds,
        "backend": "ibm_kingston",
        "label": "",
    }


# ---- constants and file format -------------------------------------------------


def test_constants_match_the_plan():
    assert CAP_SECONDS == 540.0  # 9 of the 10 free minutes; 1 minute held back
    assert WINDOW_DAYS == 28
    assert Path("results/budget.json") == budget.DEFAULT_PATH


def test_load_creates_empty_ledger_when_missing(path):
    assert not path.exists()
    data = load_budget(path)
    assert path.exists()
    assert data["version"] == 1
    assert data["cap_seconds"] == 540
    assert data["window_days"] == 28
    assert data["entries"] == []
    assert json.loads(path.read_text()) == data  # what's on disk is what was returned


def test_fresh_ledger_has_full_budget(path):
    assert used_seconds(path, now=T0) == 0
    assert remaining_seconds(path, now=T0) == 540


# ---- the cap: the exit criterion ----------------------------------------------


def test_job_exactly_at_cap_is_allowed(path):
    check_job(540.0, path, now=T0)  # must not raise


def test_job_just_over_cap_is_refused(path):
    with pytest.raises(BudgetExceeded):
        check_job(540.01, path, now=T0)


def test_cap_accounts_for_prior_usage(path):
    record_job("a", 300.0, "ibm_kingston", path=path, now=T0)
    check_job(240.0, path, now=T0)  # 300 + 240 = 540, allowed
    with pytest.raises(BudgetExceeded):
        check_job(240.01, path, now=T0)


def test_usage_sums_across_entries(path):
    record_job("a", 100.0, "ibm_kingston", path=path, now=T0)
    record_job("b", 150.5, "ibm_kingston", path=path, now=T0 + timedelta(hours=1))
    later = T0 + timedelta(hours=2)
    assert used_seconds(path, now=later) == pytest.approx(250.5)
    assert remaining_seconds(path, now=later) == pytest.approx(289.5)


def test_check_job_writes_nothing(path):
    record_job("a", 500.0, "ibm_kingston", path=path, now=T0)
    before = path.read_bytes()
    check_job(10.0, path, now=T0)  # allowed
    with pytest.raises(BudgetExceeded):
        check_job(50.0, path, now=T0)  # refused
    assert path.read_bytes() == before


def test_refused_record_job_does_not_append(path):
    record_job("a", 500.0, "ibm_kingston", path=path, now=T0)
    with pytest.raises(BudgetExceeded):
        record_job("b", 50.0, "ibm_kingston", path=path, now=T0)
    entries = json.loads(path.read_text())["entries"]
    assert [e["job_id"] for e in entries] == ["a"]
    assert used_seconds(path, now=T0) == 500.0


def test_cap_is_read_from_the_file(path):
    _write_ledger(path, [], cap=100)
    check_job(100.0, path, now=T0)
    with pytest.raises(BudgetExceeded):
        check_job(100.01, path, now=T0)


def test_remaining_never_goes_below_zero(path):
    # Over-cap ledger (e.g. the cap was lowered after jobs were recorded).
    _write_ledger(path, [_entry(T0, 150.0)], cap=100)
    assert remaining_seconds(path, now=T0) == 0


# ---- the rolling 28-day window ------------------------------------------------


def test_entry_inside_window_still_counts(path):
    record_job("a", 500.0, "ibm_kingston", path=path, now=T0)
    almost = T0 + timedelta(days=28) - timedelta(seconds=1)
    assert used_seconds(path, now=almost) == 500.0
    with pytest.raises(BudgetExceeded):
        check_job(50.0, path, now=almost)


def test_entry_exactly_28_days_old_has_expired(path):
    # Window is now-28d < timestamp, so an entry exactly 28d old is out.
    record_job("a", 500.0, "ibm_kingston", path=path, now=T0)
    edge = T0 + timedelta(days=28)
    assert used_seconds(path, now=edge) == 0
    check_job(540.0, path, now=edge)  # full cap available again


def test_expired_entry_frees_budget_but_stays_in_the_file(path):
    record_job("old", 500.0, "ibm_kingston", path=path, now=T0)
    later = T0 + timedelta(days=30)
    record_job("new", 500.0, "ibm_kingston", path=path, now=later)  # allowed now
    ids = [e["job_id"] for e in json.loads(path.read_text())["entries"]]
    assert ids == ["old", "new"]  # append-only: history is never dropped
    assert used_seconds(path, now=later) == 500.0  # only "new" counts


def test_budget_future_dated_entry_still_counts(path):
    """P002: an entry stamped after `now` (clock skew) must not hide spent QPU time."""
    record_job("fast-clock", 500.0, "ibm_kingston", path=path, now=T0 + timedelta(hours=1))
    assert used_seconds(path, now=T0) == 500.0
    with pytest.raises(BudgetExceeded):
        check_job(540.0, path, now=T0)  # 500 + 540 > 540


# ---- concurrent writers (P001) ------------------------------------------------


def _concurrent_worker(path: str, barrier, results) -> None:
    barrier.wait()  # release all workers together to force the overlap
    try:
        record_job("job", 100.0, "ibm_kingston", path=Path(path))
        results.put("ok")
    except BudgetExceeded:
        results.put("refused")


@pytest.mark.parametrize("trial", range(3))
def test_budget_concurrent_writers_never_lose_or_overspend(tmp_path, trial):
    """P001: 8 processes x 100 s against a 540 s cap.

    Correct outcome: exactly 5 jobs accepted, 5 entries on disk, 500 s recorded.
    Without a lock, all 8 are accepted and only ~2 entries survive (last writer wins).
    """
    n = 8
    ledger = tmp_path / "budget.json"
    load_budget(ledger)
    ctx = mp.get_context("spawn")
    barrier, results = ctx.Barrier(n), ctx.Queue()
    procs = [
        ctx.Process(target=_concurrent_worker, args=(str(ledger), barrier, results))
        for _ in range(n)
    ]
    for p in procs:
        p.start()
    outcomes = [results.get(timeout=60) for _ in range(n)]
    for p in procs:
        p.join(timeout=60)

    entries = json.loads(ledger.read_text())["entries"]
    assert outcomes.count("ok") == 5, outcomes
    assert len(entries) == 5, f"{len(entries)} entries on disk, expected 5"
    assert sum(e["seconds"] for e in entries) == 500.0


# ---- record_job ---------------------------------------------------------------


def test_record_job_returns_and_persists_the_entry(path):
    entry = record_job("job-1", 12.5, "ibm_kingston", label="bell", path=path, now=T0)
    assert entry["job_id"] == "job-1"
    assert entry["seconds"] == 12.5
    assert entry["backend"] == "ibm_kingston"
    assert entry["label"] == "bell"
    stamp = datetime.fromisoformat(entry["timestamp"])
    assert stamp == T0
    assert stamp.utcoffset() == timedelta(0)
    assert json.loads(path.read_text())["entries"] == [entry]


def test_recorded_jobs_persist_across_a_reload(path):
    record_job("a", 200.0, "ibm_kingston", label="first", path=path, now=T0)
    record_job("b", 100.0, "ibm_kingston", label="second", path=path, now=T0)
    reloaded = load_budget(path)  # fresh read from disk, no shared state
    assert [e["job_id"] for e in reloaded["entries"]] == ["a", "b"]
    assert used_seconds(path, now=T0) == 300.0
    with pytest.raises(BudgetExceeded):
        check_job(240.01, path, now=T0)


def test_record_job_leaves_no_temp_files(path):
    record_job("a", 1.0, "ibm_kingston", path=path, now=T0)
    record_job("b", 1.0, "ibm_kingston", path=path, now=T0)
    # The ledger, plus the P001 lock sidecar (budget.json.lock) once the lock exists.
    # Any ".budget-*.tmp" left behind by the atomic write would fail this.
    names = {p.name for p in path.parent.iterdir()}
    assert "budget.json" in names
    assert names <= {"budget.json", "budget.json.lock"}, names


# ---- input validation ---------------------------------------------------------

BAD_SECONDS = [-1.0, -0.01, math.nan, math.inf, -math.inf]


@pytest.mark.parametrize("bad", BAD_SECONDS)
def test_check_job_rejects_bad_estimates(path, bad):
    with pytest.raises(ValueError):
        check_job(bad, path, now=T0)


@pytest.mark.parametrize("bad", BAD_SECONDS)
def test_record_job_rejects_bad_seconds_and_appends_nothing(path, bad):
    with pytest.raises(ValueError):
        record_job("x", bad, "ibm_kingston", path=path, now=T0)
    assert used_seconds(path, now=T0) == 0
    assert json.loads(path.read_text())["entries"] == []
