"""Per same_circuit case: reference gate counts (reviewer's own QASM parser) vs QDK vs Qualtran.

Prints a table and writes benchmarks/phase3-tool-deviation.json. Every number comes from the
result files and the stored QASM; nothing is typed.
Run: uv run python benchmarks/phase3-tool-deviation.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.phase3 import reference as ref  # noqa: E402


def main() -> int:
    rows = [
        r
        for r in json.loads((ref.EST / "crosscheck.json").read_text())["cases"]
        if r["kind"] == "same_circuit"
    ]
    qdk, qt = ref.cases("qdk"), ref.cases("qualtran")
    out = []
    print(f"{'case':34} {'tool':8} {'T':>8} {'rot':>8} {'ccx':>8} {'equiv':>12} {'dev vs ref':>11}")
    for row in rows:
        a, b = qdk[row["qdk"]], qt[row["qualtran"]]
        text = ref.read_circuit(a["circuit_sha256"])
        assert hashlib.sha256(text.encode()).hexdigest() == a["circuit_sha256"]
        r = ref.qasm_counts(text)
        k = a["rotation_t_cost"]
        want = ref.counts_equiv(r, k)
        entries = {
            "reference": (r["t"], r["rotations"], r["ccx"], want),
            "qdk": (
                a["logical_counts"]["t_count"],
                a["logical_counts"]["rotation_count"],
                a["logical_counts"]["ccz_count"] + a["logical_counts"]["ccix_count"],
                a["toffoli_equiv"],
            ),
            "qualtran": (
                b["counts"]["t"],
                b["counts"]["rotations"],
                b["counts"]["toffoli"],
                b["toffoli_equiv"],
            ),
        }
        rec = {"case": row["case"], "rotation_t_cost": k}
        for tool, (t, rot, ccx, eq) in entries.items():
            dev = (eq - want) / want if want else None
            rec[tool] = {
                "t": t,
                "rotations": rot,
                "ccx": ccx,
                "toffoli_equiv": eq,
                "deviation_vs_reference": dev,
                "d_t": t - r["t"],
                "d_rotations": rot - r["rotations"],
            }
            print(
                f"{row['case']:34} {tool:8} {t:8d} {rot:8d} {ccx:8d} {eq:12.6g} "
                f"{'' if tool == 'reference' else f'{dev:+.2%}':>11}"
            )
        out.append(rec)
    (ROOT / "benchmarks" / "phase3-tool-deviation.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
