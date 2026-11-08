"""A superseded batch may be skipped by the gate only if nothing was approved or submitted from it.

`scripts/gate.py::_p2_batches` decides which batches the Phase 2 checks look at. A replaced plan
(SUPERSEDED.md) is skipped so the gate does not demand an approval for a plan nobody will run, but
a batch that was ever approved, submitted, or stopped must stay gated, otherwise spent QPU time
could hide behind a SUPERSEDED.md file. These tests run the real functions against a tmp tree.
"""

from __future__ import annotations

import json

import pytest

from scripts import gate


@pytest.fixture
def hw(tmp_path, monkeypatch):
    root = tmp_path / "hardware"
    root.mkdir()
    monkeypatch.setattr(gate, "P2_HW", root)
    return root


def batch(root, name, *, superseded=False, extra=()):
    d = root / name
    d.mkdir()
    (d / "plan.json").write_text(json.dumps({"batch_id": name, "jobs": []}))
    if superseded:
        (d / "SUPERSEDED.md").write_text("replaced by a newer plan\n")
    for item in extra:
        if item == "jobs":
            (d / "jobs").mkdir()
        else:
            (d / item).write_text("{}\n")
    return d


def names(root):
    return [b.name for b in gate._p2_batches()]


def test_gate_with_no_hardware_directory_has_no_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "P2_HW", tmp_path / "does-not-exist")
    assert gate._p2_batches() == []


def test_gate_keeps_a_normal_batch(hw):
    batch(hw, "b1")
    assert names(hw) == ["b1"]


def test_gate_skips_an_untouched_superseded_batch(hw):
    batch(hw, "old", superseded=True)
    batch(hw, "new")
    assert names(hw) == ["new"]


def test_gate_skips_nothing_when_the_only_batch_is_superseded_and_untouched(hw):
    batch(hw, "old", superseded=True)
    assert names(hw) == []


@pytest.mark.parametrize("touch", ["approval.json", "submitted.jsonl", "jobs", "stopped.json"])
def test_gate_does_not_skip_a_superseded_batch_that_was_approved_or_submitted(hw, touch):
    batch(hw, "old", superseded=True, extra=[touch])
    batch(hw, "new")
    assert sorted(names(hw)) == ["new", "old"]


def test_gate_does_not_skip_a_superseded_batch_even_if_the_jobs_directory_is_empty(hw):
    # `jobs/` exists the moment submit started writing; emptiness must not count as untouched
    batch(hw, "old", superseded=True, extra=["jobs"])
    assert names(hw) == ["old"]


def test_gate_ignores_a_directory_without_a_plan(hw):
    (hw / "scratch").mkdir()
    (hw / "scratch" / "SUPERSEDED.md").write_text("x")
    batch(hw, "b1")
    assert names(hw) == ["b1"]


def test_superseded_marker_alone_is_what_makes_a_batch_skippable(hw):
    # without SUPERSEDED.md an untouched batch is gated (it has no approval: the gate must fail it)
    batch(hw, "plain")
    assert gate._p2_superseded(hw / "plain") is False


def test_a_touched_superseded_batch_still_fails_the_approval_check(hw):
    """End to end: jobs exist but no approval.json, so p2_batches_approved must report a problem."""
    d = batch(hw, "old", superseded=True, extra=["jobs"])
    (d / "jobs" / "0.json").write_text(
        json.dumps({"index": 0, "job_id": "j0", "created": "2026-11-08T00:00:00+00:00"})
    )
    ok, detail = gate.p2_batches_approved()
    assert not ok
    assert "old" in detail


def test_with_only_an_untouched_superseded_batch_the_gate_reports_no_batch(hw):
    batch(hw, "old", superseded=True)
    ok, detail = gate.p2_batches_approved()
    assert not ok and "no batch" in detail
