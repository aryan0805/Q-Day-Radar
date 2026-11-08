"""Submit an approved plan to IBM hardware. THE HUMAN RUNS THIS; no Claude session ever does.

    uv run python scripts/submit_hardware.py results/hardware/<batch_id>
    uv run python scripts/submit_hardware.py results/hardware/<batch_id> --reconcile
    uv run python scripts/submit_hardware.py results/hardware/<batch_id> --resume

Guards, in order, before anything is written or any service is built:
  (a) stdin must be an interactive TTY; (b) the human must type the first 8 characters
  (lowercase hex) of sha256(plan.json); (c) an existing approval.json must match plan.json.
Then: refuse to resume a batch that already submitted anything (exit 8), check the ledger covers
the whole plan (exit 4), run one pilot per config family (raw, dd, dd_twirl, m3_cal) one at a
time, and submit the rest together in the same batch.

Exit codes: 0 ok, 2 approval refused, 3 a job used more than its estimate, 4 budget,
5 Open Plan limit (error 4317), 6 a job ended ERROR/CANCELLED, 7 usage still 0 after retries,
8 resume refused, 9 ISA circuit does not match the plan hash.
Every submitted job is journaled (submitted.jsonl) the moment it is submitted, written to a
write-once raw file once its usage is final, and ledgered with ``enforce=False`` (actual spend
always reaches the ledger).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qiskit_ibm_runtime.exceptions import IBMError  # noqa: E402

from quantum.run import budget  # noqa: E402
from quantum.run.hardware import (  # noqa: E402
    TERMINAL_STATES,
    ApprovalRefused,
    default_service_factory,
    load_qpy,
    sha256_hex,
)

PREFIX_RE = re.compile(r"[0-9a-f]{8}")
NON_DONE_USAGE_POLLS = 3  # ERROR/CANCELLED may legitimately report 0 (system error, not started)

__all__ = ["ApprovalRefused", "main"]


class _Stop(Exception):
    def __init__(self, code: int, reason: str, message: str, index: int | None = None):
        super().__init__(message)
        self.code, self.reason, self.message, self.index = code, reason, message, index


class _Handle:
    def __init__(self, spec: dict[str, Any], job: Any, created: str):
        self.spec, self.job, self.created = spec, job, created
        self.done = False


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    """Exclusive create: an existing raw file means refuse, never overwrite."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x") as fh:
        fh.write(json.dumps(payload, indent=2) + "\n")


def _journal(batch_dir: Path) -> list[dict[str, Any]]:
    path = batch_dir / "submitted.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _is_4317(text: str | None) -> bool:
    return bool(text) and "4317" in str(text)


