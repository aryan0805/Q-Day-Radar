"""The stored common-basis circuits: they reload in Qiskit and match the reference parser."""

from __future__ import annotations

import gzip
import hashlib

import pytest
from qiskit import QuantumCircuit

from tests.phase3 import reference as ref

CIRCUITS = ref.CIRCUITS


def _files() -> list:
    return ref.circuit_files()


def _text(path) -> str:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.read()


def _sha(path) -> str:
    return path.name.removesuffix(".qasm.gz")


def test_estimate_stored_circuits_are_gzip_only_and_each_decompresses_to_its_sha256_name():
    """The file name is the sha256 of the UNcompressed QASM; a raw .qasm must not linger (size)."""
    assert not list(CIRCUITS.glob("*.qasm")), "raw .qasm files left next to the .gz ones"
    for path in _files():
        assert path.name.endswith(".qasm.gz"), path.name
        assert hashlib.sha256(_text(path).encode()).hexdigest() == _sha(path), path.name


def test_estimate_every_case_file_names_a_stored_circuit_with_the_same_sha256():
    """Per-case `circuit_sha256` -> a stored file whose decompressed hash is that same value."""
    seen = 0
    for tool in ("qdk", "qualtran"):
        for name, c in ref.cases(tool).items():
            sha = c.get("circuit_sha256")
            if not sha:
                continue  # bloq-method cases have no QASM; same_circuit ones are required elsewhere
            seen += 1
            text = ref.read_circuit(sha)
            assert hashlib.sha256(text.encode()).hexdigest() == sha, f"{tool}/{name}"
    assert seen >= 8, f"only {seen} case files carry a circuit_sha256"


def test_estimate_every_stored_circuit_reloads_with_qiskit_qasm2():
    """A register named like a gate (x) used to break Qiskit's strict loader."""
    for path in _files():
        QuantumCircuit.from_qasm_str(_text(path))  # raises on any parse problem


def test_estimate_qiskit_and_the_reference_parser_agree_on_every_stored_circuit():
    """Two parsers, one answer: T-type gates, generic rotations and Toffolis."""
    from math import pi

    for path in _files():
        text = _text(path)
        want = ref.qasm_counts(text)
        qc = QuantumCircuit.from_qasm_str(text)
        t = rot = ccx = 0
        for inst in qc.data:
            name = inst.operation.name
            if name in {"t", "tdg"}:
                t += 1
            elif name == "rz":
                quarter = float(inst.operation.params[0]) / (pi / 4)
                if abs(quarter - round(quarter)) < 1e-9:
                    t += round(quarter) % 2
                else:
                    rot += 1
            elif name in {"ccx", "ccz", "cswap"}:
                ccx += 1
        assert (t, rot, ccx) == (want["t"], want["rotations"], want["ccx"]), path.name


def test_estimate_grover_common_basis_has_no_rotation_because_the_source_has_none():
    """No rz may come from lowering a multi-controlled X (lead, 2026-11-08)."""
    from quantum.circuits import registry

    crosscheck = ref.load_json(ref.EST / "crosscheck.json")["cases"]
    qdk = ref.cases("qdk")
    for k in (2, 3, 4, 5):
        name = f"grover_present_k{k}"
        src = registry.build_circuit(name)
        src_ops = {i.operation.name for i in src.decompose(reps=0).data}
        assert not ({"rz", "rx", "ry", "p", "u1", "u3", "u", "cp", "crz"} & src_ops), (
            name,
            src_ops,
        )
        assert name in {r["case"] for r in crosscheck}
        text = ref.read_circuit(qdk[name]["circuit_sha256"])
        got = ref.qasm_counts(text)
        assert got["rotations"] == 0, f"{name}: {got['rotations']} rotations in the common basis"
        assert qdk[name]["logical_counts"]["rotation_count"] == 0, name


def test_estimate_grover_nopeel_cases_also_have_no_rotation_in_the_common_basis():
    qdk = ref.cases("qdk")
    for k in (2, 3, 4, 5):
        name = f"grover_present_k{k}_nopeel"
        assert name in qdk, name
        assert qdk[name]["logical_counts"]["rotation_count"] == 0, name
        sha = qdk[name]["circuit_sha256"]
        assert ref.qasm_counts(ref.read_circuit(sha))["rotations"] == 0, name


