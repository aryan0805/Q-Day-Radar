"""`submit_hardware.py <batch> --resume`: continue a batch that stopped on a failed submit.

Background: IBM closed the Batch between two slow pilot jobs (error 1217, a 400 on create with no
job id), so the submit stopped (`stopped.json`, reason `submit_failed`, code 6) with jobs 0..k-1
done. A resume is a NEW human approval of the SAME plan: it sends only what never went out, all
inside one fresh Batch with no waiting between submits, after one budget check for the whole rest.

The state to resume from is produced by running the real submit against a fake service, never
written by hand. Test names carry the gate keywords: `approval` (guards), `immutable` (write-once
files), `budget` (the ledger and the cap).
"""

from __future__ import annotations

import json
import types
from datetime import datetime

import pytest

pytest.importorskip("scripts.submit_hardware")

import qiskit_ibm_runtime  # noqa: E402
from qiskit_ibm_runtime.exceptions import IBMRuntimeError  # noqa: E402

from quantum.run import budget  # noqa: E402
from quantum.run.hardware import RuntimeAdapter, qpy_bytes  # noqa: E402
from tests.phase2.fakes import (  # noqa: E402
    FakeJob,
    FakeService,
    JobScript,
    JobSpec,
    make_batch,
    plan_hash,
)
from tests.phase2.harness import (  # noqa: E402
    good_scripts,
    late,
    ledger,
    ledger_total,
    raw_files,
    read_json,
    run_submit,
    snapshot,
    write_ledger,
)

N_PILOTS, N_REST = 5, 7  # like the real plan: pilots 0-4 then the rest
OK = {"00": 2000, "11": 2096}
STOP_AT = 4  # the submit of index 4 failed with 1217; pilots 0-3 are done
EST = 4.0
USED = 2.0  # actual seconds per finished job (under the estimate)
ERR_1217 = IBMRuntimeError(
    "Failed to run program: '400 Client Error: Bad Request for url: "
    'https://quantum.cloud.ibm.com/api/v1/jobs. {"errors":[{"code":1217,'
    '"message":"Session has been closed."}]}\''
)
REMAINING = list(range(STOP_AT, N_PILOTS + N_REST))  # 4..11 go out on resume
REMAINING_SUM = len(REMAINING) * EST


def specs():
    out = [JobSpec("grover_present_k2", "raw", EST, pilot=True) for _ in range(N_PILOTS)]
    return out + [JobSpec("grover_present_k3", "raw", EST) for _ in range(N_REST)]


def stopped_batch(tmp_path, *, used=0.0):
    """Run the real submit until the submit of STOP_AT fails; return (batch, ledger, outcome)."""
    batch = make_batch(tmp_path / "hw", specs())
    led = write_ledger(tmp_path / "budget.json", used)
    scripts = [*good_scripts(STOP_AT, USED), JobScript(submit_raises=ERR_1217)]
    first = run_submit(batch, FakeService(scripts, id_prefix="first"), budget_path=led)
    assert first.code == 6, first.stdout
    assert set(raw_files(batch)) == set(range(STOP_AT))
    assert read_json(batch / "stopped.json")["reason"] == "submit_failed"
    return batch, led, first


def leave_remaining(led, seconds):
    """Someone else spends QPU time (another run, the Instances page): leave ``seconds`` free."""
    free = budget.remaining_seconds(path=led)
    budget.record_job("other-use", free - seconds, "b", "spent elsewhere", path=led, enforce=False)
    assert budget.remaining_seconds(path=led) == pytest.approx(seconds)


def resume(batch, led, first, service=None, **kw):
    service = service or FakeService(good_scripts(len(REMAINING), USED), id_prefix="resume")
    out = run_submit(batch, service, budget_path=led, args=("--resume",), clock=first.clock, **kw)
    return service, out


def plan_of(batch):
    return json.loads((batch / "plan.json").read_text())


# ---- (a) what goes out ---------------------------------------------------------------------------


