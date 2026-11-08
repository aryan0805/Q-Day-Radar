"""Markdown tables for tests/phase3/AUDIT.md, printed from the result files (nothing typed).

Every number is labelled measured / extrapolated / projection / literature by where it comes from.
Run: uv run python benchmarks/phase3-audit-tables.py > /tmp/audit-tables.md
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.phase3 import reference as ref  # noqa: E402


def g(x: float) -> str:
    return f"{x:.4g}"


def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def literature() -> str:
    fc = json.loads(ref.FACTCHECK.read_text())
    rows = [
        [
            e["id"],
            e["target"],
            e["quantity"],
            e["value"],
            e["units"],
            "literature",
            fc[e["id"]]["status"],
        ]
        for e in ref.literature()
    ]
    return table(["id", "target", "quantity", "value", "units", "label", "fact-check"], rows)


def same_circuit_deviation() -> str:
    d = json.loads((ROOT / "benchmarks" / "phase3-tool-deviation.json").read_text())
    n_dev = {
        t: sum(
            1
            for r in d
            if r[t]["d_t"] or r[t]["d_rotations"] or abs(r[t]["deviation_vs_reference"]) > 1e-12
        )
        for t in ("qdk", "qualtran")
    }
    f = json.loads((ROOT / "benchmarks" / "phase3-qdk-fusion.json").read_text())
    dev = [o["deviation_vs_reference"] for o in f]
    return (
        f"same_circuit cases: {len(d)}; cases where QDK (skip_transpilation) differs from the "
        f"reference parser: {n_dev['qdk']}; Qualtran: {n_dev['qualtran']} (measured).\n\n"
        f"QDK default transpilation on the same QASM: differs in (T, rotations) in "
        f"{sum(1 for o in f if o['d_t'] or o['d_rotations'])} of {len(f)} cases; toffoli_equiv "
        f"deviation (per-case median over {f[0]['runs']} runs; the transpilation is not "
        f"reproducible) min {min(dev):+.2%}, median {statistics.median(dev):+.2%}, "
        f"max {max(dev):+.2%} (measured)."
    )


def same_function() -> str:
    rows = [
        r
        for r in ref.load_json(ref.EST / "crosscheck.json")["cases"]
        if r["kind"] == "same_function"
    ]
    qdk = ref.cases("qdk")
    by_n: dict[int, list[dict]] = {}
    for r in rows:
        by_n.setdefault(qdk[r["qdk"]]["n_bits"], []).append(r)
    out = []
    for n in sorted(by_n):
        eq = [r["ratio_toffoli_equiv"] for r in by_n[n]]
        q = [r["ratio_logical_qubits"] for r in by_n[n]]
        out.append(
            [
                n,
                len(eq),
                g(min(eq)),
                g(statistics.median(eq)),
                g(max(eq)),
                g(statistics.median(q)),
                "measured",
            ]
        )
    return table(
        ["n_bits", "bases", "equiv ratio min", "median", "max", "qubit ratio median", "label"], out
    )


def scaling() -> str:
    fits = ref.load_json(ref.EST / "scaling.json")["fits"]
    rows = []
    for f in fits:
        e = f["extrapolated"]
        rows.append(
            [
                f["estimator"],
                f["quantity"],
                f["model"],
                "yes" if f.get("selected") else "",
                g(f["exponent"]) if f["model"] == "power_law" else "",
                g(f["r2"]),
                g(max(abs(r["rel"]) for r in f["residuals"])),
                g(f["holdout"]["rel_error"]),
                g(e["value"]),
                (f"{g(e['low'])} .. {g(e['high'])}" if "low" in e else ""),
                "extrapolated",
            ]
        )
    return table(
        [
            "estimator",
            "quantity",
            "model",
            "selected",
            "exponent",
            "r2",
            "max |rel|",
            "holdout",
            "n=2048 value",
            "bracket",
            "label",
        ],
        rows,
    )


def calibration() -> str:
    rows = [
        [
            r["target"],
            r["estimator"],
            r["quantity"],
            g(r["ours"]),
            r["literature_id"],
            g(r["literature_value"]),
            g(r["ratio"]),
            r["method"].split(":")[0],
        ]
        for r in ref.load_json(ref.EST / "calibration.json")["comparisons"]
    ]
    return table(
        [
            "target",
            "ours from",
            "quantity",
            "ours",
            "literature id",
            "literature",
            "ours/lit",
            "label",
        ],
        rows,
    )


def scenarios() -> str:
    s = ref.load_json(ref.EST / "scenarios.json")
    rows = []
    for t in ref.TARGETS:
        for name in ref.SCENARIOS:
            r = s["targets"][t]["by_scenario"][name]
            rows.append(
                [
                    t,
                    name,
                    g(r["logical_qubits"]),
                    g(r["physical_qubits"]),
                    g(r["runtime_seconds"]),
                    r["code_distance"],
                    "literature counts -> physical model (computed)",
                ]
            )
    return table(["target", "scenario", "logical", "physical", "runtime s", "d", "label"], rows)


def main() -> int:
    for title, fn in (
        ("Literature (typed only in literature.yaml)", literature),
        ("same_circuit vs the reference parser", same_circuit_deviation),
        ("same_function: QDK Beauregard vs Qualtran ModExp", same_function),
        ("Scaling fits", scaling),
        ("Calibration", calibration),
        ("Scenarios", scenarios),
    ):
        print(f"### {title}\n\n{fn()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
