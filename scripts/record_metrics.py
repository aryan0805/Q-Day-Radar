"""Regenerate results/metrics/<name>.json for every registry circuit (ideal simulator only)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantum.circuits.registry import build_all  # noqa: E402
from quantum.metrics import record_circuit_metrics  # noqa: E402


def main() -> int:
    for name, circuit in build_all().items():
        rec = record_circuit_metrics(name, circuit)
        print(
            f"{name}: {rec['kind']} 2q={rec['two_qubit_gates']} "
            f"success={rec['success_probability']:.4f} theory={rec['theoretical_success']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
