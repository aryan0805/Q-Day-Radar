"""Approval guards of scripts/submit_hardware.py (names contain `approval`: the gate runs them).

The human types the first 8 hex characters of sha256(plan.json) at a TTY. Every refusal must
happen BEFORE anything is written and before the service factory is called.
"""

import json
from datetime import datetime

import pytest

pytest.importorskip("scripts.submit_hardware")

from tests.phase2.fakes import FakeService, JobSpec, make_batch, plan_hash, sha  # noqa: E402
from tests.phase2.harness import (  # noqa: E402
    good_scripts,
    ledger,
    raw_files,
    read_json,
    run_submit,
    snapshot,
    write_ledger,
)


@pytest.fixture
def env(tmp_path):
    specs = [
        JobSpec("grover_present_k2", "raw", 2.0, pilot=True),
        JobSpec("grover_present_k2", "m3_cal", 2.0, pilot=True),
        JobSpec("grover_present_k3", "raw", 3.0),
        JobSpec("grover_present_k3", "dd", 3.0),
    ]
    batch = make_batch(tmp_path / "hw", specs)
    return batch, write_ledger(tmp_path / "budget.json"), FakeService(good_scripts(len(specs)))


def _untouched(batch, before, service, out, ledger_path):
    assert snapshot(batch) == before, "a refusal must not write or change anything"
    assert out.factory_calls == 0, "the service factory must not be called before approval"
    assert service.calls == []
    assert ledger(ledger_path) == []
    assert not (batch / "approval.json").exists()


# ---- refusals ---------------------------------------------------------------------------


def test_approval_refuses_when_stdin_is_not_a_tty(env):
    batch, led, service = env
    before = snapshot(batch)
    out = run_submit(batch, service, budget_path=led, tty=False)
    assert out.code == 2 and out.reason == "not_a_tty"
    assert out.stdin.reads == 0, "must not even read a prompt answer without a TTY"
    _untouched(batch, before, service, out, led)


def test_approval_refuses_a_piped_correct_hash_too(env):
    # a script that pipes the right prefix is exactly what the TTY rule exists to stop
    batch, led, service = env
    out = run_submit(batch, service, budget_path=led, tty=False, typed=plan_hash(batch)[:8])
    assert out.code == 2 and out.reason == "not_a_tty"
    assert service.n_submitted == 0


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(lambda h: "", id="empty"),
        pytest.param(lambda h: h[:7], id="seven-chars"),
        pytest.param(lambda h: h[:4], id="four-chars"),
        pytest.param(lambda h: h[:9], id="nine-chars-correct-prefix"),
        pytest.param(lambda h: h, id="full-64-char-hash"),
        pytest.param(lambda h: h[:8].upper(), id="uppercase"),
        pytest.param(lambda h: "0" * 8 if h[:8] != "0" * 8 else "1" * 8, id="wrong-8-chars"),
        pytest.param(lambda h: h[:7] + ("0" if h[7] != "0" else "1"), id="one-char-off"),
        pytest.param(lambda h: "yes", id="yes"),
        pytest.param(lambda h: "y", id="y"),
        pytest.param(lambda h: "approve", id="approve"),
    ],
)
def test_approval_refuses_wrong_or_malformed_hash_prefix(env, bad):
    batch, led, service = env
    typed = bad(plan_hash(batch))
    before = snapshot(batch)
    out = run_submit(batch, service, budget_path=led, typed=typed)
    assert out.code == 2 and out.reason == "hash_mismatch"
    _untouched(batch, before, service, out, led)


def test_approval_ignores_surrounding_whitespace_but_nothing_else(env):
    batch, led, service = env
    out = run_submit(batch, service, budget_path=led, typed=f"  {plan_hash(batch)[:8]}  ")
    assert out.code == 0 and out.reason is None


