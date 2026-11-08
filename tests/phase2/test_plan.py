"""scripts/plan_hardware.py: pilots first, signal-based selection, <= 300 s, pre-registered
predictions on the IDENTICAL ISA circuit. Offline: FakeKingston stands in for the device.

The circuit set is small on purpose (the honest Beauregard circuits take hours to simulate with
noise): grover k2 / k3 and the textbook Shor are static; a tiny dynamic circuit carries the name
of the Beauregard control so the dynamic-circuit rules are exercised.
"""

import json
import math
from collections import Counter
from datetime import UTC, datetime

import pytest
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator

pytest.importorskip("scripts.plan_hardware")
from quantum.backends import get_fake_backend  # noqa: E402
from quantum.circuits import registry  # noqa: E402
from quantum.run import hardware  # noqa: E402
from scripts import plan_hardware  # noqa: E402
from scripts.plan_hardware import build_plan  # noqa: E402

SHOTS = 1024
REPEATS = 2
NOW = datetime(2026, 11, 8, 10, 30, tzinfo=UTC)


def tiny_dynamic() -> QuantumCircuit:
    """Stands in for the honest Beauregard circuit: mid-circuit measure + reset, 8 'phase' bits."""
    q, c = QuantumRegister(2, "q"), ClassicalRegister(8, "phase")
    qc = QuantumCircuit(q, c)
    for i in range(8):
        if i:
            qc.reset(q[0])
        qc.h(q[0])
        qc.cx(q[0], q[1])
        qc.measure(q[0], c[i])
    qc.metadata = {"name": "shor15_beauregard", "kind": "generic"}
    return qc


def noisy_dir(tmp_path, signals):
    d = tmp_path / "noisy"
    d.mkdir()
    for name, signal in signals.items():
        (d / f"{name}.json").write_text(json.dumps({"name": name, "signal": signal}))
    return d


def circuits():
    return {
        "grover_present_k3": registry.build_circuit("grover_present_k3"),
        "grover_present_k2": registry.build_circuit("grover_present_k2"),
        "shor15_textbook": registry.build_circuit("shor15_textbook"),
        "shor15_beauregard": tiny_dynamic(),
    }


def _stub_predict(isa, backend, shots, seed):
    return {"0" * isa.num_clbits: shots}


