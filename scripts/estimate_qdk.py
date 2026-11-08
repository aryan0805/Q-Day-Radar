"""QDK logical counts for the registry circuits and the generic-Beauregard scaling family.

Every circuit is first turned into the common estimation form (non-dynamic, shared basis,
classically controlled gates counted as executed); the exact QASM is stored under
results/estimate/circuits/<sha256>.qasm and its hash is written into the case file.
Writes results/estimate/qdk/<case>.json. Existing files are kept unless --force.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantum.circuits.registry import REQUIRED_NAMES, build_circuit  # noqa: E402
from quantum.estimate import cases, qdk  # noqa: E402

OUT = cases.OUT / "qdk"


def _registry(name: str) -> dict:
    qc = build_circuit(name)
    meta = qc.metadata
    form, qasm, sha = cases.form_qasm_sha(qc)
    cases.store_qasm(qasm, sha)
    N, a = meta.get("N"), meta.get("a")
    return qdk.qdk_case(
        name,
        form,
        kind=meta["kind"],
        N=N,
        base_a=a,
        extra=cases.circuit_extra(qasm, sha, meta["kind"]),
    )


def _nopeel(k: int) -> dict:
    """Toy-SPN Grover with peel_last_sbox=False: the AES-projection input (P1 audit F5)."""
    from quantum.circuits.grover_present import build_grover
    from quantum.circuits.registry import grover_pairs

    qc = build_grover(k, grover_pairs(k), peel_last_sbox=False)
    form, qasm, sha = cases.form_qasm_sha(qc)
    cases.store_qasm(qasm, sha)
    return qdk.qdk_case(
        f"grover_present_k{k}_nopeel",
        form,
        kind="generic",
        N=None,
        base_a=None,
        extra={**cases.circuit_extra(qasm, sha, "generic"), "peel_last_sbox": False},
    )


def _scaling(spec: cases.Spec) -> dict:
    qc = cases.build_scaling(spec)
    form, qasm, sha = cases.form_qasm_sha(qc)
    cases.store_qasm(qasm, sha)
    return qdk.qdk_case(
        spec.case,
        form,
        kind=qc.metadata["kind"],
        N=spec.N,
        base_a=spec.a,
        extra=cases.circuit_extra(qasm, sha, qc.metadata["kind"]),
    )


def _run(job: tuple[str, object]) -> str:
    kind, arg = job
    rec = {"registry": _registry, "scaling": _scaling, "nopeel": _nopeel}[kind](arg)
    cases.write_json(OUT / f"{rec['case']}.json", rec)
    return f"{rec['case']}: equiv={rec['toffoli_equiv']:.6g} counts={rec['logical_counts']}"


def _case_id(kind: str, arg) -> str:
    return {"registry": lambda a: a, "nopeel": lambda a: f"grover_present_k{a}_nopeel"}.get(
        kind, lambda a: a.case
    )(arg)


def jobs(which: str, max_bits: int, force: bool) -> list[tuple[str, object]]:
    todo: list[tuple[str, object]] = []
    if which in ("registry", "all"):
        todo += [("registry", n) for n in REQUIRED_NAMES]
    if which in ("registry", "all"):
        todo += [("nopeel", k) for k in (2, 3, 4, 5)]
    if which in ("scaling", "all"):
        todo += [("scaling", s) for s in cases.scaling_specs(max_bits)]
    if not force:
        todo = [(k, a) for k, a in todo if not (OUT / f"{_case_id(k, a)}.json").exists()]
    return todo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--which", choices=["registry", "scaling", "all"], default="all")
    ap.add_argument("--max-bits", type=int, default=cases.SCALING_BITS[-1])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    todo = jobs(args.which, args.max_bits, args.force)
    todo.sort(key=lambda j: j[1].N.bit_length() if j[0] == "scaling" else 0)
    print(f"{len(todo)} cases to cost")
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for line in pool.map(_run, todo):
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
