"""QPU-budget behaviour of scripts/submit_hardware.py (names contain `budget`: gate runs them).

Flow under test (lead + builder, 2026-11-08): approval, remaining >= plan total, pilots one at a
time (check_job -> submit -> journal -> poll -> usage -> raw -> ledger), then ONE check_job for
the rest, all submitted together; an overrun / ERROR / CANCELLED / 4317 cancels the unfinished
jobs, still ledgers every submitted job, writes stopped.json and exits non-zero.
"""

from pathlib import Path

import pytest

pytest.importorskip("scripts.submit_hardware")
from qiskit_ibm_runtime.exceptions import IBMRuntimeError  # noqa: E402

from quantum.run import budget  # noqa: E402
from tests.phase2.fakes import FakeService, JobScript, JobSpec, make_batch  # noqa: E402
from tests.phase2.harness import (  # noqa: E402
    good_scripts,
    late,
    ledger,
    ledger_total,
    raw_files,
    read_json,
    run_submit,
    write_ledger,
)

OK_COUNTS = {"00": 2000, "11": 2096}


class SnapService(FakeService):
    """Records how many ledger entries existed at the moment of every submit()."""

    def __init__(self, scripts, ledger_path):
        super().__init__(scripts)
        self.ledger_path = ledger_path
        self.ledger_len_at_submit: list[int] = []

    def submit(self, backend, isa_circuit, *, shots, config):
        self.ledger_len_at_submit.append(len(ledger(self.ledger_path)))
        return super().submit(backend, isa_circuit, shots=shots, config=config)


def make(tmp_path, specs, used=0.0):
    batch = make_batch(tmp_path / "hw", specs)
    return batch, write_ledger(tmp_path / "budget.json", used)


def pilots2(est=4.0):
    return [
        JobSpec("grover_present_k2", "raw", est, pilot=True),
        JobSpec("grover_present_k2", "m3_cal", est, pilot=True),
    ]


def rest(n, est=4.0, config="raw"):
    return [JobSpec("grover_present_k3", config, est) for _ in range(n)]


def all_submitted_are_ledgered(service, led):
    ids = {e["job_id"] for e in ledger(led)}
    assert {j.job_id() for j in service.jobs} <= ids, "a submitted job is missing from the ledger"


def stopped(batch):
    s = read_json(batch / "stopped.json")
    assert {"reason", "index", "message"} <= set(s)
    return s


# ---- check before, record after, actual usage ----------------------------------------------


def test_budget_every_job_is_ledgered_with_its_actual_usage(tmp_path):
    batch, led = make(tmp_path, pilots2() + rest(2))
    usages = [1.1, 2.2, 3.3, 3.9]
    service = FakeService([JobScript(counts=OK_COUNTS, usage=[u]) for u in usages])
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 0
    entries = ledger(led)
    assert sorted(e["seconds"] for e in entries) == sorted(usages)
    assert {e["job_id"] for e in entries} == {j.job_id() for j in service.jobs}
    assert all(e["backend"] == "fake_backend" and e["label"] for e in entries)
    raws = raw_files(batch)
    assert sum(r["usage_seconds"] for r in raws.values()) == pytest.approx(sum(usages))
    assert ledger_total(led) == pytest.approx(sum(usages))


def test_budget_pilots_run_one_at_a_time_then_the_rest_are_submitted_together(tmp_path):
    specs = [
        JobSpec("grover_present_k2", "raw", 2.0, pilot=True),
        JobSpec("grover_present_k2", "dd", 2.0, pilot=True),
        JobSpec("grover_present_k2", "dd_twirl", 2.0, pilot=True),
        JobSpec("grover_present_k2", "m3_cal", 2.0, pilot=True),
        *rest(3, 3.0),
    ]
    batch, led = make(tmp_path, specs)
    service = SnapService(good_scripts(7, usage=1.0), led)
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 0
    assert service.submitted_configs[:4] == ["raw", "dd", "dd_twirl", "m3_cal"]
    # pilot k sees exactly k earlier jobs in the ledger (record_job came before the next submit);
    # the three remaining jobs are all submitted after the four pilots, before any of them ends
    assert service.ledger_len_at_submit[:4] == [0, 1, 2, 3]
    assert service.ledger_len_at_submit[4:] == [4, 4, 4]


def test_budget_remaining_below_plan_total_stops_before_any_submit(tmp_path):
    batch, led = make(tmp_path, pilots2() + rest(2), used=535.0)  # 5 s left, plan needs 16 s
    service = FakeService(good_scripts(4))
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 4
    assert service.n_submitted == 0
    assert ledger_total(led) == pytest.approx(535.0)
    assert stopped(batch)["reason"]


def test_budget_plan_that_exactly_fits_the_remaining_is_allowed(tmp_path):
    batch, led = make(tmp_path, pilots2(2.0) + rest(2, 3.0), used=530.0)  # needs 10, has 10
    service = FakeService(good_scripts(4, usage=1.0))
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 0 and service.n_submitted == 4


