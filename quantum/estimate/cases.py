"""Which circuits get costed: the registry plus a generic-Beauregard scaling family.

The family uses the existing builder at other (N, a); nothing here touches the registry.
N is the smallest product of two distinct odd primes with the given bit length; the bases are
the smallest coprime a in [2, N-2], and at least one has multiplicative order > 2 (P005).
"""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass
from pathlib import Path

from qiskit import QuantumCircuit, qasm2
from sympy import isprime

from quantum.classical.postprocess import classical_order
from quantum.estimate import common

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "estimate"
SCALING_BITS = tuple(range(4, 15))  # 4..14
BASES_PER_SIZE = 4


@dataclass(frozen=True)
class Spec:
    case: str
    N: int
    a: int


def semiprime(n_bits: int) -> int:
    """Smallest N of exactly n_bits bits that is a product of two distinct odd primes."""
    for N in range(2 ** (n_bits - 1) | 1, 2**n_bits, 2):
        for p in range(3, math.isqrt(N) + 1, 2):
            if N % p == 0:
                if isprime(p) and isprime(N // p) and N // p != p:
                    return N
                break
    raise ValueError(f"no semiprime with {n_bits} bits")


def bases(N: int, k: int = BASES_PER_SIZE) -> list[int]:
    out = [a for a in range(2, N - 1) if math.gcd(a, N) == 1][:k]
    if not any(classical_order(a, N) > 2 for a in out):
        raise ValueError(f"all bases of order <= 2 for N={N}")
    return out


def scaling_specs(max_bits: int = SCALING_BITS[-1]) -> list[Spec]:
    specs = []
    for n in SCALING_BITS:
        if n > max_bits:
            continue
        N = semiprime(n)
        specs += [Spec(f"beauregard_N{N}_a{a}", N, a) for a in bases(N)]
    return specs


def build_scaling(spec: Spec) -> QuantumCircuit:
    from quantum.circuits.beauregard import build_shor

    return build_shor(spec.N, spec.a)


def form_qasm_sha(qc: QuantumCircuit) -> tuple[QuantumCircuit, str, str]:
    """Estimation form, the exact QASM2 handed to both tools, and its sha256."""
    form = common.estimation_form(qc)
    qasm = qasm2.dumps(form)
    return form, qasm, common.circuit_sha256(qasm)


def circuit_extra(qasm: str, sha: str, source_kind: str) -> dict:
    """Fields every same-circuit file carries (both tools)."""
    return {
        "circuit_sha256": sha,
        "circuit_form": "non_dynamic",
        "classical_control_counted": "executed",
        "source_kind": source_kind,
    }


def qasm_path(sha: str) -> Path:
    return OUT / "circuits" / f"{sha}.qasm.gz"


def read_qasm(sha: str) -> str:
    """Stored QASM for a hash; checks that it hashes to its own name."""
    qasm = gzip.decompress(qasm_path(sha).read_bytes()).decode()
    if common.circuit_sha256(qasm) != sha:
        raise RuntimeError(f"{qasm_path(sha)} does not hash to its name")
    return qasm


def store_qasm(qasm: str, sha: str) -> Path:
    """Write <sha>.qasm.gz (sha = hash of the UNCOMPRESSED text); mtime 0 keeps bytes stable."""
    path = qasm_path(sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if read_qasm(sha) != qasm:
            raise RuntimeError(f"{path} exists with different content")
    else:
        path.write_bytes(gzip.compress(qasm.encode(), compresslevel=9, mtime=0))
    return path


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
