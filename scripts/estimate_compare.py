"""Cross-check, scaling fits and calibration -> results/estimate/*.json (three files).

Reads only the per-case files under results/estimate/{qdk,qualtran}/.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantum.estimate import cases, study  # noqa: E402


def main() -> int:
    qdk = study.load("qdk")
    qt = study.load("qualtran")
    cross = study.crosscheck(qdk, qt)
    scal = study.fits(qdk, qt)
    cal = study.calibration(qdk, qt, scal)
    cases.write_json(cases.OUT / "crosscheck.json", cross)
    cases.write_json(cases.OUT / "scaling.json", scal)
    cases.write_json(cases.OUT / "calibration.json", cal)
    for kind in ("same_circuit", "same_function"):
        rows = [r for r in cross["cases"] if r["kind"] == kind]
        worst = max(r["ratio_toffoli_equiv"] for r in rows)
        print(f"{kind}: {len(rows)} cases, max toffoli_equiv ratio {worst:.4g}")
    for f in scal["fits"]:
        print(
            f"{f['estimator']:24s} {f['quantity']:15s} {f['model']:9s} exp={f['exponent']:.3f} "
            f"r2={f['r2']:.5f} holdout_err={f['holdout']['rel_error']:.3g} "
            f"n=2048 -> {f['extrapolated']['value']:.4g}"
        )
    for c in cal["comparisons"]:
        print(
            f"{c['target']:7s} {c['estimator'][:44]:44s} {c['quantity']:20s} ratio={c['ratio']:.3g}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