def test_budget_single_check_before_the_batch_catches_a_concurrent_writer(tmp_path):
    batch, led = make(tmp_path, pilots2(2.0) + rest(2, 4.0), used=500.0)

    def another_session_spends():
        budget.record_job("other-session", 35.0, "ibm_other", "elsewhere", path=led, enforce=False)

    service = FakeService(
        [
            JobScript(counts=OK_COUNTS, usage=[1.0], on_usage_final=another_session_spends),
            JobScript(counts=OK_COUNTS, usage=[1.0]),
            *good_scripts(2),
        ]
    )
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 4, "used 500 + 35 + 2 pilots + 8 for the rest exceeds 540"
    assert service.n_submitted == 2, "only the pilots ran"
    all_submitted_are_ledgered(service, led)
    assert stopped(batch)["reason"]


# ---- pilots --------------------------------------------------------------------------------


@pytest.mark.parametrize("bad_pilot", [0, 1])
def test_budget_pilot_over_its_estimate_stops_the_batch(tmp_path, bad_pilot):
    batch, led = make(tmp_path, pilots2(4.0) + rest(3))
    scripts = good_scripts(5, usage=1.0)
    scripts[bad_pilot] = JobScript(counts=OK_COUNTS, usage=[5.0])
    service = FakeService(scripts)
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 3
    assert service.n_submitted == bad_pilot + 1, "nothing after the bad pilot, no non-pilot job"
    all_submitted_are_ledgered(service, led)
    assert max(e["seconds"] for e in ledger(led)) == 5.0, "the real usage is recorded"
    s = stopped(batch)
    assert s["index"] == bad_pilot


def test_budget_pilot_exactly_at_its_estimate_is_not_an_overrun(tmp_path):
    batch, led = make(tmp_path, pilots2(4.0) + rest(1))
    out = run_submit(batch, FakeService(good_scripts(3, usage=4.0)), budget_path=led)
    assert out.code == 0


# ---- usage() is 0 until final ----------------------------------------------------------------


def test_budget_zero_usage_is_never_recorded_the_final_value_is(tmp_path):
    batch, led = make(tmp_path, pilots2() + rest(1))
    scripts = good_scripts(3, usage=1.0)
    scripts[0] = JobScript(counts=OK_COUNTS, usage=[0.0, 0.0, 3.2])
    service = FakeService(scripts)
    out = run_submit(batch, service, budget_path=led, poll_seconds=7)
    assert out.code == 0
    first = next(e for e in ledger(led) if e["job_id"] == service.jobs[0].job_id())
    assert first["seconds"] == 3.2
    assert raw_files(batch)[0]["usage_seconds"] == 3.2
    assert out.sleeps.count(7) >= 2, "it must wait between usage polls"
    assert all(e["seconds"] > 0 for e in ledger(led))


def test_budget_usage_still_zero_after_the_poll_limit_stops_and_never_records_zero(tmp_path):
    batch, led = make(tmp_path, pilots2(4.0) + rest(2))
    service = FakeService([JobScript(counts=OK_COUNTS, usage=[0.0]), *good_scripts(3)])
    out = run_submit(batch, service, budget_path=led, max_usage_polls=3)
    assert out.code == 7
    assert service.n_submitted == 1
    usage_calls = [c for c in service.calls if c[0] == "job.usage"]
    assert len(usage_calls) == 3
    raw = raw_files(batch)[0]
    assert raw["usage_seconds"] is None and raw["usage_unknown"] is True
    (entry,) = ledger(led)
    assert entry["seconds"] == 4.0, "conservative: the job's estimate, not 0"
    assert entry["label"].startswith("usage_unknown:")
    assert stopped(batch)["reason"]


# ---- failed and cancelled jobs still count ---------------------------------------------------


@pytest.mark.parametrize("status", ["ERROR", "CANCELLED"])
def test_budget_failed_or_cancelled_job_is_still_ledgered_with_its_usage(tmp_path, status):
    batch, led = make(tmp_path, pilots2() + rest(2))
    service = FakeService(
        [
            JobScript(final_status=status, usage=[2.5], error="boom: user error"),
            *good_scripts(3),
        ]
    )
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 6
    assert service.n_submitted == 1
    (entry,) = ledger(led)
    assert entry["seconds"] == 2.5 and entry["job_id"] == service.jobs[0].job_id()
    raw = raw_files(batch)[0]
    assert raw["status"] == status and raw["counts"] is None
    assert raw["usage_seconds"] == 2.5
    assert (raw["error"] or "").startswith("boom") or status == "CANCELLED"
    assert stopped(batch)["index"] == 0


# ---- error 4317 ----------------------------------------------------------------------------------


def test_budget_open_plan_limit_4317_at_submit_stops_with_exit_5(tmp_path):
    batch, led = make(tmp_path, pilots2() + rest(2))
    err = IBMRuntimeError("Failed to run program: 4317 - Open Plan usage limit exceeded.")
    service = FakeService([*good_scripts(2), JobScript(submit_raises=err), *good_scripts(1)])
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 5
    all_submitted_are_ledgered(service, led)
    assert len(ledger(led)) == service.n_submitted == 2, "the pilots ran and were recorded"
    assert stopped(batch)["reason"]


