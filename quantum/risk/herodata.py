"""hero.json: the home-page sequence's data (circuit, ideal and hardware counts, order and factors).

Everything is read from code and result files, nothing is typed here:
- the gate list comes from the registry's Shor-15 textbook circuit (the readable form; the stored
  estimation QASM is the same circuit lowered to Clifford + T and is ~15x longer);
- ideal probabilities are the exact statevector probabilities of that circuit;
- hardware counts are the raw job files of the human-approved ibm_kingston batch;
- the order and the factors come from the measured counts through quantum.classical.postprocess
  (continued fractions on one shot), never from a stored answer.
"""

from __future__ import annotations

import json
from pathlib import Path

from qiskit.quantum_info import Statevector

from quantum.circuits.registry import build_circuit
from quantum.classical.postprocess import convergents, factors_from_order, order_from_shot

ROOT = Path(__file__).resolve().parents[2]
CIRCUIT_NAME = "shor15_textbook"
PROB_DIGITS = 12
DEVICE_NAME = "ibm_kingston"
DEVICE_QUBITS_SOURCE = "FakeKingston snapshot of ibm_kingston (qiskit-ibm-runtime)"


def _gates(qc) -> list[dict]:
    """Gate list with ASAP layers (a gate sits one layer after the last gate on its wires)."""
    busy: dict[tuple[str, int], int] = {}
    out = []
    for inst in qc.data:
        qs = [qc.find_bit(q).index for q in inst.qubits]
        cs = [qc.find_bit(c).index for c in inst.clbits]
        wires = [("q", i) for i in qs] + [("c", i) for i in cs]
        layer = 1 + max((busy.get(w, 0) for w in wires), default=0)
        for w in wires:
            busy[w] = layer
        out.append({"op": inst.operation.name, "qubits": qs, "clbits": cs, "layer": layer})
    return out


def _ideal_probabilities(qc, n_bits: int) -> dict[str, float]:
    body = qc.remove_final_measurements(inplace=False)
    probs = Statevector.from_instruction(body).probabilities_dict(qargs=list(range(n_bits)))
    return {
        str(k): round(float(v), PROB_DIGITS)
        for k, v in sorted(probs.items())
        if round(float(v), PROB_DIGITS) > 0
    }


def _hardware(batch_dir: Path) -> dict:
    plan = json.loads((batch_dir / "plan.json").read_text())
    jobs = []
    for p in sorted((batch_dir / "jobs").glob("*.json"), key=lambda p: int(p.stem)):
        j = json.loads(p.read_text())
        if j["name"] != CIRCUIT_NAME:
            continue
        jobs.append(
            {
                "index": j["index"],
                "job_id": j["job_id"],
                "isa_sha256": j["isa_sha256"],
                "config": j["config"],
                "shots": j["shots"],
                "finished": j["finished"],
                "finished_date": j["finished"].split("T")[0],
                "status": j["status"],
                "counts": dict(sorted(j["counts"].items())),
            }
        )
    return {
        "backend": plan["backend"],
        "batch": batch_dir.name,
        "jobs": jobs,
    }


def _resolution(counts: dict[str, int], n_count: int, a: int, big_n: int) -> dict | None:
    """The most frequent hardware outcome (config raw, pooled) that yields non-trivial factors."""
    for bits, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        m = int(bits, 2)
        r = order_from_shot(m, n_count, a, big_n)
        if r is None:
            continue
        fac = factors_from_order(a, r, big_n)
        if fac is None:
            continue
        return {
            "bitstring": bits,
            "count": n,
            "measured": m,
            "denominator": 2**n_count,
            "convergents": [[f.numerator, f.denominator] for f in convergents(m, 2**n_count)],
            "order": r,
            "factors": list(fac),
            "n": big_n,
            "a": a,
        }
    return None


def _notes(kind: str, a: int, big_n: int, backend: str) -> dict[str, str]:
    """Caption text for the hero, built from the data it describes (Phase 5 hero)."""
    return {
        "compiled": (
            f"This circuit is labelled {kind}: the multiplications for a = {a} mod {big_n} are "
            "built in, so the order is baked into the circuit. It shows the pipeline, not "
            "generic Shor."
        ),
        "hardware": f"{backend} ran the transpiled form of this circuit, not the gate list shown.",
        "success": "A shot counts as a success when continued fractions on it find the order.",
    }


def build_hero(batch_dir: Path, n_qubits_of_backend: int) -> dict:
    qc = build_circuit(CIRCUIT_NAME)
    meta = qc.metadata
    n_count = meta["n_count"]
    hw = _hardware(batch_dir)
    pooled: dict[str, int] = {}
    for j in hw["jobs"]:
        if j["config"] == "raw":
            for k, v in j["counts"].items():
                pooled[k] = pooled.get(k, 0) + v
    return {
        "circuit": {
            "name": CIRCUIT_NAME,
            "kind": meta["kind"],
            "n": meta["N"],
            "a": meta["a"],
            "n_count": n_count,
            "n_qubits": qc.num_qubits,
            "n_clbits": qc.num_clbits,
            "registers": [{"name": r.name, "size": r.size, "kind": "quantum"} for r in qc.qregs]
            + [{"name": r.name, "size": r.size, "kind": "classical"} for r in qc.cregs],
            "gates": _gates(qc),
        },
        "ideal": {
            "method": "exact statevector probabilities of the circuit above",
            "probabilities": _ideal_probabilities(qc, n_count),
        },
        "hardware": {
            **hw,
            "device_qubits": n_qubits_of_backend,
            "device_qubits_source": DEVICE_QUBITS_SOURCE,
            "pooled_raw_counts": dict(sorted(pooled.items())),
        },
        "notes": _notes(meta["kind"], meta["a"], meta["N"], hw["backend"]),
        "resolution": _resolution(pooled, n_count, meta["a"], meta["N"]),
    }
