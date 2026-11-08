"""Run the registry circuits on the FakeKingston noisy simulator -> results/noisy/<name>.json."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantum.circuits.registry import REQUIRED_NAMES, build_circuit  # noqa: E402
from quantum.run.noisy import run_noisy  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--names", default="", help="comma-separated circuit names (default: all)")
    ap.add_argument("--shots", type=int, default=8192)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument(
        "--reduced-reason",
        help="allow shots < 8192 and record why (adds reduced_shots_reason and prediction)",
    )
    args = ap.parse_args(argv)
    names = [n for n in args.names.split(",") if n] or list(REQUIRED_NAMES)
    for name in names:
        rec = run_noisy(
            name,
            build_circuit(name),
            shots=args.shots,
            seed_simulator=args.seed,
            reduced_reason=args.reduced_reason,
        )
        print(
            f"{name}: success={rec['success_probability']:.4f} "
            f"wilson=[{rec['wilson_95'][0]:.4f}, {rec['wilson_95'][1]:.4f}] "
            f"chance={rec['chance_baseline']:.4f} norm={rec['normalized_score']:.3f} "
            f"H={rec['hellinger_vs_ideal']:.3f} signal={rec['signal']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