class _Runner:
    def __init__(
        self,
        batch_dir: Path,
        plan: dict[str, Any],
        service: Any,
        budget_path: Path,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
        max_usage_polls: int,
        poll_seconds: float,
        out: TextIO,
    ):
        self.batch_dir, self.plan, self.service = batch_dir, plan, service
        self.budget_path, self.clock, self.sleep = budget_path, clock, sleep
        self.max_usage_polls, self.poll_seconds, self.out = max_usage_polls, poll_seconds, out
        self.backend = service.backend(plan["backend"])
        self.handles: list[_Handle] = []
        self.pending_failure: _Stop | None = None

    # -- submit -------------------------------------------------------------------------
    def submit(self, spec: dict[str, Any]) -> _Handle:
        data = (self.batch_dir / "circuits" / f"{spec['index']}.qpy").read_bytes()
        if sha256_hex(data) != spec["isa_sha256"]:
            raise _Stop(
                9, "isa_mismatch", f"job {spec['index']}: circuit != isa_sha256", spec["index"]
            )
        try:
            job = self.service.submit(
                self.backend, load_qpy(data), shots=spec["shots"], config=spec["config"]
            )
        except IBMError as exc:
            code = 5 if _is_4317(str(exc)) else 6
            raise _Stop(code, "submit_failed", str(exc), spec["index"]) from exc
        created = self.clock().isoformat()
        entry = {
            "index": spec["index"],
            "job_id": job.job_id(),
            "name": spec["name"],
            "config": spec["config"],
            "estimated_seconds": spec["estimated_seconds"],
            "created": created,
        }
        with open(self.batch_dir / "submitted.jsonl", "a") as fh:
            fh.write(json.dumps(entry) + "\n")
        handle = _Handle(spec, job, created)
        self.handles.append(handle)
        self.out.write(f"submitted job {spec['index']} ({spec['name']}/{spec['config']})\n")
        return handle

    # -- finish: usage poll, raw file, ledger -------------------------------------------
    def finish(self, handle: _Handle) -> _Stop | None:
        spec, job = handle.spec, handle.job
        status = job.status()
        polls = (
            self.max_usage_polls
            if status == "DONE"
            else min(self.max_usage_polls, NON_DONE_USAGE_POLLS)
        )
        usage = 0.0
        for attempt in range(polls):
            usage = float(job.usage())
            if usage > 0:
                break
            if attempt < polls - 1:
                self.sleep(self.poll_seconds)
        unknown = status == "DONE" and usage <= 0
        counts: dict[str, int] | None = None
        error: str | None = None
        if status == "DONE":
            try:
                counts = job.counts()
            except IBMError as exc:
                status, error = "ERROR", str(exc)
        else:
            error = job.error_message() or status
        record = {
            "index": spec["index"],
            "job_id": job.job_id(),
            "backend": self.plan["backend"],
            "name": spec["name"],
            "config": spec["config"],
            "isa_sha256": spec["isa_sha256"],
            "shots": spec["shots"],
            "counts": counts,
            "usage_seconds": None if unknown else usage,
            "created": handle.created,
            "finished": self.clock().isoformat(),
            "status": status,
            "error": error,
            "usage_unknown": unknown,
        }
        label = f"{self.plan['batch_id']}:{spec['index']}:{spec['name']}:{spec['config']}"
        seconds = spec["estimated_seconds"] if unknown else usage
        if unknown:
            label = f"usage_unknown:{label}"
        # Ledger FIRST: a job that ran must be recorded even if the raw write then fails.
        # Skip when this job_id is already in the ledger (reconcile after a partial finish).
        ledgered = {e["job_id"] for e in budget.load_budget(self.budget_path)["entries"]}
        if job.job_id() not in ledgered:
            budget.record_job(
                job.job_id(),
                seconds,
                self.plan["backend"],
                label,
                path=self.budget_path,
                now=self.clock(),
                enforce=False,
            )
        handle.done = True
        try:
            _write_new(self.batch_dir / "jobs" / f"{spec['index']}.json", record)
        except OSError as exc:  # FileExistsError (write-once), disk full, permissions
            return _Stop(6, "raw_write_failed", f"job {spec['index']}: {exc}", spec["index"])
        if unknown:
            return _Stop(7, "usage_unknown", f"job {spec['index']}: usage still 0", spec["index"])
        if status != "DONE":
            code = 5 if _is_4317(error) else 6
            return _Stop(
                code, "job_failed", f"job {spec['index']} {status}: {error}", spec["index"]
            )
        if usage > spec["estimated_seconds"]:
            return _Stop(
                3,
                "overrun",
                f"job {spec['index']} used {usage:.2f} s > estimate {spec['estimated_seconds']} s",
                spec["index"],
            )
        return None

    # -- waiting ------------------------------------------------------------------------
    def wait_all(self, handles: list[_Handle]) -> _Stop | None:
        """Poll until every handle is finished; on the first failure cancel the rest."""
        stop: _Stop | None = None
        while not all(h.done for h in handles):
            progressed = False
            for h in handles:
                if h.done:
                    continue
                if h.job.status() in TERMINAL_STATES:
                    progressed = True
                    result = self.finish(h)
                    if result and stop is None:
                        stop = result
                        self.cancel_unfinished(handles)
            if not progressed:
                self.sleep(self.poll_seconds)
        return stop

    def cancel_unfinished(self, handles: list[_Handle]) -> None:
        for h in handles:
            if not h.done and h.job.status() not in TERMINAL_STATES:
                h.job.cancel()

    def run_one(self, spec: dict[str, Any]) -> _Stop | None:
        budget.check_job(spec["estimated_seconds"], self.budget_path, self.clock())
        return self.wait_all([self.submit(spec)])