def test_approval_refuses_when_plan_changed_after_a_previous_approval(env):
    batch, led, service = env
    stale = {
        "batch_id": "test-batch",
        "plan_sha256": plan_hash(batch),
        "approved_at": "2026-11-08T11:30:00+00:00",
        "approved_by": "human",
    }
    (batch / "approval.json").write_text(json.dumps(stale, indent=2))
    plan = json.loads((batch / "plan.json").read_text())
    plan["jobs"][2]["estimated_seconds"] = 0.1  # someone edits the plan after it was approved
    (batch / "plan.json").write_text(json.dumps(plan, indent=2))
    before = snapshot(batch)
    # even typing the NEW correct prefix must not re-approve silently
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 2 and out.reason == "plan_changed"
    assert snapshot(batch) == before and out.factory_calls == 0 and service.calls == []
    assert json.loads((batch / "approval.json").read_text()) == stale


def test_approval_edited_plan_is_refused_with_the_old_prefix(env):
    batch, led, service = env
    old_prefix = plan_hash(batch)[:8]
    plan = json.loads((batch / "plan.json").read_text())
    plan["jobs"][0]["shots"] = 8192
    (batch / "plan.json").write_text(json.dumps(plan, indent=2))
    out = run_submit(batch, service, budget_path=led, typed=old_prefix)
    assert out.code == 2 and out.reason == "hash_mismatch"
    assert service.calls == [] and not (batch / "approval.json").exists()


def test_approval_refuses_a_tampered_circuit_before_it_is_submitted(env):
    batch, led, service = env
    planned = [j["isa_sha256"] for j in json.loads((batch / "plan.json").read_text())["jobs"]]
    (batch / "circuits" / "2.qpy").write_bytes(b"not the circuit that was planned")
    out = run_submit(batch, service, budget_path=led)
    assert out.code != 0
    assert all(h in planned for h in service.submitted_hashes)
    assert planned[2] not in service.submitted_hashes
    assert service.n_submitted <= 2, "the tampered job and everything after it must not run"


# ---- what a successful approval writes -----------------------------------------------------


def test_approval_file_records_hash_time_and_human(env):
    batch, led, service = env
    out = run_submit(batch, service, budget_path=led)
    assert out.code == 0
    approval = read_json(batch / "approval.json")
    assert approval["batch_id"] == "test-batch"
    assert approval["approved_by"] == "human"
    assert approval["plan_sha256"] == sha((batch / "plan.json").read_bytes())
    stamp = datetime.fromisoformat(approval["approved_at"])
    assert stamp.tzinfo is not None


def test_approval_comes_before_every_job_created(env):
    batch, led, service = env
    run_submit(batch, service, budget_path=led)
    approved = datetime.fromisoformat(read_json(batch / "approval.json")["approved_at"])
    raws = raw_files(batch)
    assert len(raws) == 4
    for i, raw in raws.items():
        assert datetime.fromisoformat(raw["created"]) > approved, f"job {i}"


def test_approval_prompt_tells_the_human_what_they_are_approving(env):
    batch, led, service = env
    out = run_submit(batch, service, budget_path=led)
    plan = json.loads((batch / "plan.json").read_text())
    text = out.stdout
    assert plan_hash(batch)[:8] in text
    assert str(len(plan["jobs"])) in text
    total = plan["total_estimated_seconds"]
    assert f"{total:g}" in text or str(total) in text
    assert plan["backend"] in text


def test_approval_factory_is_called_once_and_only_after_all_guards(env):
    batch, led, service = env
    out = run_submit(batch, service, budget_path=led)
    assert out.factory_calls == 1 and service.closed


def test_approval_submitted_circuits_are_exactly_the_planned_isa_in_plan_order(env):
    batch, led, service = env
    run_submit(batch, service, budget_path=led)
    plan = json.loads((batch / "plan.json").read_text())
    assert service.submitted_hashes == [j["isa_sha256"] for j in plan["jobs"]]
    assert service.submitted_configs == [j["config"] for j in plan["jobs"]]
    for i, raw in raw_files(batch).items():
        assert raw["isa_sha256"] == plan["jobs"][i]["isa_sha256"]


def test_approval_second_run_after_approval_does_not_reapprove_or_resubmit(env):
    batch, led, service = env
    run_submit(batch, service, budget_path=led)
    first = (batch / "approval.json").read_bytes()
    again = run_submit(batch, FakeService(good_scripts(4)), budget_path=led)
    assert again.code == 8
    assert (batch / "approval.json").read_bytes() == first