def test_budget_4317_on_a_pilot_stops_immediately(tmp_path):
    batch, led = make(tmp_path, pilots2() + rest(1))
    err = IBMRuntimeError("4317 Open Plan usage limit exceeded")
    out = run_submit(batch, FakeService([JobScript(submit_raises=err)]), budget_path=led)
    assert out.code == 5 and ledger(led) == []


def test_budget_other_runtime_errors_are_not_reported_as_the_open_plan_limit(tmp_path):
    batch, led = make(tmp_path, pilots2() + rest(1))
    err = IBMRuntimeError("Something else went wrong: 9999")
    service = FakeService([JobScript(submit_raises=err)])
    try:
        out = run_submit(batch, service, budget_path=led)
    except Exception:
        return  # propagating an unknown error is acceptable; calling it 4317 is not
    assert out.code != 5 and out.code != 0


# ---- mid-batch overrun ---------------------------------------------------------------------------


def test_budget_mid_batch_overrun_cancels_pending_jobs_and_ledgers_every_job(tmp_path):
    batch, led = make(tmp_path, pilots2(2.0) + rest(5, 4.0), used=100.0)
    scripts = [
        JobScript(counts=OK_COUNTS, usage=[2.0]),
        JobScript(counts=OK_COUNTS, usage=[2.0]),
        JobScript(counts=OK_COUNTS, usage=[3.0]),  # batch job: fine
        JobScript(counts=OK_COUNTS, usage=[6.0]),  # batch job: beats its 4.0 estimate
        *late(3, usage=0.0),  # still pending when the overrun is seen
    ]
    service = SnapService(scripts, led)
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 3
    assert service.n_submitted == 7, "after the pilots the batch is submitted in one go"
    cancelled = [c[1] for c in service.calls if c[0] == "job.cancel"]
    pending = [j.job_id() for j in service.jobs[4:]]
    assert set(pending) <= set(cancelled), "every unfinished job must be cancelled"
    assert service.jobs[3].job_id() not in cancelled, "the finished overrun job is not cancelled"
    raws = raw_files(batch)
    assert set(raws) == set(range(7)), "every submitted job has a raw file"
    for i in (4, 5, 6):
        assert raws[i]["status"] == "CANCELLED" and raws[i]["counts"] is None
    all_submitted_are_ledgered(service, led)
    assert len(ledger(led)) == 7 + 1  # seven jobs plus the pre-existing 100 s entry
    assert stopped(batch)["index"] == 3
    # the ledger never grows by more than the pilots' actuals + the remaining budget it checked
    added = ledger_total(led) - 100.0
    checked_remaining = 5 * 4.0
    assert added <= 2.0 + 2.0 + checked_remaining


def test_budget_job_that_pushes_the_ledger_over_the_cap_is_still_recorded(tmp_path):
    batch, led = make(tmp_path, pilots2(2.0) + rest(2, 3.0), used=530.0)  # plan 10 s, has 10 s
    scripts = [
        JobScript(counts=OK_COUNTS, usage=[2.0]),
        JobScript(counts=OK_COUNTS, usage=[2.0]),
        JobScript(counts=OK_COUNTS, usage=[20.0]),  # actually used 20 s, estimate was 3
        *late(1, usage=0.0),
    ]
    service = FakeService(scripts)
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 3
    assert ledger_total(led) > budget.CAP_SECONDS, "actual spend is recorded even past the cap"
    assert any(e["seconds"] == 20.0 for e in ledger(led))
    all_submitted_are_ledgered(service, led)
    with pytest.raises(budget.BudgetExceeded):  # and the guard now refuses anything new
        budget.check_job(1.0, path=led)


def test_budget_error_in_the_batch_cancels_unfinished_jobs_and_exits_6(tmp_path):
    batch, led = make(tmp_path, pilots2(2.0) + rest(3, 4.0))
    scripts = [
        *good_scripts(2, usage=1.0),
        JobScript(final_status="ERROR", usage=[1.5], error="bad circuit"),
        *late(2, usage=0.0),
    ]
    service = FakeService(scripts)
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 6
    cancelled = {c[1] for c in service.calls if c[0] == "job.cancel"}
    assert {j.job_id() for j in service.jobs[3:]} <= cancelled
    raws = raw_files(batch)
    assert raws[2]["status"] == "ERROR" and raws[2]["usage_seconds"] == 1.5
    all_submitted_are_ledgered(service, led)


def test_budget_the_ledger_file_is_the_one_passed_in_not_the_default(tmp_path):
    batch, led = make(tmp_path, pilots2() + rest(1))
    default = Path("results/budget.json")
    before = default.read_bytes() if default.exists() else None
    run_submit(batch, FakeService(good_scripts(3)), budget_path=led)
    assert (default.read_bytes() if default.exists() else None) == before
    assert len(ledger(led)) == 3