def _stop_file(batch_dir: Path, stop: _Stop, out: TextIO, name: str = "stopped.json") -> int:
    (batch_dir / name).write_text(
        json.dumps(
            {
                "reason": stop.reason,
                "index": stop.index,
                "message": stop.message,
                "code": stop.code,
            },
            indent=2,
        )
        + "\n"
    )
    out.write(f"STOPPED ({stop.reason}): {stop.message}\n")
    return stop.code


def _execute(runner: _Runner, plan: dict[str, Any]) -> _Stop | None:
    pilots = [j for j in plan["jobs"] if j.get("pilot")]
    rest = [j for j in plan["jobs"] if not j.get("pilot")]
    for spec in pilots:  # one at a time; each must come in at or under its estimate
        stop = runner.run_one(spec)
        if stop:
            return stop
    if rest:
        total = sum(j["estimated_seconds"] for j in rest)
        budget.check_job(total, runner.budget_path, runner.clock())
        return _submit_all(runner, rest)
    return None


def _submit_all(runner: _Runner, specs: list[dict[str, Any]]) -> _Stop | None:
    """Submit every spec back to back (journaled at submit time), then wait for all of them."""
    handles: list[_Handle] = []
    for spec in specs:
        try:
            handles.append(runner.submit(spec))
        except _Stop as stop:
            runner.cancel_unfinished(handles)
            runner.wait_all(handles)
            return stop
    return runner.wait_all(handles)


def _reconcile(runner: _Runner, batch_dir: Path) -> int:
    code = 0
    for entry in _journal(batch_dir):
        if (batch_dir / "jobs" / f"{entry['index']}.json").exists():
            continue
        spec = next(j for j in runner.plan["jobs"] if j["index"] == entry["index"])
        handle = _Handle(spec, runner.service.job(entry["job_id"]), entry["created"])
        while handle.job.status() not in TERMINAL_STATES:
            runner.sleep(runner.poll_seconds)
        stop = runner.finish(handle)
        if stop and stop.code == 7:
            code = 7
    return code