@pytest.mark.parametrize("controls", [3, 4, 5])
def test_estimate_form_lowers_a_multi_controlled_x_to_4_k_minus_2_toffolis_and_keeps_the_unitary(
    controls,
):
    """Barenco: k controls with k-2 DIRTY ancillas cost 4(k-2) Toffolis. Checked by hand count and
    by comparing the full unitary (ancillas included) with Qiskit's own multi-controlled X."""
    from qiskit import qasm2
    from qiskit.quantum_info import Operator

    from quantum.estimate import common

    n = controls + 1 + (controls - 2)  # controls, target, spare qubits to borrow
    qc = QuantumCircuit(n)
    qc.mcx(list(range(controls)), controls)
    form = common.estimation_form(qc)
    counts = ref.qasm_counts(qasm2.dumps(form))
    assert counts["ccx"] == 4 * (controls - 2), counts
    assert counts["rotations"] == 0 and counts["t"] == 0, counts
    assert Operator(form).equiv(Operator(qc)), "lowering changed the unitary"


def test_estimate_form_mcx_without_spare_qubits_does_not_silently_return_a_wrong_circuit():
    from quantum.estimate import common

    qc = QuantumCircuit(4)
    qc.mcx([0, 1, 2], 3)  # no spare qubit to borrow
    try:
        form = common.estimation_form(qc)
    except (ValueError, RuntimeError):
        return
    from qiskit.quantum_info import Operator

    assert Operator(form).equiv(Operator(qc)), "no ancilla available, yet the unitary changed"


@pytest.mark.parametrize("controls", [3, 4, 5])
def test_estimate_form_mcx_lowering_works_for_every_state_of_the_borrowed_ancillas(controls):
    """Dirty ancillas: act on random states of ALL qubits (ancillas included) and compare with
    Qiskit's own multi-controlled X. A lowering that needs |0> ancillas fails here."""
    import numpy as np
    from qiskit.quantum_info import Statevector

    from quantum.estimate import common

    n = controls + 1 + (controls - 2)
    qc = QuantumCircuit(n)
    qc.mcx(list(range(controls)), controls)
    form = common.estimation_form(qc)
    rng = np.random.default_rng(1234)
    for _ in range(6):
        v = rng.normal(size=2**n) + 1j * rng.normal(size=2**n)
        v /= np.linalg.norm(v)
        a, b = Statevector(v).evolve(qc), Statevector(v).evolve(form)
        # equal up to one global phase: |<a|b>| = 1
        assert abs(np.vdot(a.data, b.data)) == pytest.approx(1.0, abs=1e-9)


def test_estimate_form_mcx_test_has_teeth_dropping_one_toffoli_or_cleaning_ancillas_fails():
    """Mutation checks for the two MCX tests above."""
    import numpy as np
    from qiskit.quantum_info import Operator, Statevector

    from quantum.estimate import common

    controls = 4
    n = controls + 1 + (controls - 2)
    qc = QuantumCircuit(n)
    qc.mcx(list(range(controls)), controls)
    form = common.estimation_form(qc)
    # (a) remove one ccx: the unitary must change
    idx = next(i for i, inst in enumerate(form.data) if inst.operation.name == "ccx")
    broken = form.copy_empty_like()
    for i, inst in enumerate(form.data):
        if i != idx:
            broken.append(inst.operation, inst.qubits, inst.clbits)
    assert not Operator(broken).equiv(Operator(qc))
    # (b) only the first half of the gate list (compute, no uncompute): still right on
    # |0...0> (no control is set) but a random state of all qubits, ancillas included, exposes it.
    # A uniform superposition would NOT expose it: it is invariant under any basis permutation.
    half = form.copy_empty_like()
    for inst in form.data[: len(form.data) // 2]:
        half.append(inst.operation, inst.qubits, inst.clbits)
    zero = Statevector.from_label("0" * n)
    assert abs(np.vdot(zero.evolve(qc).data, zero.evolve(half).data)) == pytest.approx(1.0)
    rng = np.random.default_rng(99)
    v = rng.normal(size=2**n) + 1j * rng.normal(size=2**n)
    v /= np.linalg.norm(v)
    overlap = abs(np.vdot(Statevector(v).evolve(qc).data, Statevector(v).evolve(half).data))
    assert overlap < 0.99, f"half a lowering passed on a random state (overlap {overlap:.4f})"
