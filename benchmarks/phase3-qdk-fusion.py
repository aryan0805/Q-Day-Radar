"""How much QDK's DEFAULT Qiskit transpilation would move each same_circuit count.

Our wrapper calls QDK with skip_transpilation=True. This script costs the identical stored QASM
with QDK's default backend as well and compares both with the reference parser
(tests/phase3/reference.py). Writes benchmarks/phase3-qdk-fusion.json. Nothing is typed.
Run: uv run python benchmarks/phase3-qdk-fusion.py
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.phase3 import reference as ref  # noqa: E402

# QDK's default transpilation is not reproducible run to run even with a seed (the maximum
# deviation moved between runs), so every case is costed REPEATS times; the median is reported
# together with the min and max over runs.
SEED = 20261108
REPEATS = 5


def main() -> int:
    warnings.filterwarnings("ignore")
    from qiskit import QuantumCircuit
    from qsharp.interop.qiskit import ResourceEstimatorBackend

    rows = [
        r
        for r in json.loads((ref.EST / "crosscheck.json").read_text())["cases"]
        if r["kind"] == "same_circuit"
    ]
    qdk = ref.cases("qdk")
    out = []
    for row in rows:
        c = qdk[row["qdk"]]
        text = ref.read_circuit(c["circuit_sha256"])
        want = ref.qasm_counts(text)
        k = c["rotation_t_cost"]
        # Qiskit's strict QASM2 loader rejects a register named like the gate `x`
        qc = QuantumCircuit.from_qasm_str(re.sub(r"\bx\[", "xr[", text))
        runs = []
        for _ in range(REPEATS):
            lc = ResourceEstimatorBackend().run(qc, seed_transpiler=SEED).result()["logicalCounts"]
            eq = lc["cczCount"] + lc["ccixCount"] + lc["tCount"] / 4 + lc["rotationCount"] * k / 4
            runs.append((lc, eq))
        ref_eq = ref.counts_equiv(want, k)
        devs = [(eq - ref_eq) / ref_eq for _, eq in runs]
        lc, eq = runs[0]
        out.append(
            {
                "case": row["case"],
                "reference": want,
                "qdk_default": {
                    "t": lc["tCount"],
                    "rotations": lc["rotationCount"],
                    "ccx": lc["cczCount"] + lc["ccixCount"],
                    "toffoli_equiv": eq,
                },
                "d_t": lc["tCount"] - want["t"],
                "d_rotations": lc["rotationCount"] - want["rotations"],
                "deviation_vs_reference": statistics.median(devs),
                "deviation_runs_min": min(devs),
                "deviation_runs_max": max(devs),
                "runs": REPEATS,
                "our_wrapper_toffoli_equiv": c["toffoli_equiv"],
                "reference_toffoli_equiv": ref_eq,
            }
        )
    dev = [o["deviation_vs_reference"] for o in out]
    print(
        f"cases: {len(out)}; differing from the reference in (T, rotations): "
        f"{sum(1 for o in out if o['d_t'] or o['d_rotations'])}"
    )
    print(
        f"toffoli_equiv deviation of QDK default vs reference: min {min(dev):+.2%}, "
        f"median {statistics.median(dev):+.2%}, max {max(dev):+.2%}"
    )
    spread = max(o["deviation_runs_max"] - o["deviation_runs_min"] for o in out)
    print(f"largest spread of one case's deviation over {REPEATS} runs: {spread:.2%}")
    same = sum(
        1 for o in out if abs(o["our_wrapper_toffoli_equiv"] - o["reference_toffoli_equiv"]) < 1e-9
    )
    print(f"our wrapper (skip_transpilation) equals the reference in {same} of {len(out)} cases")
    (ROOT / "benchmarks" / "phase3-qdk-fusion.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