def _resume_batch(
    batch_dir: Path,
    plan: dict[str, Any],
    plan_sha: str,
    *,
    stdin: TextIO,
    out: TextIO,
    factory: Callable[[], Any],
    budget_path: Path,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
    max_usage_polls: int,
    poll_seconds: float,
) -> int:
    """Resume a batch that stopped on a submit/job failure: one NEW Batch, every job that was
    never submitted goes out back to back, the human re-types the same hash prefix."""
    approval_path = batch_dir / "approval.json"
    if not approval_path.exists():
        raise ApprovalRefused("not_approved", "no approval.json: nothing to resume")
    if json.loads(approval_path.read_text())["plan_sha256"] != plan_sha:
        raise ApprovalRefused("plan_changed", "approval.json does not match plan.json")
    # the stop that counts is the latest one: stopped.json, or stopped-resume-<n>.json of the
    # latest resume n (1-based line number in resumes.jsonl)
    resumes_path = batch_dir / "resumes.jsonl"
    n_resumes = len(resumes_path.read_text().splitlines()) if resumes_path.exists() else 0
    stopped_path = batch_dir / (f"stopped-resume-{n_resumes}.json" if n_resumes else "stopped.json")
    if not stopped_path.exists():
        out.write(f"REFUSED (resume_not_applicable): no {stopped_path.name}; nothing to resume.\n")
        return 8
    stopped = json.loads(stopped_path.read_text())
    if stopped.get("reason") not in ("submit_failed", "job_failed") or stopped.get("code") != 6:
        out.write(
            f"REFUSED (resume_not_applicable): stopped for {stopped.get('reason')!r} "
            f"(code {stopped.get('code')}); only submit_failed/job_failed (code 6) may resume.\n"
        )
        return 8
    if not stdin.isatty():
        raise ApprovalRefused("not_a_tty", "stdin is not an interactive terminal")

    journaled = {e["index"] for e in _journal(batch_dir)}
    jobs_dir = batch_dir / "jobs"
    have_raw = {int(p.stem) for p in jobs_dir.glob("*.json")} if jobs_dir.exists() else set()
    indices = [j["index"] for j in plan["jobs"] if j["index"] not in journaled | have_raw]
    if not indices:
        out.write("nothing to resume: every planned job is already journaled.\n")
        return 0
    specs = [j for j in plan["jobs"] if j["index"] in set(indices)]
    for spec in specs:  # verify every circuit BEFORE the prompt: nothing queued, then cancelled
        qpy_path = batch_dir / "circuits" / f"{spec['index']}.qpy"
        if not qpy_path.exists() or sha256_hex(qpy_path.read_bytes()) != spec["isa_sha256"]:
            out.write(
                f"REFUSED (isa_mismatch): circuits/{spec['index']}.qpy is missing or does not "
                "match the planned isa_sha256; nothing submitted.\n"
            )
            return 9
    estimate = round(sum(j["estimated_seconds"] for j in specs), 1)
    used = budget.used_seconds(path=budget_path, now=clock())
    left = budget.remaining_seconds(path=budget_path, now=clock())
    out.write(
        f"RESUME batch {plan['batch_id']} on {plan['backend']} after stop "
        f"{stopped.get('reason')} at index {stopped.get('index')}.\n"
        f"Jobs to submit ({len(indices)}): {indices}\n"
        f"Estimated {estimate} s; ledger used {used:.1f} s, remaining {left:.1f} s.\n"
        f"Plan hash: {plan_sha}\n"
        "Type the first 8 characters of the plan hash to resume: "
    )
    out.flush()
    typed = stdin.readline().strip()
    if not PREFIX_RE.fullmatch(typed) or typed != plan_sha[:8]:
        raise ApprovalRefused("hash_mismatch", "typed prefix does not match the plan hash")

    with open(resumes_path, "a") as fh:
        fh.write(
            json.dumps(
                {
                    "resumed_at": clock().isoformat(),
                    "plan_sha256": plan_sha,
                    "approved_by": "human",
                    "indices": indices,
                    "after_stop": {
                        k: stopped.get(k) for k in ("reason", "index", "code", "message")
                    },
                }
            )
            + "\n"
        )
    k = len(resumes_path.read_text().splitlines())

    runner = _Runner(
        batch_dir, plan, factory(), budget_path, clock, sleep, max_usage_polls, poll_seconds, out
    )
    stop: _Stop | None = None
    try:
        code = _reconcile(runner, batch_dir)  # every journaled job gets its raw file first
        if code:
            return _stop_file(
                batch_dir,
                _Stop(code, "usage_unknown", "reconcile: a journaled job's usage is still 0"),
                out,
                name=f"stopped-resume-{k}.json",
            )
        try:
            budget.check_job(estimate, budget_path, clock())
            stop = _submit_all(runner, specs)
        except _Stop as exc:
            stop = exc
        except budget.BudgetExceeded as exc:
            stop = _Stop(4, "budget", str(exc))
        if stop and stop.code != 4:
            runner.cancel_unfinished(runner.handles)
            runner.wait_all([h for h in runner.handles if not h.done])
    finally:
        runner.service.close()
    if stop:
        return _stop_file(batch_dir, stop, out, name=f"stopped-resume-{k}.json")
    out.write("all resumed jobs finished\n")
    return 0


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    service_factory: Callable[[], Any] | None = None,
    budget_path: Path = budget.DEFAULT_PATH,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_usage_polls: int = 10,
    poll_seconds: float = 30.0,
) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("batch_dir", type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--reconcile", action="store_true", help="finish journaled jobs; never submits"
    )
    mode.add_argument(
        "--resume",
        action="store_true",
        help="after a submit/job failure stop: submit the never-submitted jobs in a NEW batch",
    )
    args = ap.parse_args(argv)
    stdin = stdin if stdin is not None else sys.stdin
    out = stdout if stdout is not None else sys.stdout
    clock = clock or (lambda: datetime.now(UTC))
    factory = service_factory or default_service_factory
    batch_dir: Path = args.batch_dir
    plan_bytes = (batch_dir / "plan.json").read_bytes()
    plan_sha = sha256_hex(plan_bytes)
    plan = json.loads(plan_bytes)
    approval_path = batch_dir / "approval.json"

    if args.resume:
        return _resume_batch(
            batch_dir,
            plan,
            plan_sha,
            stdin=stdin,
            out=out,
            factory=factory,
            budget_path=budget_path,
            clock=clock,
            sleep=sleep,
            max_usage_polls=max_usage_polls,
            poll_seconds=poll_seconds,
        )

    if args.reconcile:  # creates no job, so no TTY approval; but it needs an approved plan
        if not approval_path.exists():
            raise ApprovalRefused("not_approved", "no approval.json: nothing to reconcile")
        if json.loads(approval_path.read_text())["plan_sha256"] != plan_sha:
            raise ApprovalRefused("plan_changed", "approval.json does not match plan.json")
        runner = _Runner(
            batch_dir,
            plan,
            factory(),
            budget_path,
            clock,
            sleep,
            max_usage_polls,
            poll_seconds,
            out,
        )
        try:
            return _reconcile(runner, batch_dir)
        finally:
            runner.service.close()

    # (a) interactive TTY
    if not stdin.isatty():
        raise ApprovalRefused("not_a_tty", "stdin is not an interactive terminal")
    out.write(
        f"Batch {plan['batch_id']} on {plan['backend']}: {len(plan['jobs'])} jobs, "
        f"estimated {plan['total_estimated_seconds']} s of QPU time.\n"
        f"Plan hash: {plan_sha}\n"
        "Type the first 8 characters of the plan hash to approve and submit: "
    )
    out.flush()
    typed = stdin.readline().strip()
    # (b) exactly 8 lowercase hex characters equal to the plan hash prefix
    if not PREFIX_RE.fullmatch(typed) or typed != plan_sha[:8]:
        raise ApprovalRefused("hash_mismatch", "typed prefix does not match the plan hash")
    # (c) an existing approval must match this plan
    if approval_path.exists() and json.loads(approval_path.read_text())["plan_sha256"] != plan_sha:
        raise ApprovalRefused("plan_changed", "approval.json does not match plan.json")

    # never resubmit: any trace of an earlier run means reconcile or re-plan
    jobs_dir = batch_dir / "jobs"
    if (
        (batch_dir / "stopped.json").exists()
        or _journal(batch_dir)
        or (jobs_dir.exists() and any(jobs_dir.glob("*.json")))
    ):
        out.write(
            "REFUSED (resume_refused): this batch already submitted or stopped. "
            "Use --reconcile, or re-plan and re-approve.\n"
        )
        return 8
    if not approval_path.exists():
        _write_new(
            approval_path,
            {
                "batch_id": plan["batch_id"],
                "plan_sha256": plan_sha,
                "approved_at": clock().isoformat(),
                "approved_by": "human",
            },
        )

    remaining = budget.remaining_seconds(path=budget_path, now=clock())
    if remaining < plan["total_estimated_seconds"]:
        return _stop_file(
            batch_dir,
            _Stop(
                4,
                "budget",
                f"ledger has {remaining:.1f} s left < plan {plan['total_estimated_seconds']} s",
            ),
            out,
        )

    runner = _Runner(
        batch_dir, plan, factory(), budget_path, clock, sleep, max_usage_polls, poll_seconds, out
    )
    try:
        try:
            stop = _execute(runner, plan)
        except _Stop as exc:
            runner.cancel_unfinished(runner.handles)
            runner.wait_all([h for h in runner.handles if not h.done])
            stop = exc
        except budget.BudgetExceeded as exc:
            runner.cancel_unfinished(runner.handles)
            runner.wait_all([h for h in runner.handles if not h.done])
            stop = _Stop(4, "budget", str(exc))
    finally:
        runner.service.close()
    if stop:
        return _stop_file(batch_dir, stop, out)
    out.write("all jobs finished\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApprovalRefused as refusal:
        print(f"REFUSED ({refusal.reason}): {refusal}", file=sys.stderr)
        raise SystemExit(2) from refusal