def test_resume_sends_only_the_unjournaled_indices_in_plan_order(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    service, out = resume(batch, led, first)
    assert out.code == 0, out.stdout
    plan = plan_of(batch)["jobs"]
    assert service.submitted_hashes == [plan[i]["isa_sha256"] for i in REMAINING]
    assert service.submitted_configs == [plan[i]["config"] for i in REMAINING]
    assert set(raw_files(batch)) == set(range(N_PILOTS + N_REST)), "every job now has a raw file"


def test_resume_never_resubmits_a_journaled_index(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    journaled = {json.loads(line)["job_id"] for line in (batch / "submitted.jsonl").open()}
    assert len(journaled) == STOP_AT
    service, out = resume(batch, led, first)
    assert out.code == 0
    assert service.n_submitted == len(REMAINING)
    sent = {j.job_id() for j in service.jobs}
    assert not sent & journaled
    after = [json.loads(line) for line in (batch / "submitted.jsonl").open()]
    assert [e["index"] for e in after] == list(range(N_PILOTS + N_REST)), "one entry per index"
    assert len({e["job_id"] for e in after}) == len(after)


def test_resume_does_not_resubmit_a_journaled_job_that_has_no_raw_file_yet(tmp_path):
    """Journaled but unfinished (a crash before its raw file): resume finishes it by id, once."""
    batch, led, first = stopped_batch(tmp_path)
    lost = (batch / "jobs" / "3.json").read_bytes()
    (batch / "jobs" / "3.json").unlink()  # job 3 stays journaled and ledgered, raw file missing
    job3_id = json.loads(lost)["job_id"]
    n_ledger = len(ledger(led))
    service = FakeService(good_scripts(len(REMAINING), USED), id_prefix="resume")
    ibm_side = FakeService([], id_prefix="first")  # IBM still knows job 3
    service.known.append(
        FakeJob(ibm_side, 3, JobScript(counts=OK, usage=[USED], statuses_before_final=0))
    )
    _, out = resume(batch, led, first, service)
    assert out.code == 0, out.stdout
    plan = plan_of(batch)["jobs"]
    assert service.submitted_hashes == [plan[i]["isa_sha256"] for i in REMAINING]
    assert ("service.job", job3_id) in service.calls, "finished by id, not resubmitted"
    assert raw_files(batch)[3]["job_id"] == job3_id
    assert len([e for e in ledger(led) if e["job_id"] == job3_id]) == 1, "not ledgered twice"
    assert len(ledger(led)) == n_ledger + len(REMAINING)


def test_resume_does_not_send_an_index_that_already_has_a_raw_file(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    (batch / "jobs" / "11.json").write_text(json.dumps({"index": 11, "placed": "by hand"}))
    service, out = resume(batch, led, first, FakeService(good_scripts(7, USED), id_prefix="r"))
    plan = plan_of(batch)["jobs"]
    assert service.submitted_hashes == [plan[i]["isa_sha256"] for i in REMAINING if i != 11]
    assert read_json(batch / "jobs" / "11.json") == {"index": 11, "placed": "by hand"}, "immutable"


def test_resume_goes_through_one_service_with_no_wait_between_submits(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    service, out = resume(batch, led, first)
    assert out.code == 0
    assert out.factory_calls == 1, "one service, so the adapter opens ONE new Batch"
    assert service.closed
    assert "service.job" not in service.call_names(), "nothing journaled is left to reconcile"
    names = service.call_names()
    submits = [i for i, n in enumerate(names) if n == "service.submit"]
    assert len(submits) == len(REMAINING)
    first_poll = next(i for i, n in enumerate(names) if n in ("job.status", "job.usage"))
    assert max(submits) < first_poll, "every submit happens before anything is polled or awaited"
    # pilots are not run one at a time on resume: index 4 is a pilot and goes with the rest
    assert plan_of(batch)["jobs"][STOP_AT]["pilot"] is True


# ---- the real adapter: one Batch per service, a fresh one for a fresh service --------------------


class _Group(types.SimpleNamespace):
    pass


class _Options:
    def __getattr__(self, name):
        group = _Group()
        object.__setattr__(self, name, group)
        return group


def _patch_runtime(monkeypatch):
    events: list[tuple] = []

    class FakeBatch:
        count = 0

        def __init__(self, backend=None, **kw):
            type(self).count += 1
            self.n = type(self).count
            events.append(("batch.open", self.n))

        def close(self):
            events.append(("batch.close", self.n))

    class FakeSampler:
        def __init__(self, mode=None, **kw):
            self.mode, self.options = mode, _Options()

        def run(self, pubs, shots=None):
            events.append(("run", self.mode.n))
            return types.SimpleNamespace(job_id=lambda: f"j{len(events)}")

    monkeypatch.setattr(qiskit_ibm_runtime, "Batch", FakeBatch)
    monkeypatch.setattr(qiskit_ibm_runtime, "SamplerV2", FakeSampler)
    return events


def test_resume_adapter_opens_one_batch_for_all_submits_and_a_new_one_per_service(monkeypatch):
    events = _patch_runtime(monkeypatch)
    from tests.phase2.fakes import tiny_circuit

    first = RuntimeAdapter(types.SimpleNamespace(backend=lambda n: n))
    for i in range(5):
        first.submit("be", tiny_circuit(i), shots=4096, config="raw")
    first.close()
    second = RuntimeAdapter(types.SimpleNamespace(backend=lambda n: n))
    for i in range(3):
        second.submit("be", tiny_circuit(i), shots=4096, config="dd")
    second.close()
    assert [e for e in events if e[0].startswith("batch")] == [
        ("batch.open", 1), ("batch.close", 1), ("batch.open", 2), ("batch.close", 2),
    ]  # fmt: skip
    assert [e[1] for e in events if e[0] == "run"] == [1] * 5 + [2] * 3


# ---- (b) refusals: nothing is submitted ----------------------------------------------------------


def assert_nothing_happened(batch, led, service, out, before_batch, before_ledger):
    assert service.n_submitted == 0
    assert out.factory_calls == 0, "no service is built when a guard refuses"
    assert snapshot(batch) == before_batch, "a refused resume writes nothing"
    assert ledger(led) == before_ledger


def refused_resume(tmp_path, **run_kw):
    batch, led, first = stopped_batch(tmp_path)
    before_batch, before_ledger = snapshot(batch), ledger(led)
    service = FakeService(good_scripts(len(REMAINING)), id_prefix="resume")
    out = run_submit(
        batch, service, budget_path=led, args=("--resume",), clock=first.clock, **run_kw
    )
    return batch, led, service, out, before_batch, before_ledger


def test_approval_resume_refuses_without_a_tty(tmp_path):
    *state, out, b, ldg = refused_resume(tmp_path, tty=False)
    assert out.reason == "not_a_tty" and out.code == 2
    assert_nothing_happened(*state, out, b, ldg)
    assert out.stdin.reads == 0, "nothing is read from a non-interactive stdin"


@pytest.mark.parametrize("typed", ["", "deadbeef", "ABCDEF12", "0x123456", "   "])
def test_approval_resume_refuses_a_wrong_or_malformed_prefix(tmp_path, typed):
    *state, out, b, ldg = refused_resume(tmp_path, typed=typed)
    assert out.reason == "hash_mismatch" and out.code == 2
    assert_nothing_happened(*state, out, b, ldg)


def test_approval_resume_refuses_the_uppercase_form_of_the_right_prefix(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    before = snapshot(batch)
    service = FakeService(good_scripts(8), id_prefix="resume")
    out = run_submit(
        batch, service, budget_path=led, args=("--resume",), clock=first.clock,
        typed=plan_hash(batch)[:8].upper(),
    )  # fmt: skip
    assert out.reason == "hash_mismatch" and service.n_submitted == 0
    assert snapshot(batch) == before


def test_approval_resume_refuses_a_plan_changed_after_approval(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    (batch / "plan.json").write_text((batch / "plan.json").read_text() + "\n")  # one extra byte
    before_batch, before_ledger = snapshot(batch), ledger(led)
    service = FakeService(good_scripts(8), id_prefix="resume")
    out = run_submit(batch, service, budget_path=led, args=("--resume",), clock=first.clock)
    assert out.reason == "plan_changed" and out.code == 2
    assert_nothing_happened(batch, led, service, out, before_batch, before_ledger)


def test_approval_resume_refuses_when_there_is_no_approval_json(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    (batch / "approval.json").unlink()
    before_batch, before_ledger = snapshot(batch), ledger(led)
    service = FakeService(good_scripts(8), id_prefix="resume")
    out = run_submit(batch, service, budget_path=led, args=("--resume",), clock=first.clock)
    assert out.reason == "not_approved" and out.code == 2
    assert service.n_submitted == 0 and out.factory_calls == 0
    assert snapshot(batch) == before_batch and ledger(led) == before_ledger


def test_approval_resume_refuses_a_batch_that_never_stopped(tmp_path):
    batch = make_batch(tmp_path / "hw", specs())
    led = write_ledger(tmp_path / "budget.json")
    done = run_submit(batch, FakeService(good_scripts(N_PILOTS + N_REST, USED)), budget_path=led)
    assert done.code == 0 and not (batch / "stopped.json").exists()
    before_batch, before_ledger = snapshot(batch), ledger(led)
    service = FakeService(good_scripts(3), id_prefix="resume")
    out = run_submit(batch, service, budget_path=led, args=("--resume",), clock=done.clock)
    assert out.code == 8, "resume_not_applicable: there is no stop to resume from"
    assert_nothing_happened(batch, led, service, out, before_batch, before_ledger)


def test_approval_resume_refuses_a_batch_that_was_never_submitted(tmp_path):
    batch = make_batch(tmp_path / "hw", specs())
    led = write_ledger(tmp_path / "budget.json")
    before = snapshot(batch)
    service = FakeService(good_scripts(3))
    out = run_submit(batch, service, budget_path=led, args=("--resume",))
    assert out.reason == "not_approved" and out.code == 2
    assert service.n_submitted == 0 and out.factory_calls == 0
    assert snapshot(batch) == before and ledger(led) == []


def stop_with_code(tmp_path, code):
    """A stopped batch whose stopped.json carries ``code`` (3 overrun, 5 Open Plan, 7 usage)."""
    batch = make_batch(tmp_path / "hw", specs())
    led = write_ledger(tmp_path / "budget.json")
    if code == 3:  # a pilot used more than its estimate
        scripts = [JobScript(counts={"00": 4096}, usage=[EST + 5])]
    elif code == 5:  # error 4317
        scripts = [JobScript(submit_raises=IBMRuntimeError("4317 Open Plan usage limit exceeded"))]
    else:  # 7: DONE but usage never leaves 0
        scripts = [JobScript(counts={"00": 4096}, usage=[0.0])]
    first = run_submit(batch, FakeService(scripts, id_prefix="first"), budget_path=led)
    assert first.code == code, first.stdout
    return batch, led, first


@pytest.mark.parametrize("code", [3, 5, 7])
def test_approval_resume_refuses_after_overrun_open_plan_limit_or_unknown_usage(tmp_path, code):
    batch, led, first = stop_with_code(tmp_path, code)
    before_batch, before_ledger = snapshot(batch), ledger(led)
    service = FakeService(good_scripts(12), id_prefix="resume")
    out = run_submit(batch, service, budget_path=led, args=("--resume",), clock=first.clock)
    assert out.code == 8, "a stop that says 'the plan is wrong' or 'out of quota' is not resumable"
    assert_nothing_happened(batch, led, service, out, before_batch, before_ledger)
    assert not (batch / "resumes.jsonl").exists()


# ---- (c) budget ----------------------------------------------------------------------------------


def test_budget_resume_checks_the_sum_of_the_rest_once_before_any_submit(tmp_path, monkeypatch):
    batch, led, first = stopped_batch(tmp_path)
    service = FakeService(good_scripts(len(REMAINING), USED), id_prefix="resume")
    seen = []
    real = budget.check_job

    def spy(seconds, *a, **k):
        seen.append((seconds, service.n_submitted))
        return real(seconds, *a, **k)

    monkeypatch.setattr(budget, "check_job", spy)
    _, out = resume(batch, led, first, service)
    assert out.code == 0
    assert seen == [(pytest.approx(REMAINING_SUM), 0)], (
        "exactly one check, for the whole rest, before the first submit"
    )


def test_budget_resume_refuses_when_the_ledger_cannot_cover_the_rest(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    leave_remaining(led, REMAINING_SUM - 0.1)
    before_ledger = ledger(led)
    service = FakeService(good_scripts(len(REMAINING)), id_prefix="resume")
    out = run_submit(batch, service, budget_path=led, args=("--resume",), clock=first.clock)
    assert out.code == 4, out.stdout
    assert service.n_submitted == 0, "nothing is submitted when the rest does not fit"
    assert ledger(led) == before_ledger
    assert len(raw_files(batch)) == STOP_AT


def test_budget_resume_accepts_a_rest_that_exactly_fits(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    leave_remaining(led, REMAINING_SUM)
    _, out = resume(batch, led, first)
    assert out.code == 0, out.stdout


def test_budget_resume_ledgers_every_job_once_and_never_double_counts(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    service, out = resume(batch, led, first)
    assert out.code == 0
    entries = ledger(led)
    assert len(entries) == N_PILOTS + N_REST
    assert len({e["job_id"] for e in entries}) == len(entries)
    assert ledger_total(led) == pytest.approx((N_PILOTS + N_REST) * USED)
    assert {j.job_id() for j in service.jobs} <= {e["job_id"] for e in entries}


# ---- (d) the record of the resume ----------------------------------------------------------------


def test_approval_resume_appends_exactly_one_human_line_with_the_plan_hash_and_indices(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    stopped_before = (batch / "stopped.json").read_bytes()
    _, out = resume(batch, led, first)
    assert out.code == 0
    lines = (batch / "resumes.jsonl").read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["approved_by"] == "human"
    assert rec["plan_sha256"] == plan_hash(batch)
    assert rec["indices"] == REMAINING
    assert rec["after_stop"] == json.loads(stopped_before), "the stop it resumed from, verbatim"
    assert set(rec) >= {"resumed_at", "plan_sha256", "approved_by", "indices", "after_stop"}
    resumed_at = datetime.fromisoformat(rec["resumed_at"])
    approved_at = datetime.fromisoformat(read_json(batch / "approval.json")["approved_at"])
    assert resumed_at > approved_at
    raws = raw_files(batch)
    for i in REMAINING:
        assert datetime.fromisoformat(raws[i]["created"]) > resumed_at, f"job {i} before approval"


def test_immutable_resume_leaves_approval_stopped_and_earlier_raw_files_byte_identical(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    before = snapshot(batch)
    _, out = resume(batch, led, first)
    assert out.code == 0
    after = snapshot(batch)
    for name in ("approval.json", "stopped.json", "plan.json"):
        assert after[name] == before[name], name
    for i in range(STOP_AT):
        assert after[f"jobs/{i}.json"] == before[f"jobs/{i}.json"]
    assert not any(k.startswith("stopped-resume") for k in after), "a clean resume adds no stop"
    # the earlier journal lines are untouched, new ones are appended
    old = before["submitted.jsonl"]
    assert after["submitted.jsonl"].startswith(old)


def test_resume_line_is_written_before_the_first_submit(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    seen = []

    class Spy(FakeService):
        def submit(self, backend, isa, *, shots, config):
            path = batch / "resumes.jsonl"
            seen.append(path.exists() and len(path.read_text().splitlines()))
            return super().submit(backend, isa, shots=shots, config=config)

    _, out = resume(batch, led, first, Spy(good_scripts(len(REMAINING), USED), id_prefix="resume"))
    assert out.code == 0
    assert seen and all(n == 1 for n in seen), "approval is on file before any job is created"


# ---- (e) a failure during the resume ---------------------------------------------------------


def test_immutable_failed_resume_writes_stopped_resume_1_and_leaves_stopped_json_alone(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    stopped_before = (batch / "stopped.json").read_bytes()
    err = IBMRuntimeError("Failed to run program: 400 Client Error: 1217 Session has been closed")
    # first two resume jobs go out and stay pending; the third cannot be created
    scripts = [*late(2, usage=0.0), JobScript(submit_raises=err)]
    service = FakeService(scripts, id_prefix="resume")
    _, out = resume(batch, led, first, service)
    assert out.code == 6, out.stdout
    assert (batch / "stopped.json").read_bytes() == stopped_before
    stop = read_json(batch / "stopped-resume-1.json")
    assert stop["reason"] == "submit_failed" and stop["index"] == REMAINING[2]
    # the two in-flight jobs are cancelled, recorded, and ledgered like in a first run
    cancelled = {c[1] for c in service.calls if c[0] == "job.cancel"}
    assert {j.job_id() for j in service.jobs} <= cancelled
    raws = raw_files(batch)
    for i in REMAINING[:2]:
        assert raws[i]["status"] == "CANCELLED" and raws[i]["counts"] is None
    assert REMAINING[2] not in raws, "the job that was never created has no raw file"
    ids = {e["job_id"] for e in ledger(led)}
    assert {j.job_id() for j in service.jobs} <= ids
    lines = (batch / "resumes.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["indices"] == REMAINING


def test_budget_failed_resume_stops_on_an_overrun_and_ledgers_every_submitted_job(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    scripts = [
        JobScript(counts={"00": 4096}, usage=[USED]),
        JobScript(counts={"00": 4096}, usage=[EST + 6.0]),  # beats its estimate
        *late(len(REMAINING) - 2, usage=0.0),
    ]
    service = FakeService(scripts, id_prefix="resume")
    _, out = resume(batch, led, first, service)
    assert out.code == 3
    assert read_json(batch / "stopped-resume-1.json")["code"] == 3
    ids = {e["job_id"] for e in ledger(led)}
    assert {j.job_id() for j in service.jobs} <= ids, "all eight resumed jobs are in the ledger"
    assert service.n_submitted == len(REMAINING)
    assert (batch / "stopped.json").exists()


# ---- (f) the gate checks the resume record ----------------------------------------------------


@pytest.fixture
def gate_mod():
    from scripts import gate

    return gate


def gate_batch(tmp_path, lines, *, created=("2026-11-08T13:00:05+00:00",)):
    d = tmp_path / "hardware" / "b"
    (d / "jobs").mkdir(parents=True)
    (d / "plan.json").write_text('{"jobs": []}')
    for i, c in enumerate(created):
        (d / "jobs" / f"{i}.json").write_text(json.dumps({"index": i, "created": c}))
    if lines is not None:
        (d / "resumes.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    return d


GOOD = {
    "approved_by": "human", "plan_sha256": "H" * 64, "resumed_at": "2026-11-08T13:00:00+00:00",
    "indices": [0], "after_stop": {"reason": "submit_failed"},
}  # fmt: skip


def test_gate_resume_problems_none_for_a_good_resume_or_no_file(gate_mod, tmp_path):
    assert gate_mod._p2_resume_problems(gate_batch(tmp_path, [GOOD]), "H" * 64) == []
    other = tmp_path / "x"
    other.mkdir()
    assert gate_mod._p2_resume_problems(other, "H" * 64) == []


def test_gate_resume_problems_flag_a_non_human_approval(gate_mod, tmp_path):
    b = gate_batch(tmp_path, [{**GOOD, "approved_by": "claude"}])
    problems = gate_mod._p2_resume_problems(b, "H" * 64)
    assert len(problems) == 1 and "resume 0" in problems[0]


def test_gate_resume_problems_flag_a_wrong_plan_hash(gate_mod, tmp_path):
    b = gate_batch(tmp_path, [{**GOOD, "plan_sha256": "0" * 64}])
    assert len(gate_mod._p2_resume_problems(b, "H" * 64)) == 1


def test_gate_resume_problems_flag_a_job_created_before_the_resume(gate_mod, tmp_path):
    b = gate_batch(tmp_path, [GOOD], created=("2026-11-08T12:59:59+00:00",))
    problems = gate_mod._p2_resume_problems(b, "H" * 64)
    assert len(problems) == 1 and "created before" in problems[0]


def test_gate_resume_problems_treat_a_job_created_at_the_same_instant_as_early(gate_mod, tmp_path):
    b = gate_batch(tmp_path, [GOOD], created=("2026-11-08T13:00:00+00:00",))
    assert len(gate_mod._p2_resume_problems(b, "H" * 64)) == 1


def test_gate_resume_problems_ignore_jobs_the_resume_did_not_send(gate_mod, tmp_path):
    # job 1 is an old pilot (created long before the resume) but is not in `indices`
    b = gate_batch(
        tmp_path, [GOOD], created=("2026-11-08T13:00:05+00:00", "2026-11-08T07:00:00+00:00")
    )
    assert gate_mod._p2_resume_problems(b, "H" * 64) == []


def test_gate_resume_problems_report_only_the_bad_line_of_several(gate_mod, tmp_path):
    second = {**GOOD, "indices": [1], "resumed_at": "2026-11-08T14:00:00+00:00"}
    b = gate_batch(
        tmp_path,
        [GOOD, {**second, "approved_by": "bot"}],
        created=("2026-11-08T13:00:05+00:00", "2026-11-08T14:00:05+00:00"),
    )
    problems = gate_mod._p2_resume_problems(b, "H" * 64)
    assert len(problems) == 1 and "resume 1" in problems[0]


def test_gate_approval_check_fails_end_to_end_on_a_bad_resume_record(
    gate_mod, tmp_path, monkeypatch
):
    root = tmp_path / "hardware"
    monkeypatch.setattr(gate_mod, "P2_HW", root)
    b = gate_batch(tmp_path, [{**GOOD, "approved_by": "claude"}])
    digest = plan_hash(b)
    (b / "approval.json").write_text(
        json.dumps(
            {
                "approved_by": "human",
                "plan_sha256": digest,
                "approved_at": "2026-11-08T12:00:00+00:00",
            }
        )
    )
    (b / "resumes.jsonl").write_text(json.dumps({**GOOD, "plan_sha256": digest}) + "\n")
    ok, detail = gate_mod.p2_batches_approved()
    assert ok, detail
    (b / "resumes.jsonl").write_text(
        json.dumps({**GOOD, "plan_sha256": digest, "approved_by": "claude"}) + "\n"
    )
    ok, detail = gate_mod.p2_batches_approved()
    assert not ok and "resume 0" in detail
    _ = qpy_bytes  # keep the import used when the adapter test is skipped


# ---- more stop kinds and a second resume ------------------------------------------------------


def test_resume_after_a_job_that_ended_in_error_sends_only_the_never_submitted_jobs(tmp_path):
    """job_failed (code 6) is resumable; the failed job itself is journaled and is not retried."""
    batch = make_batch(tmp_path / "hw", specs())
    led = write_ledger(tmp_path / "budget.json")
    scripts = [
        *good_scripts(3, USED),
        JobScript(final_status="ERROR", error="boom", usage=[1.0]),  # pilot 3 fails
    ]
    first = run_submit(batch, FakeService(scripts, id_prefix="first"), budget_path=led)
    assert first.code == 6 and read_json(batch / "stopped.json")["reason"] == "job_failed"
    assert set(raw_files(batch)) == {0, 1, 2, 3}
    service, out = resume(batch, led, first, FakeService(good_scripts(8, USED), id_prefix="r"))
    assert out.code == 0, out.stdout
    plan = plan_of(batch)["jobs"]
    assert service.submitted_hashes == [plan[i]["isa_sha256"] for i in range(4, 12)]
    assert raw_files(batch)[3]["status"] == "ERROR", "the failed job's raw file is untouched"


def test_budget_resume_that_does_not_fit_leaves_a_budget_stop_file_and_a_resume_line(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    leave_remaining(led, REMAINING_SUM - 0.1)
    service = FakeService(good_scripts(len(REMAINING)), id_prefix="resume")
    out = run_submit(batch, service, budget_path=led, args=("--resume",), clock=first.clock)
    assert out.code == 4 and service.n_submitted == 0
    stop = read_json(batch / "stopped-resume-1.json")
    assert stop["code"] == 4 and stop["reason"] == "budget"
    assert len((batch / "resumes.jsonl").read_text().splitlines()) == 1, "the approval is on file"


def test_resume_twice_is_allowed_only_from_a_resumable_latest_stop(tmp_path):
    batch, led, first = stopped_batch(tmp_path)
    err = IBMRuntimeError("Failed to run program: 400 Client Error: 1217 Session has been closed")
    scripts = [JobScript(counts=OK, usage=[USED]), JobScript(submit_raises=err)]
    _, one = resume(batch, led, first, FakeService(scripts, id_prefix="r1"))
    assert one.code == 6 and (batch / "stopped-resume-1.json").exists()
    # second resume continues from the latest stop and sends only what is still missing
    done = set(raw_files(batch))
    todo = [i for i in range(N_PILOTS + N_REST) if i not in done]
    service = FakeService(good_scripts(len(todo), USED), id_prefix="r2")
    out = run_submit(batch, service, budget_path=led, args=("--resume",), clock=one.clock)
    assert out.code == 0, out.stdout
    plan = plan_of(batch)["jobs"]
    assert service.submitted_hashes == [plan[i]["isa_sha256"] for i in todo]
    lines = [json.loads(x) for x in (batch / "resumes.jsonl").read_text().splitlines()]
    assert [r["indices"] for r in lines] == [REMAINING, todo]
    assert lines[1]["after_stop"]["index"] == REMAINING[1]
    # the batch is finished: a third resume has nothing to resume from
    nothing = FakeService(good_scripts(3), id_prefix="r3")
    again = run_submit(batch, nothing, budget_path=led, args=("--resume",), clock=out.clock)
    assert again.code == 8 and nothing.n_submitted == 0 and again.factory_calls == 0
    assert len(ledger(led)) == N_PILOTS + N_REST and len({e["job_id"] for e in ledger(led)}) == 12


def test_immutable_resume_refuses_a_circuit_file_that_no_longer_matches_the_plan(tmp_path):
    """A swapped .qpy must stop the resume before any job is created (nothing queued, then lost)."""
    batch, led, first = stopped_batch(tmp_path)
    (batch / "circuits" / "7.qpy").write_bytes(b"not the planned circuit")
    before, before_ledger = snapshot(batch), ledger(led)
    service = FakeService(good_scripts(len(REMAINING)), id_prefix="resume")
    out = run_submit(batch, service, budget_path=led, args=("--resume",), clock=first.clock)
    assert out.code == 9 and service.n_submitted == 0
    assert snapshot(batch) == before and ledger(led) == before_ledger
    assert not (batch / "resumes.jsonl").exists(), "no approval line for a resume that never ran"


def test_resume_whose_reconcile_sees_usage_still_zero_stops_with_code_7_and_cannot_resume_again(
    tmp_path,
):
    batch, led, first = stopped_batch(tmp_path)
    (batch / "jobs" / "3.json").unlink()  # journaled, raw file missing: reconcile finishes it
    ibm_side = FakeService([], id_prefix="first")
    service = FakeService(good_scripts(len(REMAINING), USED), id_prefix="resume")
    service.known.append(
        FakeJob(ibm_side, 3, JobScript(counts=OK, usage=[0.0], statuses_before_final=0))
    )
    _, out = resume(batch, led, first, service)
    assert out.code == 7, out.stdout
    assert service.n_submitted == 0, "nothing is sent while a journaled job's usage is unknown"
    stop = read_json(batch / "stopped-resume-1.json")
    assert stop["reason"] == "usage_unknown" and stop["code"] == 7
    assert len((batch / "resumes.jsonl").read_text().splitlines()) == 1
    # a further resume is refused: the latest stop is not resumable
    again = FakeService(good_scripts(len(REMAINING)), id_prefix="again")
    out2 = run_submit(batch, again, budget_path=led, args=("--resume",), clock=out.clock)
    assert out2.code == 8 and again.n_submitted == 0 and out2.factory_calls == 0
