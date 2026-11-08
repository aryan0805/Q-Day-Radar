"""Phase 1 (P005): 2q-gate spread over base a for the HONEST generic Beauregard Shor circuit."""

from __future__ import annotations

import datetime as dt
import json
import statistics
import subprocess
from math import gcd
from pathlib import Path

import qiskit
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from quantum.backends import get_fake_backend
from quantum.circuits.beauregard import build_shor

ROOT = Path(__file__).resolve().parent.parent
BENCH = Path(__file__).resolve().parent
SEEDS = [1234, 1235, 1236, 1237, 1238]
OPT = 3
EXPECTED_CSWAP = {15: 28, 21: 45}
REGISTRY = {15: 7, 21: 2}
DATE = "2026-11-07"


def sh(*cmd: str) -> str:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def order(a: int, n: int) -> int:
    """Brute-force multiplicative order; a table label only, never a circuit input."""
    r, x = 1, a % n
    while x != 1:
        x = x * a % n
        r += 1
    return r


def main() -> None:
    backend = get_fake_backend()
    data: dict = {}
    deviations = []
    for n in (15, 21):
        rows = []
        for a in range(2, n):
            if gcd(a, n) != 1:
                continue
            qc = build_shor(n, a)
            kind = qc.metadata["kind"]
            cswap = qc.count_ops().get("cswap", 0)
            if kind != "generic":
                deviations.append(f"N={n} a={a}: kind={kind}")
            if cswap != EXPECTED_CSWAP[n]:
                deviations.append(f"N={n} a={a}: cswap={cswap} expected {EXPECTED_CSWAP[n]}")
            per_seed, depth = {}, None
            for s in SEEDS:
                out = generate_preset_pass_manager(
                    optimization_level=OPT, backend=backend, seed_transpiler=s
                ).run(qc)
                per_seed[s] = out.num_nonlocal_gates()
                if s == SEEDS[0]:
                    depth = out.depth()
            v = list(per_seed.values())
            rows.append(
                {
                    "a": a, "order": order(a, n), "kind": kind, "cswap": cswap,
                    "twoq_per_seed": per_seed, "twoq_seed1234": per_seed[1234],
                    "twoq_min": min(v), "twoq_median": statistics.median(v),
                    "twoq_max": max(v), "depth_seed1234": depth,
                }
            )
            print(n, rows[-1], flush=True)
        meds = [r["twoq_median"] for r in rows]
        reg = next(r for r in rows if r["a"] == REGISTRY[n])
        ranked = sorted(meds)
        by_order = {}
        for r in rows:
            by_order.setdefault(r["order"], []).append(r["twoq_median"])
        data[str(n)] = {
            "rows": rows,
            "min": min(meds), "median": statistics.median(meds), "max": max(meds),
            "spread_pct": (max(meds) / min(meds) - 1) * 100,
            "registry_a": REGISTRY[n], "registry_median": reg["twoq_median"],
            "registry_rank_ascending": ranked.index(reg["twoq_median"]) + 1,
            "registry_rank_ties_below": sum(m < reg["twoq_median"] for m in meds) + 1,
            "registry_rank_ties_above": sum(m <= reg["twoq_median"] for m in meds),
            "n_bases": len(rows),
            "mean_median_by_order": {
                str(k): {"mean": statistics.mean(x), "bases": len(x)}
                for k, x in sorted(by_order.items())
            },
        }
    result = {
        "name": "phase1-spread-over-a",
        "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "git_head": sh("git", "rev-parse", "HEAD"),
        "git_status_quantum": sh("git", "status", "--short", "quantum"),
        "qiskit_version": qiskit.__version__,
        "optimization_level": OPT, "seeds": SEEDS, "backend": "FakeKingston",
        "circuit": "honest generic build_shor(N, a), defaults",
        "cswap_deviations": deviations,
        "results": data,
    }
    txt = json.dumps(result, indent=2)
    (BENCH / "phase1-spread-over-a.json").write_text(txt + "\n")
    (BENCH / "results").mkdir(exist_ok=True)
    (BENCH / "results" / f"phase1-spread-over-a-{DATE}.json").write_text(txt + "\n")

    md = [
        "# Phase 1 spread over base a (P005)",
        "",
        "Honest generic Beauregard Shor circuit (`build_shor(N, a)`, defaults), "
        "optimization level 3, "
        "FakeKingston. Registry bases are a=7 (N=15) and a=2 (N=21). Order r is a label only. "
        f"Seeds {SEEDS}. Qiskit {qiskit.__version__}. HEAD {result['git_head'][:10]}; "
        "`git status --short quantum`: "
        + ("clean." if not result["git_status_quantum"] else "dirty (see JSON)."),
        "",
        "cswap deviations: " + ("; ".join(deviations) if deviations else "none"),
    ]
    for n, d in data.items():
        md += [
            "", f"## N={n}", "",
            "| a | r | cswap | 2q seed1234 | 2q min | 2q median | 2q max | depth |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in d["rows"]:
            md.append(
                f"| {r['a']} | {r['order']} | {r['cswap']} | {r['twoq_seed1234']} "
                f"| {r['twoq_min']} "
                f"| {r['twoq_median']} | {r['twoq_max']} | {r['depth_seed1234']} |"
            )
        md += [
            "",
            f"- Per-base seed-median over {d['n_bases']} bases: min {d['min']}, "
            f"median {d['median']}, "
            f"max {d['max']}",
            f"- Spread (max/min - 1): {d['spread_pct']:.1f}%",
            f"- Registry base a={d['registry_a']}: median {d['registry_median']}; rank "
            f"{d['registry_rank_ties_below']}-{d['registry_rank_ties_above']} "
            f"(ascending, 1 = cheapest, of {d['n_bases']}; range reflects ties)",
            "- Mean of per-base medians by order:",
        ]
        for k, v in d["mean_median_by_order"].items():
            md.append(f"  - r={k}: {v['mean']:.1f} ({v['bases']} bases)")
    (BENCH / "phase1-spread-over-a.md").write_text("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
