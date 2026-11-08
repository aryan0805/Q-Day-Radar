"""Run Phase 3 end to end (QDK -> Qualtran -> compare -> scenarios), or verify the fast cases.

  uv run python scripts/estimate_all.py            # compute everything, write results/estimate/
  uv run python scripts/estimate_all.py --verify   # recompute registry + n <= 6 cases, the three
                                                   # comparison files and scenarios.json in
                                                   # memory; exit 1 if any file would change

Verify writes nothing except content-addressed QASM files that already exist.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import estimate_compare  # noqa: E402
import estimate_qdk  # noqa: E402
import estimate_qualtran  # noqa: E402
import estimate_scenarios  # noqa: E402

from quantum.circuits.registry import REQUIRED_NAMES  # noqa: E402
from quantum.estimate import cases, study  # noqa: E402

FAST_BITS = 6


def _same(path: Path, fresh: dict) -> bool:
    if not path.exists():
        print(f"MISSING {path}")
        return False
    old = json.loads(path.read_text())
    new = json.loads(json.dumps(fresh, sort_keys=True))
    if old != new:
        print(f"CHANGED {path}")
        return False
    return True


def verify() -> int:
    ok = True
    for name in REQUIRED_NAMES:
        ok &= _same(cases.OUT / "qdk" / f"{name}.json", estimate_qdk._registry(name))
        ok &= _same(
            cases.OUT / "qualtran" / f"{name}.json", estimate_qualtran.same_circuit(name, False)
        )
    for k in (2, 3, 4, 5):
        rec = estimate_qdk._nopeel(k)
        ok &= _same(cases.OUT / "qdk" / f"{rec['case']}.json", rec)
    for spec in cases.scaling_specs(FAST_BITS):
        ok &= _same(cases.OUT / "qdk" / f"{spec.case}.json", estimate_qdk._scaling(spec))
        ok &= _same(
            cases.OUT / "qualtran" / f"{spec.case}.json",
            estimate_qualtran.same_circuit(spec.case, False),
        )
        fid = f"modexp_N{spec.N}_a{spec.a}"
        ok &= _same(cases.OUT / "qualtran" / f"{fid}.json", estimate_qualtran.modexp(spec, False))
    for gz in sorted((cases.OUT / "circuits").glob("*.qasm.gz")):
        sha = gz.name.removesuffix(".qasm.gz")
        try:
            cases.read_qasm(sha)  # decompress, hash, compare with the file name
        except RuntimeError as exc:
            print(f"BAD CIRCUIT {exc}")
            ok = False
    qdk, qt = study.load("qdk"), study.load("qualtran")
    scal = study.fits(qdk, qt)
    ok &= _same(cases.OUT / "crosscheck.json", study.crosscheck(qdk, qt))
    ok &= _same(cases.OUT / "scaling.json", scal)
    ok &= _same(cases.OUT / "calibration.json", study.calibration(qdk, qt, scal))
    ok &= _same(cases.OUT / "scenarios.json", estimate_scenarios.build())
    print("verify:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args(argv)
    if args.verify:
        return verify()
    jobs = ["--jobs", str(args.jobs)]
    estimate_qdk.main(jobs)
    estimate_qualtran.main(jobs)
    estimate_compare.main()
    estimate_scenarios.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
