"""Shared pieces of the Phase 3 estimators: the equivalence formula and the common circuit form.

Every number that ends up in a result file is computed here from each tool's raw counts, so
the two tools are compared on one price list. The only typed number is ROTATION_EPS (a design
choice, stored in every file); the rotation synthesis coefficient comes from literature.yaml.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import cache
from math import isclose, log2, pi
from pathlib import Path

import yaml
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import ControlFlowOp, IfElseOp

LITERATURE_PATH = Path(__file__).with_name("literature.yaml")
ROTATION_EPS: float = 1e-10  # one precision for every rotation, both tools
ROTATION_COEFF_ID = "ross_selinger2014_t_per_rotation"

# The shared basis both tools are given (rz angles that are multiples of pi/4 become T/S/Z).
SHARED_BASIS = ["h", "x", "z", "s", "sdg", "t", "tdg", "cx", "ccx", "rz", "measure", "reset"]
_ATOL = 1e-9


@cache
def literature() -> dict[str, dict]:
    with LITERATURE_PATH.open() as fh:
        return {e["id"]: e for e in yaml.safe_load(fh)}


def rotation_t_cost(eps: float) -> float:
    """T gates per arbitrary z-rotation at precision eps: coefficient * log2(1/eps).

    Coefficient 3 is Ross-Selinger's typical-case leading term (literature.yaml); the
    O(log log(1/eps)) term is dropped, so this slightly underestimates.
    """
    return float(literature()[ROTATION_COEFF_ID]["value"]) * log2(1.0 / eps)


def toffoli_equiv(
    *,
    toffoli: int = 0,
    ccz: int = 0,
    ccix: int = 0,
    t: int = 0,
    rotations: int = 0,
    eps: float,
) -> float:
    """toffoli + ccz + ccix + t/4 + rotations * rotation_t_cost(eps) / 4."""
    return toffoli + ccz + ccix + t / 4 + rotations * rotation_t_cost(eps) / 4


def circuit_sha256(qasm: str) -> str:
    return hashlib.sha256(qasm.encode()).hexdigest()


def conditionals_always_on(qc: QuantumCircuit) -> QuantumCircuit:
    """Inline every if_else true-body unconditionally: each conditional gate counted once.

    Cost meaning: the exact per-shot worst case over all measurement histories (an upper
    bound), NOT an expectation. QDK instead follows one branch chosen from a fixed
    pseudo-random outcome sequence, so its raw numbers on dynamic circuits are not usable.
    """
    out = qc.copy_empty_like(name=f"{qc.name}_condon")
    for inst in qc.data:
        op = inst.operation
        if isinstance(op, IfElseOp):
            if len(op.blocks) > 1 and len(op.blocks[1].data):
                raise ValueError("if_else with a non-empty else-branch has no single-circuit bound")
            body = conditionals_always_on(op.blocks[0])
            out.compose(body, qubits=inst.qubits, clbits=inst.clbits, inplace=True)
        elif isinstance(op, ControlFlowOp):
            raise NotImplementedError(f"control flow {op.name!r} is not handled")
        else:
            out._append(inst)
    return out


def _mcx_ccx_chain(controls: list, target, dirty: list) -> list[tuple[str, tuple]]:
    """Barenco et al. Lemma 7.2: k-control X from 4(k-2) Toffolis and k-2 DIRTY ancillas.

    Returns [("ccx", (a, b, c))...] / [("cx", ...)]. Ancillas come back unchanged for any input.
    """
    k = len(controls)
    if k == 1:
        return [("cx", (controls[0], target))]
    if k == 2:
        return [("ccx", (controls[0], controls[1], target))]
    a = dirty[: k - 2]
    down = [("ccx", (controls[i + 1], a[i - 1], a[i])) for i in range(k - 3, 0, -1)]
    mid = [("ccx", (controls[0], controls[1], a[0]))]
    up = [("ccx", (controls[i + 1], a[i - 1], a[i])) for i in range(1, k - 2)]
    top = [("ccx", (controls[k - 1], a[k - 3], target))]
    return top + down + mid + up + top + down + mid + up


def mcx_to_ccx(qc: QuantumCircuit) -> QuantumCircuit:
    """Replace every multi-controlled X (3+ controls) by a Toffoli chain on dirty ancillas.

    The ancillas are other qubits of the circuit, so no qubit is added. No rotations result.
    """
    out = qc.copy_empty_like()
    for inst in qc.data:
        op = inst.operation
        if op.name == "mcx" and op.num_qubits - 1 >= 3:
            qs = list(inst.qubits)
            controls, target = qs[:-1], qs[-1]
            busy = set(qs)
            dirty = [q for q in qc.qubits if q not in busy][: len(controls) - 2]
            if len(dirty) < len(controls) - 2:
                raise ValueError("not enough spare qubits for a dirty-ancilla mcx lowering")
            for name, args in _mcx_ccx_chain(controls, target, dirty):
                out.append(name_to_gate(name), list(args))
        else:
            out._append(inst)
    return out


def name_to_gate(name: str):
    from qiskit.circuit.library import CCXGate, CXGate

    return {"ccx": CCXGate(), "cx": CXGate()}[name]


_RESERVED_REGISTERS = set(SHARED_BASIS) | {"y", "u", "p", "cz", "cp", "id", "sx", "cswap"}


def _rename_registers(qc: QuantumCircuit) -> QuantumCircuit:
    """Registers named like gates ('x', 't', ...) break strict QASM2 reload: add a suffix."""
    if not any(r.name in _RESERVED_REGISTERS for r in (*qc.qregs, *qc.cregs)):
        return qc
    from qiskit.circuit import ClassicalRegister, QuantumRegister

    def fix(name: str) -> str:
        return f"{name}_r" if name in _RESERVED_REGISTERS else name

    qmap = {r: QuantumRegister(len(r), fix(r.name)) for r in qc.qregs}
    cmap = {r: ClassicalRegister(len(r), fix(r.name)) for r in qc.cregs}
    out = QuantumCircuit(*qmap.values(), *cmap.values(), name=qc.name)
    out.global_phase = qc.global_phase
    qm = {q: out.qubits[i] for i, q in enumerate(qc.qubits)}
    cm = {c: out.clbits[i] for i, c in enumerate(qc.clbits)}
    for inst in qc.data:
        out._append(inst.operation, [qm[q] for q in inst.qubits], [cm[c] for c in inst.clbits])
    out.metadata = qc.metadata
    return out


def _canonical_rz(qc: QuantumCircuit) -> QuantumCircuit:
    """rz(k pi/4) -> exact T/S/Z/Sdg (up to global phase): both tools then classify it alike."""
    out = qc.copy_empty_like()
    for inst in qc.data:
        op = inst.operation
        if op.name == "rz":
            k = float(op.params[0]) / (pi / 4)
            if isclose(k, round(k), abs_tol=_ATOL):
                k = round(k) % 8
                (q,) = inst.qubits
                if k % 2:
                    out.t(q)
                    k -= 1
                {
                    0: lambda: None,
                    2: lambda q=q: out.s(q),
                    4: lambda q=q: out.z(q),
                    6: lambda q=q: out.sdg(q),
                }[k]()
                continue
        out._append(inst)
    return out


def estimation_form(qc: QuantumCircuit) -> QuantumCircuit:
    """Non-dynamic circuit in SHARED_BASIS, same gates as `qc`, for costing only (not to run).

    Steps: inline conditionals (upper bound), translate to SHARED_BASIS without optimisation,
    rewrite rz angles that are multiples of pi/4. Never mutates its input.
    """
    flat = mcx_to_ccx(conditionals_always_on(qc))
    low = transpile(flat, basis_gates=SHARED_BASIS, optimization_level=0)
    out = _rename_registers(_canonical_rz(low))
    out.name = f"{qc.name}_estimation_form"
    out.metadata = {
        **(qc.metadata or {}),
        "costing_variant": "estimation_form",
        "circuit_form": "non_dynamic",
        "classical_control_counted": "executed",
    }
    bad = set(out.count_ops()) - set(SHARED_BASIS)
    if bad:
        raise ValueError(f"gates outside the shared basis: {sorted(bad)}")
    return out


def parse_power(text: str | float) -> float:
    """'1.19*2^86' -> float; plain numbers pass through."""
    if not isinstance(text, str):
        return float(text)
    m = re.fullmatch(r"\s*([\d.]+)\s*\*\s*2\^(\d+)\s*", text)
    if m:
        return float(m.group(1)) * 2 ** int(m.group(2))
    return float(text)


def eval_formula(text: str, n: float) -> float:
    """Evaluate a paper formula such as '3n + 0.002 n lg n' at n. Only n, numbers, + - * and lg."""
    expr = text.replace("lg n", "*log2(n)")
    expr = re.sub(r"(\d)\s*n\b", r"\1*n", expr)
    expr = re.sub(r"\s+n\b", "*n", expr)
    if re.search(r"[^0-9n.+\-*/() log2]", expr):
        raise ValueError(f"unsupported formula {text!r}")
    return float(eval(expr, {"__builtins__": {}}, {"n": n, "log2": math.log2}))  # noqa: S307