@pytest.fixture(scope="module")
def planned(tmp_path_factory):
    """Structure of a full plan. The noisy simulation is stubbed here (it is slow and these tests
    are not about it); `planned_real` below runs the real prediction on a small plan."""
    tmp = tmp_path_factory.mktemp("plan")
    signals = {
        "grover_present_k2": True,
        "grover_present_k3": True,
        "shor15_textbook": False,  # no signal under noise: must be dropped
        "shor15_beauregard": False,  # dynamic and no signal: planned as the single raw control
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(plan_hardware, "_predict", _stub_predict)
        batch = build_plan(
            circuits(),
            get_fake_backend(),
            shots=SHOTS,
            out_root=tmp / "hardware",
            batch_id="plan-test",
            now=lambda: NOW,
            noisy_dir=noisy_dir(tmp, signals),
            repeats=REPEATS,
            backend_choice_reason="test: FakeKingston stands in for ibm_kingston",
        )
    return batch, json.loads((batch / "plan.json").read_text()), tmp


@pytest.fixture(scope="module")
def planned_real(tmp_path_factory):
    """A small plan with the REAL noisy-simulation predictions (k2 + the tiny dynamic control)."""
    tmp = tmp_path_factory.mktemp("plan_real")
    batch = build_plan(
        {"grover_present_k2": circuits()["grover_present_k2"], "shor15_beauregard": tiny_dynamic()},
        get_fake_backend(),
        shots=SHOTS,
        out_root=tmp / "hardware",
        batch_id="plan-real",
        noisy_dir=noisy_dir(tmp, {"grover_present_k2": True, "shor15_beauregard": False}),
        repeats=1,
    )
    return batch, json.loads((batch / "plan.json").read_text()), tmp


def isa_two_qubit_count(name):
    pm = generate_preset_pass_manager(
        optimization_level=3, backend=get_fake_backend(), seed_transpiler=1234
    )
    return pm.run(circuits()[name]).num_nonlocal_gates()


# ---- structure the gate and submit script rely on ------------------------------------------


def test_plan_has_the_agreed_top_level_and_job_fields(planned):
    _, plan, _ = planned
    assert {"batch_id", "created", "backend", "total_estimated_seconds", "jobs"} <= set(plan)
    assert plan["batch_id"] == "plan-test" and plan["created"] == NOW.isoformat()
    for i, job in enumerate(plan["jobs"]):
        assert {
            "index", "name", "kind", "config", "shots", "isa_sha256", "estimated_seconds",
            "prediction", "pilot",
        } <= set(job)  # fmt: skip
        assert job["index"] == i and job["shots"] == SHOTS
        assert {"model", "counts", "success_probability"} <= set(job["prediction"])
        assert sum(job["prediction"]["counts"].values()) == SHOTS


def test_plan_total_is_the_sum_of_estimates_and_within_the_cap(planned):
    _, plan, _ = planned
    assert plan["total_estimated_seconds"] == pytest.approx(
        sum(j["estimated_seconds"] for j in plan["jobs"]), abs=0.1
    )
    assert 0 < plan["total_estimated_seconds"] <= 300


# ---- pilots --------------------------------------------------------------------------------


def test_plan_pilots_are_the_smallest_circuit_under_each_config_then_one_calibration(planned):
    _, plan, _ = planned
    jobs = plan["jobs"]
    static = ["grover_present_k2", "grover_present_k3"]
    smallest = min(static, key=lambda n: (isa_two_qubit_count(n), n))
    assert smallest == "grover_present_k2"
    pilots = [j for j in jobs if j["pilot"]]
    assert [j["index"] for j in pilots] == [0, 1, 2, 3], "pilots come first"
    assert [(j["name"], j["config"]) for j in pilots[:3]] == [
        (smallest, "raw"), (smallest, "dd"), (smallest, "dd_twirl"),
    ]  # fmt: skip
    assert pilots[3]["config"] == "m3_cal"
    assert not any(j["pilot"] for j in jobs[4:])


def test_plan_calibration_ones_is_last_and_zeros_is_a_pilot(planned):
    _, plan, _ = planned
    cal = [j for j in plan["jobs"] if j["config"] == "m3_cal"]
    assert [j["name"] for j in cal] == ["m3_cal_zeros", "m3_cal_ones"]
    assert cal[0]["pilot"] and not cal[1]["pilot"]
    assert plan["jobs"][-1]["name"] == "m3_cal_ones"
    assert all(j["kind"] == "calibration" for j in cal)


def test_plan_calibration_measures_exactly_the_physical_qubits_the_experiments_measure(planned):
    # M3 matrices are per physical qubit: a calibration laid out on OTHER qubits is useless
    _, plan, _ = planned
    needed = sorted(
        {
            q
            for j in plan["jobs"]
            if j["config"] in ("raw", "dd", "dd_twirl")
            for q in j["measured_qubits"]
        }
    )
    assert plan["m3_qubits"] == needed
    for j in plan["jobs"]:
        if j["config"] == "m3_cal":
            assert j["measured_qubits"] == needed, (
                f"{j['name']} measures {j['measured_qubits']}, experiments use {needed}"
            )


# ---- which circuits and configs ------------------------------------------------------------


def test_plan_drops_circuits_without_noisy_signal(planned):
    _, plan, _ = planned
    names = {j["name"] for j in plan["jobs"]}
    assert "shor15_textbook" not in names
    assert {"grover_present_k2", "grover_present_k3"} <= names


def test_plan_static_circuits_get_raw_dd_and_dd_twirl_once_per_repeat(planned):
    _, plan, _ = planned
    for name in ("grover_present_k2", "grover_present_k3"):
        got = Counter(j["config"] for j in plan["jobs"] if j["name"] == name)
        assert got == {"raw": REPEATS, "dd": REPEATS, "dd_twirl": REPEATS}, (name, got)


def test_plan_dynamic_circuit_is_a_single_raw_control_never_dd_or_twirl(planned):
    _, plan, _ = planned
    dyn = [j for j in plan["jobs"] if j["name"] == "shor15_beauregard"]
    assert [j["config"] for j in dyn] == ["control"]
    assert sum(1 for j in plan["jobs"] if j["config"] == "control") <= 2
    assert all(j["config"] not in ("dd", "dd_twirl") for j in dyn)


def test_plan_twirled_jobs_record_randomizations_that_multiply_to_the_shots(planned):
    _, plan, _ = planned
    for j in plan["jobs"]:
        if j["config"] == "dd_twirl":
            assert j["num_randomizations"] * j["shots_per_randomization"] == j["shots"]
        else:
            assert "num_randomizations" not in j


# ---- pre-registration: the prediction is of the identical ISA circuit ---------------------------


def test_plan_isa_hash_is_the_sha256_of_the_saved_qpy_bytes(planned):
    import hashlib

    batch, plan, _ = planned
    for j in plan["jobs"]:
        data = (batch / "circuits" / f"{j['index']}.qpy").read_bytes()
        assert hashlib.sha256(data).hexdigest() == j["isa_sha256"]


def test_plan_same_circuit_under_every_config_and_repeat_is_the_same_isa(planned):
    # QPY bytes are NOT deterministic (the same circuit serialises to different bytes each time),
    # so the hash cannot show this; compare the loaded circuits structurally
    batch, plan, _ = planned
    for name in ("grover_present_k2", "grover_present_k3"):
        jobs = [j for j in plan["jobs"] if j["name"] == name]
        loaded = [
            hardware.load_qpy((batch / "circuits" / f"{j['index']}.qpy").read_bytes()) for j in jobs
        ]
        assert all(c == loaded[0] for c in loaded[1:]), f"{name} differs between configs/repeats"
    others = {
        j["name"]: hardware.load_qpy((batch / "circuits" / f"{j['index']}.qpy").read_bytes())
        for j in plan["jobs"]
    }
    assert others["grover_present_k2"] != others["grover_present_k3"]


def test_plan_every_job_has_its_own_qpy_file(planned):
    # NOT asserting distinct isa_sha256: QPY bytes are only sometimes non-deterministic, so two
    # jobs of one circuit may or may not share a hash. Integrity is file == hash (tested above);
    # circuit identity is content_sha256 (tested below).
    batch, plan, _ = planned
    assert sorted(p.name for p in (batch / "circuits").iterdir()) == sorted(
        f"{j['index']}.qpy" for j in plan["jobs"]
    )


@pytest.mark.parametrize("which", ["first", "last"])
def test_plan_static_prediction_reproduces_exactly_from_the_saved_isa_circuit(planned_real, which):
    batch, plan, _ = planned_real
    job = {"first": plan["jobs"][0], "last": plan["jobs"][-1]}[which]
    isa = hardware.load_qpy((batch / "circuits" / f"{job['index']}.qpy").read_bytes())
    sim = AerSimulator.from_backend(get_fake_backend(), shot_branching_enable=True)
    counts = sim.run(isa, shots=SHOTS, seed_simulator=1234).result().get_counts()
    assert {k: int(v) for k, v in counts.items()} == job["prediction"]["counts"]
    if job["name"] in registry.SUCCESS_FN:
        check = registry.SUCCESS_FN[job["name"]]
        want = sum(v for b, v in counts.items() if check(b)) / SHOTS
        assert math.isclose(job["prediction"]["success_probability"], want, abs_tol=1e-12)


def test_plan_dynamic_prediction_is_a_statistically_consistent_simulation_of_the_saved_isa(
    planned_real,
):
    # dynamic circuits are not bit-reproducible with shot branching (observed): the stored
    # prediction is the pre-registered record, so only statistical agreement is required
    batch, plan, _ = planned_real
    job = next(j for j in plan["jobs"] if j["name"] == "shor15_beauregard")
    isa = hardware.load_qpy((batch / "circuits" / f"{job['index']}.qpy").read_bytes())
    assert hardware.count_mid_circuit(isa) > 0
    sim = AerSimulator.from_backend(get_fake_backend(), shot_branching_enable=True)
    counts = sim.run(isa, shots=SHOTS, seed_simulator=1234).result().get_counts()
    check = registry.SUCCESS_FN["shor15_beauregard"]
    again = sum(v for b, v in counts.items() if check(b)) / SHOTS
    assert abs(job["prediction"]["success_probability"] - again) < 0.06
    assert sum(job["prediction"]["counts"].values()) == SHOTS


def test_plan_estimates_follow_the_estimate_function(planned):
    batch, plan, _ = planned
    backend = get_fake_backend()
    for j in plan["jobs"]:
        isa = hardware.load_qpy((batch / "circuits" / f"{j['index']}.qpy").read_bytes())
        want = hardware.estimate_seconds(isa, SHOTS, target=backend.target, config=j["config"])
        assert j["estimated_seconds"] == pytest.approx(want)


# ---- refusals ---------------------------------------------------------------------------------


@pytest.fixture
def fast_predict(monkeypatch):
    """The refusal tests are not about predictions: stub the (slow) noisy simulation."""
    monkeypatch.setattr(
        plan_hardware, "_predict", lambda isa, backend, shots, seed: {"0" * isa.num_clbits: shots}
    )


def test_plan_over_the_cap_raises_and_leaves_nothing_on_disk(tmp_path, fast_predict):
    out = tmp_path / "hardware"
    with pytest.raises(ValueError):
        build_plan(
            {"grover_present_k2": registry.build_circuit("grover_present_k2")},
            get_fake_backend(),
            shots=SHOTS,
            out_root=out,
            batch_id="too-big",
            noisy_dir=noisy_dir(tmp_path, {"grover_present_k2": True}),
            max_total_seconds=1.0,
        )
    assert not (out / "too-big").exists(), "a refused plan must not leave a half-written batch"


def test_plan_never_overwrites_an_existing_batch(tmp_path, fast_predict):
    out = tmp_path / "hardware"
    kwargs = dict(
        shots=SHOTS,
        out_root=out,
        batch_id="once",
        noisy_dir=noisy_dir(tmp_path, {"grover_present_k2": True}),
    )
    c = {"grover_present_k2": registry.build_circuit("grover_present_k2")}
    build_plan(c, get_fake_backend(), **kwargs)
    before = (out / "once" / "plan.json").read_bytes()
    with pytest.raises(FileExistsError):
        build_plan(c, get_fake_backend(), **kwargs)
    assert (out / "once" / "plan.json").read_bytes() == before


def test_plan_with_no_static_circuit_that_has_signal_raises(tmp_path, fast_predict):
    with pytest.raises(ValueError):
        build_plan(
            {"grover_present_k2": registry.build_circuit("grover_present_k2")},
            get_fake_backend(),
            shots=SHOTS,
            out_root=tmp_path / "hardware",
            noisy_dir=noisy_dir(tmp_path, {"grover_present_k2": False}),
        )


# ---- adopted audit items: missing noisy file, deterministic content identity ---------------------


def test_plan_missing_noisy_file_raises_not_a_silent_bypass_of_the_signal_rule(
    tmp_path, fast_predict
):
    out = tmp_path / "hardware"
    with pytest.raises(FileNotFoundError):
        build_plan(
            {"grover_present_k2": registry.build_circuit("grover_present_k2")},
            get_fake_backend(),
            shots=SHOTS,
            out_root=out,
            batch_id="no-noisy",
            noisy_dir=tmp_path / "does-not-exist",
        )
    assert not (out / "no-noisy").exists()


def test_plan_refused_plan_can_be_retried_with_the_same_batch_id(tmp_path, fast_predict):
    out = tmp_path / "hardware"
    kwargs = dict(
        shots=SHOTS,
        out_root=out,
        batch_id="retry",
        noisy_dir=noisy_dir(tmp_path, {"grover_present_k2": True}),
    )
    c = {"grover_present_k2": registry.build_circuit("grover_present_k2")}
    with pytest.raises(ValueError):
        build_plan(c, get_fake_backend(), max_total_seconds=1.0, **kwargs)
    assert (build_plan(c, get_fake_backend(), **kwargs) / "plan.json").is_file()


def test_plan_content_hash_is_deterministic_and_identifies_the_circuit(planned):
    from qiskit import qasm3

    batch, plan, _ = planned
    for j in plan["jobs"]:
        isa = hardware.load_qpy((batch / "circuits" / f"{j['index']}.qpy").read_bytes())
        assert "content_sha256" in j
        # recomputing from the loaded file gives the same value: it is a content identity
        assert j["content_sha256"] == hardware.sha256_hex(qasm3.dumps(isa).encode())
    for name in ("grover_present_k2", "grover_present_k3"):
        same = {j["content_sha256"] for j in plan["jobs"] if j["name"] == name}
        assert len(same) == 1, f"{name}: raw, dd, dd_twirl and repeats are one circuit"
    k2 = next(j for j in plan["jobs"] if j["name"] == "grover_present_k2")["content_sha256"]
    k3 = next(j for j in plan["jobs"] if j["name"] == "grover_present_k3")["content_sha256"]
    assert k2 != k3


def test_plan_calibration_circuits_are_laid_out_on_the_intended_qubits_even_for_one_circuit(
    tmp_path, fast_predict
):
    batch = build_plan(
        {"grover_present_k3": registry.build_circuit("grover_present_k3")},
        get_fake_backend(),
        shots=SHOTS,
        out_root=tmp_path / "hardware",
        batch_id="cal",
        noisy_dir=noisy_dir(tmp_path, {"grover_present_k3": True}),
        repeats=1,
    )
    plan = json.loads((batch / "plan.json").read_text())
    exp = next(j for j in plan["jobs"] if j["config"] == "raw")
    for j in plan["jobs"]:
        if j["config"] == "m3_cal":
            assert j["measured_qubits"] == plan["m3_qubits"] == sorted(exp["measured_qubits"])


def test_plan_exactly_one_control_job_the_raw_shor15_beauregard(tmp_path, fast_predict):
    # lead's rule: one control only. shor21 is dynamic too but is not a control and not planned.
    def dynamic(name, n_bits):
        q, c = QuantumRegister(2, "q"), ClassicalRegister(n_bits, "phase")
        qc = QuantumCircuit(q, c)
        for i in range(n_bits):
            if i:
                qc.reset(q[0])
            qc.h(q[0])
            qc.cx(q[0], q[1])
            qc.measure(q[0], c[i])
        qc.metadata = {"name": name, "kind": "generic"}
        return qc

    batch = build_plan(
        {
            "grover_present_k2": registry.build_circuit("grover_present_k2"),
            "shor15_beauregard": dynamic("shor15_beauregard", 8),
            "shor21_beauregard": dynamic("shor21_beauregard", 10),
        },
        get_fake_backend(),
        shots=SHOTS,
        out_root=tmp_path / "hardware",
        batch_id="one-control",
        noisy_dir=noisy_dir(
            tmp_path,
            {"grover_present_k2": True, "shor15_beauregard": False, "shor21_beauregard": False},
        ),
        repeats=1,
    )
    jobs = json.loads((batch / "plan.json").read_text())["jobs"]
    controls = [(j["name"], j["config"]) for j in jobs if j["config"] == "control"]
    assert controls == [("shor15_beauregard", "control")]
    assert "shor21_beauregard" not in {j["name"] for j in jobs}


# ---- lead's plan decisions: control only without signal; backend choice is recorded ------------


def test_plan_records_why_this_backend_was_chosen(planned):
    _, plan, _ = planned
    assert plan["backend_choice_reason"] == "test: FakeKingston stands in for ibm_kingston"


def test_plan_backend_choice_reason_defaults_to_an_empty_string(tmp_path, fast_predict):
    batch = build_plan(
        {"grover_present_k2": registry.build_circuit("grover_present_k2")},
        get_fake_backend(),
        shots=SHOTS,
        out_root=tmp_path / "hardware",
        noisy_dir=noisy_dir(tmp_path, {"grover_present_k2": True}),
        repeats=1,
    )
    assert json.loads((batch / "plan.json").read_text())["backend_choice_reason"] == ""


def test_plan_dynamic_circuit_with_signal_is_a_normal_raw_job_not_a_control(tmp_path, fast_predict):
    # a control is meant to show the honest circuit sits at chance: if noisy simulation says it
    # has signal, it is just another raw run
    batch = build_plan(
        {
            "grover_present_k2": registry.build_circuit("grover_present_k2"),
            "shor15_beauregard": tiny_dynamic(),
        },
        get_fake_backend(),
        shots=SHOTS,
        out_root=tmp_path / "hardware",
        batch_id="dyn-signal",
        noisy_dir=noisy_dir(tmp_path, {"grover_present_k2": True, "shor15_beauregard": True}),
        repeats=1,
    )
    jobs = json.loads((batch / "plan.json").read_text())["jobs"]
    dyn = [j for j in jobs if j["name"] == "shor15_beauregard"]
    assert [j["config"] for j in dyn] == ["raw"]
    assert not any(j["config"] == "control" for j in jobs)


def test_plan_excludes_shor21_explicitly_even_if_its_noisy_signal_is_true(tmp_path, fast_predict):
    # lead: N = 21 is off the hardware batch regardless of the signal rule
    q, c = QuantumRegister(2, "q"), ClassicalRegister(10, "phase")
    shor21 = QuantumCircuit(q, c)
    for i in range(10):
        if i:
            shor21.reset(q[0])
        shor21.h(q[0])
        shor21.cx(q[0], q[1])
        shor21.measure(q[0], c[i])
    shor21.metadata = {"name": "shor21_beauregard", "kind": "generic"}
    batch = build_plan(
        {
            "grover_present_k2": registry.build_circuit("grover_present_k2"),
            "shor21_beauregard": shor21,
        },  # fmt: skip
        get_fake_backend(),
        shots=SHOTS,
        out_root=tmp_path / "hardware",
        batch_id="no-shor21",
        noisy_dir=noisy_dir(tmp_path, {"grover_present_k2": True, "shor21_beauregard": True}),
        repeats=1,
    )
    jobs = json.loads((batch / "plan.json").read_text())["jobs"]
    assert "shor21_beauregard" not in {j["name"] for j in jobs}


def _dynamic10():
    q, c = QuantumRegister(2, "q"), ClassicalRegister(10, "phase")
    qc = QuantumCircuit(q, c)
    for i in range(10):
        if i:
            qc.reset(q[0])
        qc.h(q[0])
        qc.cx(q[0], q[1])
        qc.measure(q[0], c[i])
    qc.metadata = {"name": "shor21_beauregard", "kind": "generic"}
    return qc


def test_plan_records_the_excluded_circuits_and_why(tmp_path, fast_predict):
    batch = build_plan(
        {
            "grover_present_k2": registry.build_circuit("grover_present_k2"),
            "shor21_beauregard": _dynamic10(),
        },  # fmt: skip
        get_fake_backend(),
        shots=SHOTS,
        out_root=tmp_path / "hardware",
        batch_id="excluded",
        noisy_dir=noisy_dir(tmp_path, {"grover_present_k2": True}),  # no shor21 noisy file at all
        repeats=1,
    )
    plan = json.loads((batch / "plan.json").read_text())
    assert [e["name"] for e in plan["excluded"]] == ["shor21_beauregard"]
    assert plan["excluded"][0]["reason"].strip(), "an exclusion needs a stated reason"
    assert "shor21_beauregard" not in {j["name"] for j in plan["jobs"]}


def test_plan_exclusion_is_a_switch_not_a_hidden_rule(tmp_path, fast_predict):
    batch = build_plan(
        {
            "grover_present_k2": registry.build_circuit("grover_present_k2"),
            "shor21_beauregard": _dynamic10(),
        },  # fmt: skip
        get_fake_backend(),
        shots=SHOTS,
        out_root=tmp_path / "hardware",
        batch_id="no-exclusion",
        noisy_dir=noisy_dir(tmp_path, {"grover_present_k2": True, "shor21_beauregard": True}),
        repeats=1,
        exclude={},
    )
    plan = json.loads((batch / "plan.json").read_text())
    assert plan.get("excluded", []) == []
    assert "shor21_beauregard" in {j["name"] for j in plan["jobs"]}


# --- first_pilot: the human wants one named circuit's raw job submitted first --------------------


@pytest.fixture(scope="module")
def first_pilot_plans(tmp_path_factory):
    """The same plan built twice: once as usual, once with the dynamic circuit as first pilot.

    The dynamic circuit has a (marginal) noisy signal here, so it is a normal raw job, as the
    real shor15_beauregard is.
    """
    tmp = tmp_path_factory.mktemp("first_pilot")
    signals = {"grover_present_k2": True, "shor15_beauregard": True}
    both = {
        "grover_present_k2": circuits()["grover_present_k2"],
        "shor15_beauregard": tiny_dynamic(),
    }
    out = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(plan_hardware, "_predict", _stub_predict)
        for label, kwargs in (("base", {}), ("first", {"first_pilot": "shor15_beauregard"})):
            (tmp / label).mkdir()
            batch = build_plan(
                both,
                get_fake_backend(),
                shots=SHOTS,
                out_root=tmp / label / "hardware",
                batch_id=f"fp-{label}",
                now=lambda: NOW,
                noisy_dir=noisy_dir(tmp / label, signals),
                repeats=2,
                **kwargs,
            )
            out[label] = (batch, json.loads((batch / "plan.json").read_text()))
    return out


def _key(job):
    return (job["name"], job["config"])


def test_first_pilot_puts_the_named_dynamic_circuit_at_index_0_as_a_pilot(first_pilot_plans):
    _, plan = first_pilot_plans["first"]
    first = plan["jobs"][0]
    assert (first["index"], first["name"], first["config"], first["pilot"]) == (
        0, "shor15_beauregard", "raw", True,
    )  # fmt: skip


def test_first_pilot_keeps_the_other_jobs_in_their_original_order(first_pilot_plans):
    _, base = first_pilot_plans["base"]
    _, first = first_pilot_plans["first"]
    moved = ("shor15_beauregard", "raw")
    assert [_key(j) for j in base["jobs"] if _key(j) != moved] == [
        _key(j) for j in first["jobs"][1:]
    ]
    assert len(base["jobs"]) == len(first["jobs"])
    assert sum(1 for j in first["jobs"] if _key(j) == moved) == 1, "moved, not duplicated"


def test_first_pilot_renumbers_indices_contiguously(first_pilot_plans):
    _, plan = first_pilot_plans["first"]
    assert [j["index"] for j in plan["jobs"]] == list(range(len(plan["jobs"])))


def test_first_pilot_pilots_are_the_first_five_and_nothing_else(first_pilot_plans):
    _, plan = first_pilot_plans["first"]
    flags = [j["pilot"] for j in plan["jobs"]]
    assert flags[:5] == [True] * 5
    assert not any(flags[5:])
    assert [_key(j) for j in plan["jobs"][1:5]] == [
        ("grover_present_k2", "raw"),
        ("grover_present_k2", "dd"),
        ("grover_present_k2", "dd_twirl"),
        ("m3_cal_zeros", "m3_cal"),
    ]  # the original pilots follow, unchanged


def test_first_pilot_changes_no_circuit_estimate_or_total(first_pilot_plans):
    _, base = first_pilot_plans["base"]
    _, first = first_pilot_plans["first"]
    assert first["total_estimated_seconds"] == base["total_estimated_seconds"]
    by_key = {_key(j): j for j in base["jobs"]}
    for j in first["jobs"]:
        b = by_key[_key(j)]
        assert j["content_sha256"] == b["content_sha256"], "same circuit"
        assert j["estimated_seconds"] == b["estimated_seconds"]
        assert j["prediction"]["counts"] == b["prediction"]["counts"]


def test_first_pilot_saved_files_follow_the_new_indices(first_pilot_plans):
    batch, plan = first_pilot_plans["first"]
    for j in plan["jobs"]:
        data = (batch / "circuits" / f"{j['index']}.qpy").read_bytes()
        assert hardware.sha256_hex(data) == j["isa_sha256"], j["index"]
    zero = hardware.load_qpy((batch / "circuits" / "0.qpy").read_bytes())
    assert hardware.count_mid_circuit(zero) > 0, "file 0 is the dynamic circuit"


def test_first_pilot_naming_a_circuit_that_is_not_in_the_plan_raises_and_writes_nothing(
    tmp_path, fast_predict
):
    signals = {"grover_present_k2": True, "shor15_beauregard": True}
    for bad in ("shor21_beauregard", "no_such_circuit"):
        (tmp_path / bad).mkdir()
        with pytest.raises(ValueError, match="first_pilot"):
            build_plan(
                {
                    "grover_present_k2": circuits()["grover_present_k2"],
                    "shor15_beauregard": tiny_dynamic(),
                },
                get_fake_backend(),
                shots=SHOTS,
                out_root=tmp_path / "hardware",
                batch_id="fp-bad",
                noisy_dir=noisy_dir(tmp_path / bad, signals),
                repeats=1,
                first_pilot=bad,
            )
        assert not (tmp_path / "hardware" / "fp-bad").exists()


def test_first_pilot_naming_a_control_job_raises_instead_of_relabelling_it_raw(
    tmp_path, fast_predict
):
    """A control run exists to be compared with the real raw runs; making it a raw pilot would
    silently change what the job means. The plan must refuse and write nothing."""
    with pytest.raises(ValueError, match=r"(?s)first_pilot.*control|control.*first_pilot"):
        build_plan(
            {
                "grover_present_k2": circuits()["grover_present_k2"],
                "shor15_beauregard": tiny_dynamic(),
            },
            get_fake_backend(),
            shots=SHOTS,
            out_root=tmp_path / "hardware",
            batch_id="fp-control",
            noisy_dir=noisy_dir(tmp_path, {"grover_present_k2": True, "shor15_beauregard": False}),
            repeats=1,
            first_pilot="shor15_beauregard",  # no noisy signal => planned as a control job
        )
    assert not (tmp_path / "hardware" / "fp-control").exists()
