"""Qualtran costs -> results/estimate/qualtran/<case>.json.

1. same_circuit: the exact QASM stored for each QDK case (results/estimate/circuits/<sha>.qasm)
   is costed through QASM2 -> cirq -> bloq. Needs the QDK case file (run estimate_qdk.py first).
2. modexp_N<N>_a<a>: Qualtran ModExp at every scaling (N, a), built explicitly (2n exponent bits).
3. rsa2048_modexp: ModExp at a 2048-bit semiprime, three bases (cost is base-independent).
4. ecc256_ecadd: Qualtran ECAdd (symbolic n evaluated at n = 256), times 2n as a labelled
   projection (ECPhaseEstimateR itself has no costable decomposition in qualtran 0.7.0).
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantum.estimate import cases, common, qualtran_est  # noqa: E402

OUT = cases.OUT / "qualtran"
QDK = cases.OUT / "qdk"
SAME_CIRCUIT_MAX_BITS = 10


def same_circuit(case: str, write: bool = True) -> dict:
    q = json.loads((QDK / f"{case}.json").read_text())
    qasm = cases.read_qasm(q["circuit_sha256"])
    counts = qualtran_est.qualtran_counts_from_qasm(qasm)
    extra = {k: q[k] for k in ("circuit_sha256", "circuit_form", "classical_control_counted")} | {
        "source_kind": q["source_kind"]
    }
    rec = qualtran_est.qualtran_case(
        case,
        "same_circuit",
        counts,
        bloq="cirq_optree_to_cbloq(QASM2)",
        N=q["N"],
        base_a=q["base_a"],
        extra=extra,
    )
    if write:
        cases.write_json(OUT / f"{case}.json", rec)
    return rec


def modexp(spec: cases.Spec, write: bool = True) -> dict:
    counts = qualtran_est.qualtran_modexp_counts(spec.N, spec.a)
    rec = qualtran_est.qualtran_case(
        f"modexp_N{spec.N}_a{spec.a}", "bloq", counts, bloq="ModExp", N=spec.N, base_a=spec.a
    )
    if write:
        cases.write_json(OUT / f"{rec['case']}.json", rec)
    return rec


def rsa2048() -> dict:
    from sympy import nextprime

    p = nextprime(3 * 2**1022)
    q = nextprime(p + 1000)
    N = p * q
    assert N.bit_length() == 2048
    results = {a: qualtran_est.qualtran_modexp_counts(N, a) for a in (7, 11, 13)}
    base = results[7]
    same = all(r == base for r in results.values())
    rec = qualtran_est.qualtran_case(
        "rsa2048_modexp",
        "bloq",
        base,
        bloq="ModExp",
        N=N,
        base_a=7,
        extra={"bases_checked": sorted(results), "cost_independent_of_base": same},
    )
    cases.write_json(OUT / "rsa2048_modexp.json", rec)
    return rec


def ecc256() -> dict:
    import sympy
    from qualtran.bloqs.cryptography.ecc import ECAdd
    from qualtran.resource_counting import QECGatesCost, get_cost_value

    n = sympy.Symbol("n", positive=True, integer=True)
    bloq = ECAdd(n=n, mod=sympy.Symbol("p", positive=True, integer=True))
    cost = get_cost_value(bloq, QECGatesCost())
    qubits = int(sympy.sympify(bloq.signature.n_qubits()).subs(n, 256))
    at = {
        k: int(sympy.sympify(getattr(cost, k)).subs(n, 256))
        for k in ("toffoli", "and_bloq", "cswap", "t", "rotation")
    }

    class _C:  # a GateCounts-like view at n = 256
        toffoli, and_bloq, cswap, t, rotation = (
            at[k] for k in ("toffoli", "and_bloq", "cswap", "t", "rotation")
        )

    counts = qualtran_est.qualtran_counts_from_cost(_C, qubits)
    additions = 2 * 256  # point additions in full Shor ECDLP (Roetteler 2017, Sec. 1)
    rec = qualtran_est.qualtran_case(
        "ecc256_ecadd",
        "bloq",
        counts,
        bloq="ECAdd",
        N=None,
        base_a=None,
        extra={
            "n_field_bits": 256,
            "raw_cost_at_n256": at,
            "label": "single point addition (measured by Qualtran, symbolic n at 256)",
            "projection": {
                "label": "projection",
                "point_additions": additions,
                "literature_id": "roetteler2017_toffoli_p256",
                "toffoli_equiv": additions
                * common.toffoli_equiv(
                    toffoli=counts["toffoli"],
                    t=counts["t"],
                    rotations=counts["rotations"],
                    eps=common.ROTATION_EPS,
                ),
            },
        },
    )
    cases.write_json(OUT / "ecc256_ecadd.json", rec)
    return rec


def _task(job):
    kind, arg = job
    rec = {"same": same_circuit, "modexp": modexp}[kind](arg)
    return f"{rec['case']}: equiv={rec['toffoli_equiv']:.6g} qubits={rec['logical_qubits']}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--same-circuit-max-bits", type=int, default=SAME_CIRCUIT_MAX_BITS)
    ap.add_argument("--max-bits", type=int, default=cases.SCALING_BITS[-1])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--skip-big", action="store_true", help="skip rsa2048 and ecc256")
    args = ap.parse_args(argv)
    todo: list = []
    for p in sorted(QDK.glob("*.json")):
        q = json.loads(p.read_text())
        if q["n_bits"] is None or q["n_bits"] <= args.same_circuit_max_bits:
            todo.append(("same", q["case"]))
    todo += [("modexp", s) for s in cases.scaling_specs(args.max_bits)]
    print(f"{len(todo)} Qualtran cases")
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for line in pool.map(_task, todo):
            print(line, flush=True)
    if not args.skip_big:
        for fn in (rsa2048, ecc256):
            rec = fn()
            print(f"{rec['case']}: equiv={rec['toffoli_equiv']:.6g} qubits={rec['logical_qubits']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
