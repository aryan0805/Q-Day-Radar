"""`submit_hardware.py <batch> --reconcile`: recover jobs journaled before a crash.

It never submits, never needs a TTY, never writes approval.json, and never overwrites a raw
file or records a job twice (names contain `immutable` / `budget` where the gate should run them).
"""

import json

import pytest

pytest.importorskip("scripts.submit_hardware")

from quantum.run import budget  # noqa: E402
from tests.phase2.fakes import FakeJob, FakeService, JobScript, JobSpec, make_batch  # noqa: E402
from tests.phase2.harness import (  # noqa: E402
    good_scripts,
    ledger,
    raw_files,
    run_submit,
    snapshot,
    write_ledger,
)

OK = {"00": 2000, "11": 2096}


def crashed_batch(tmp_path, crash_index):
    """Run a batch that dies (simulated) when job ``crash_index`` is first polled."""
    specs = [
        JobSpec("grover_present_k2", "raw", 4.0, pilot=True),
        JobSpec("grover_present_k2", "m3_cal", 4.0, pilot=True),
        JobSpec("grover_present_k3", "raw", 4.0),
        JobSpec("grover_present_k3", "dd", 4.0),
    ]
    batch = make_batch(tmp_path / "hw", specs)
    led = write_ledger(tmp_path / "budget.json")
    scripts = good_scripts(4, usage=2.0)
    scripts[crash_index] = JobScript(counts=OK, usage=[2.0], crash_on_status=True)
    service = FakeService(scripts)
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_submit(batch, service, budget_path=led)
    return batch, led, service


def ibm_side(service_after_crash, usages=(2.0,), **overrides):
    """A fresh service whose .job(id) returns what IBM would now report for each journaled id."""
    fresh = FakeService([])
    for job in service_after_crash.jobs:
        script = JobScript(counts=OK, usage=[usages[0]], statuses_before_final=0, **overrides)
        fresh.known.append(FakeJob(fresh, job.index, script))
    return fresh


def reconcile(batch, service, led, **kw):
    return run_submit(batch, service, budget_path=led, tty=False, args=("--reconcile",), **kw)


@pytest.mark.parametrize("crash_index", [0, 2])
def test_budget_reconcile_after_a_crash_ledgers_the_job_and_submits_nothing(tmp_path, crash_index):
    batch, led, crashed = crashed_batch(tmp_path, crash_index)
    journal = [json.loads(x) for x in (batch / "submitted.jsonl").read_text().splitlines()]
    assert crash_index in {j["index"] for j in journal}, "journaled before polling"
    assert crash_index not in raw_files(batch)
    ledgered_before = {e["job_id"] for e in ledger(led)}
    approval = (batch / "approval.json").read_bytes()

    fresh = ibm_side(crashed)
    out = reconcile(batch, fresh, led)
    assert out.code == 0
    assert "service.submit" not in fresh.call_names(), "reconcile must never submit"
    assert fresh.n_submitted == 0
    assert (batch / "approval.json").read_bytes() == approval
    raws = raw_files(batch)
    assert set(raws) == {j["index"] for j in journal}
    ids = [e["job_id"] for e in ledger(led)]
    assert len(ids) == len(set(ids)), "no job may be ledgered twice"
    assert {j["job_id"] for j in journal} <= set(ids)
    assert ledgered_before <= set(ids)
    done = raws[crash_index]
    assert done["status"] == "DONE" and done["usage_seconds"] == 2.0
    assert done["counts"] == OK


def test_budget_reconcile_twice_does_not_duplicate_ledger_entries(tmp_path):
    batch, led, crashed = crashed_batch(tmp_path, 0)
    assert reconcile(batch, ibm_side(crashed), led).code == 0
    ledger_after_first, files = ledger(led), snapshot(batch)
    assert reconcile(batch, ibm_side(crashed), led).code == 0
    assert ledger(led) == ledger_after_first
    assert snapshot(batch) == files


def test_budget_reconcile_does_not_double_record_a_job_that_is_already_in_the_ledger(tmp_path):
    # raw write failed after the ledger entry was made: reconcile must add the raw file only
    batch, led, crashed = crashed_batch(tmp_path, 0)
    jid = crashed.jobs[0].job_id()
    budget.record_job(jid, 2.0, "fake_backend", "pre-recorded", path=led, enforce=False)
    assert reconcile(batch, ibm_side(crashed), led).code == 0
    assert [e["job_id"] for e in ledger(led)].count(jid) == 1
    assert 0 in raw_files(batch)


def test_immutable_reconcile_never_overwrites_an_existing_raw_file(tmp_path):
    batch, led, crashed = crashed_batch(tmp_path, 2)
    (batch / "jobs").mkdir(exist_ok=True)
    existing = batch / "jobs" / "2.json"
    existing.write_text('{"planted": true}\n')
    out = reconcile(batch, ibm_side(crashed), led)
    assert out.code in (0, 7)
    assert existing.read_text() == '{"planted": true}\n'


def test_budget_reconcile_exits_7_when_usage_is_still_zero(tmp_path):
    batch, led, crashed = crashed_batch(tmp_path, 0)
    fresh = FakeService([])
    for job in crashed.jobs:
        fresh.known.append(FakeJob(fresh, job.index, JobScript(counts=OK, usage=[0.0])))
    out = reconcile(batch, fresh, led, max_usage_polls=3)
    assert out.code == 7
    assert "service.submit" not in fresh.call_names()
    entries = ledger(led)
    assert all(e["seconds"] > 0 for e in entries), "never record 0 silently"


def test_budget_reconcile_records_a_failed_job_with_its_usage(tmp_path):
    batch, led, crashed = crashed_batch(tmp_path, 0)
    fresh = ibm_side(crashed, usages=(1.7,), final_status="ERROR", error="user error")
    out = reconcile(batch, fresh, led)
    assert out.code == 0
    raw = raw_files(batch)[0]
    assert raw["status"] == "ERROR" and raw["counts"] is None and raw["usage_seconds"] == 1.7
    assert any(e["job_id"] == crashed.jobs[0].job_id() and e["seconds"] == 1.7 for e in ledger(led))


def test_budget_reconcile_needs_an_existing_approval(tmp_path):
    specs = [JobSpec("grover_present_k2", "raw", 4.0, pilot=True)]
    batch = make_batch(tmp_path / "hw", specs)
    led = write_ledger(tmp_path / "budget.json")
    service = FakeService([])
    try:
        out = reconcile(batch, service, led)
        assert out.code == 2
    except Exception as exc:  # a refusal raised as an exception is fine too
        assert "approv" in str(exc).lower() or getattr(exc, "reason", None)
    assert service.calls == [] and not (batch / "approval.json").exists()
