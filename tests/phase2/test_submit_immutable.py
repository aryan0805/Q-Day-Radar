"""Raw hardware files are write-once (names contain `immutable`: the gate runs them).

A rerun after a stop or a crash must refuse BEFORE submitting anything: with "open x after
submit" a rerun would spend QPU seconds first and only then fail to write.
"""

import inspect
import json

import pytest

pytest.importorskip("scripts.submit_hardware")
from scripts import submit_hardware  # noqa: E402
from tests.phase2.fakes import FakeService, JobScript, JobSpec, make_batch  # noqa: E402
from tests.phase2.harness import (  # noqa: E402
    good_scripts,
    ledger,
    raw_files,
    run_submit,
    snapshot,
    write_ledger,
)

SENTINEL = '{"planted": "must survive"}\n'


@pytest.fixture
def env(tmp_path):
    specs = [
        JobSpec("grover_present_k2", "raw", 3.0, pilot=True),
        JobSpec("grover_present_k2", "m3_cal", 3.0, pilot=True),
        JobSpec("grover_present_k3", "raw", 3.0),
    ]
    batch = make_batch(tmp_path / "hw", specs)
    return batch, write_ledger(tmp_path / "budget.json"), len(specs)


def test_immutable_rerun_after_a_complete_batch_changes_nothing_and_submits_nothing(env):
    batch, led, n = env
    assert run_submit(batch, FakeService(good_scripts(n)), budget_path=led).code == 0
    files, entries = snapshot(batch), ledger(led)
    fresh = FakeService(good_scripts(n))
    again = run_submit(batch, fresh, budget_path=led)
    assert again.code == 8 and again.factory_calls == 0
    assert fresh.calls == []
    assert snapshot(batch) == files, "no raw file, journal or approval may change"
    assert ledger(led) == entries


def test_immutable_existing_raw_file_blocks_the_run_before_any_submit(env):
    batch, led, n = env
    (batch / "jobs").mkdir()
    (batch / "jobs" / "0.json").write_text(SENTINEL)
    before = snapshot(batch)
    service = FakeService(good_scripts(n))
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 8 and out.factory_calls == 0 and service.calls == []
    assert snapshot(batch) == before
    assert not (batch / "approval.json").exists(), "a refused resume must not approve anything"
    assert ledger(led) == []


def test_immutable_stopped_batch_cannot_be_resumed(env):
    batch, led, n = env
    (batch / "stopped.json").write_text(json.dumps({"reason": "x", "index": 0, "message": "m"}))
    service = FakeService(good_scripts(n))
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 8 and service.calls == []


def test_immutable_journal_with_a_job_blocks_a_second_submission_run(env):
    batch, led, n = env
    (batch / "submitted.jsonl").write_text(json.dumps({"index": 0, "job_id": "j0"}) + "\n")
    service = FakeService(good_scripts(n))
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 8 and service.calls == []


def test_immutable_a_stopped_run_leaves_a_batch_that_cannot_be_rerun(env):
    batch, led, n = env
    scripts = good_scripts(n)
    scripts[0] = JobScript(counts={"00": 4096}, usage=[9.0])  # pilot overrun -> exit 3
    first = run_submit(batch, FakeService(scripts), budget_path=led)
    assert first.code == 3
    files = snapshot(batch)
    fresh = FakeService(good_scripts(n))
    assert run_submit(batch, fresh, budget_path=led).code == 8
    assert fresh.calls == [] and snapshot(batch) == files


def test_immutable_raw_file_planted_during_the_run_is_never_overwritten(env):
    batch, led, n = env

    def plant():
        (batch / "jobs").mkdir(exist_ok=True)
        (batch / "jobs" / "1.json").write_text(SENTINEL)

    scripts = [
        JobScript(counts={"00": 4096}, usage=[1.0], on_usage_final=plant),
        *good_scripts(n - 1),
    ]
    service = FakeService(scripts)
    try:
        out = run_submit(batch, service, budget_path=led)
        assert out.code != 0, "writing over an existing raw file must not look like success"
    except FileExistsError:
        pass
    assert (batch / "jobs" / "1.json").read_text() == SENTINEL
    ids = {e["job_id"] for e in ledger(led)}
    # a job that ran must be ledgered even if its raw file could not be written
    assert {j.job_id() for j in service.jobs} <= ids


def test_immutable_raw_files_are_opened_with_exclusive_create():
    src = inspect.getsource(submit_hardware)
    assert '"x"' in src or "'x'" in src or "O_EXCL" in src, "raw files need write-once creation"
    assert "unlink(" not in src and "os.remove(" not in src and "rmtree(" not in src


def test_immutable_run_writes_one_raw_file_per_job_with_the_agreed_fields(env):
    batch, led, n = env
    assert run_submit(batch, FakeService(good_scripts(n)), budget_path=led).code == 0
    raws = raw_files(batch)
    assert sorted(raws) == list(range(n))
    plan = json.loads((batch / "plan.json").read_text())
    for i, raw in raws.items():
        assert {
            "index", "job_id", "backend", "name", "config", "isa_sha256", "shots", "counts",
            "usage_seconds", "created", "finished", "status", "error", "usage_unknown",
        } <= set(raw)  # fmt: skip
        job = plan["jobs"][i]
        assert (raw["name"], raw["config"], raw["shots"]) == (
            job["name"], job["config"], job["shots"],
        )  # fmt: skip
        assert raw["isa_sha256"] == job["isa_sha256"]
        assert raw["status"] == "DONE" and raw["error"] is None and raw["usage_unknown"] is False
        assert sum(raw["counts"].values()) == 4096
        assert raw["created"] <= raw["finished"]
    journal = [json.loads(line) for line in (batch / "submitted.jsonl").read_text().splitlines()]
    assert [j["index"] for j in journal] == list(range(n))
    assert {"index", "job_id", "name", "config", "estimated_seconds", "created"} <= set(journal[0])
    assert [j["job_id"] for j in journal] == [raws[i]["job_id"] for i in range(n)]
