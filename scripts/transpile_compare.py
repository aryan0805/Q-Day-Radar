"""Compare transpiler choices on the target device: preset opt 3 vs the AI pass (local mode).

    uv run python scripts/transpile_compare.py [--seeds 1234 1235 1236 1237 1238]

Counts two-qubit gates (and depth) on FakeKingston for each registry circuit, with 5-seed
medians, and records which transpilation to keep per circuit. Uses NO QPU time and no cloud
service: the AI pass runs in local mode only (the cloud service is Premium-only). If the AI
pass cannot run, the reason is recorded and opt 3 is kept. Output:
``results/transpile/phase2-compare.json``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import qiskit  # noqa: E402
from qiskit import QuantumCircuit  # noqa: E402
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager  # noqa: E402

from quantum.backends import get_fake_backend  # noqa: E402
from quantum.circuits.registry import REQUIRED_NAMES, build_circuit  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "results" / "transpile" / "phase2-compare.json"
DEFAULT_SEEDS = (1234, 1235, 1236, 1237, 1238)


def _ai_pass_manager_factory(backend: Any) -> tuple[Callable[[int], Any] | None, str | None]:
    """Return (factory(seed) -> pass manager, None) or (None, reason it is unavailable)."""
    try:
        from qiskit_ibm_transpiler import generate_ai_pass_manager
    except ImportError as exc:
        return None, (
            f"qiskit-ibm-transpiler not importable here ({exc}). Probe 2026-11-08 with "
            "`uv run --with qiskit-ibm-transpiler`: 0.18.0 pulls qiskit-ibm-runtime down to "
            "0.45.1 (no FakeKingston) and its import fails under qiskit 2.6.2 with "
            "'No module named qiskit.synthesis.linear.linear_matrix_utils'. Kept opt 3."
        )

    def factory(seed: int) -> Any:
        return generate_ai_pass_manager(
            coupling_map=backend.coupling_map,
            ai_optimization_level=3,
            optimization_level=3,
            include_ai_synthesis=False,
            local_mode=True,
            seed_transpiler=seed,
        )

    return factory, None


def _measure(pm: Any, circuit: QuantumCircuit) -> dict[str, int]:
    isa = pm.run(circuit)
    return {"two_qubit_gates": isa.num_nonlocal_gates(), "depth": isa.depth()}


def _summary(per_seed: dict[int, dict[str, int]]) -> dict[str, Any]:
    twoq = [v["two_qubit_gates"] for v in per_seed.values()]
    depth = [v["depth"] for v in per_seed.values()]
    return {
        "two_qubit_gates_median": statistics.median(twoq),
        "two_qubit_gates_min": min(twoq),
        "two_qubit_gates_max": max(twoq),
        "depth_median": statistics.median(depth),
        "per_seed": {str(k): v for k, v in per_seed.items()},
    }


def compare(
    names: list[str], seeds: tuple[int, ...] = DEFAULT_SEEDS, *, skip_ai: bool = False
) -> dict[str, Any]:
    backend = get_fake_backend()
    ai_factory, ai_reason = (
        (None, "skipped by --skip-ai") if skip_ai else _ai_pass_manager_factory(backend)
    )
    circuits: dict[str, Any] = {}
    for name in names:
        circuit = build_circuit(name)
        base = {
            s: _measure(
                generate_preset_pass_manager(
                    optimization_level=3, backend=backend, seed_transpiler=s
                ),
                circuit,
            )
            for s in seeds
        }
        entry: dict[str, Any] = {"opt3": _summary(base), "ai": None, "ai_unavailable": ai_reason}
        chosen = "opt3"
        if ai_factory is not None:
            try:
                ai = {s: _measure(ai_factory(s), circuit) for s in seeds}
                entry["ai"], entry["ai_unavailable"] = _summary(ai), None
                if entry["ai"]["two_qubit_gates_median"] < entry["opt3"]["two_qubit_gates_median"]:
                    chosen = "ai"
            except Exception as exc:  # noqa: BLE001 - record why, keep opt 3
                entry["ai_unavailable"] = f"{type(exc).__name__}: {exc}"
        entry["chosen"] = chosen
        circuits[name] = entry
        print(
            f"{name}: opt3 median 2q={entry['opt3']['two_qubit_gates_median']} "
            f"ai={'n/a' if entry['ai'] is None else entry['ai']['two_qubit_gates_median']} "
            f"-> {chosen}",
            flush=True,
        )
    return {
        "backend": "fake_kingston",
        "seeds": list(seeds),
        "qiskit_version": qiskit.__version__,
        "ai_pass": {"mode": "local", "available": ai_factory is not None, "reason": ai_reason},
        "timestamp": datetime.now(UTC).isoformat(),
        "circuits": circuits,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    ap.add_argument("--names", default="", help="comma-separated (default: all 7)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--skip-ai", action="store_true")
    args = ap.parse_args(argv)
    names = [n for n in args.names.split(",") if n] or list(REQUIRED_NAMES)
    result = compare(names, tuple(args.seeds), skip_ai=args.skip_ai)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
