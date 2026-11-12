"""Phase 5 Lighthouse benchmark: the gate's own invocation, per build, median of 3 per screen.

Same call as scripts/gate.py p5_lighthouse (mobile defaults, performance and accessibility only,
--headless=new, median of 3), plus total blocking time. Lab data on a local server, not field data.
Every figure is printed from the Lighthouse JSON; nothing is typed.

    PYTHONPATH=. uv run python benchmarks/phase5-lighthouse.py label=<web dir> [label=<web dir> ...]

Writes benchmarks/phase5-lighthouse.json and benchmarks/phase5-lighthouse.md.
"""

from __future__ import annotations

import functools
import json
import statistics
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from tests.phase5.conftest import _Handler, _Server

ROOT = Path(__file__).resolve().parents[1]


def _commit(web: Path) -> str:
    """The commit a build came from: out/build.json (stamped by the build itself), else the
    checkout's HEAD. No local path is recorded."""
    import json
    import subprocess

    stamp = web / "out" / "build.json"
    if stamp.is_file():
        return json.loads(stamp.read_text())["commit"]
    r = subprocess.run(
        ["git", "-C", str(web), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return r.stdout.strip() or "unknown"


SCREENS = ("/", "/lab/", "/scaling/", "/inventory/")
RUNS = 3
# thresholds fixed in the Phase 5 brief before BUILD, repeated here only to print pass/fail
MIN = {"performance": 0.90, "accessibility": 1.00}
MAX_LCP_MS, MAX_CLS = 2000.0, 0.05


def one_run(web: Path, base: str, screen: str) -> dict:
    out = Path(tempfile.gettempdir()) / f"qday-lh-bench-{threading.get_ident()}.json"
    r = subprocess.run(
        [
            str(web / "node_modules" / ".bin" / "lighthouse"),
            base + screen,
            "--output=json",
            f"--output-path={out}",
            "--quiet",
            "--only-categories=performance,accessibility",
            "--chrome-flags=--headless=new",
        ],
        cwd=web,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"lighthouse failed on {screen}: {(r.stderr or '')[-300:]}")
    lh = json.loads(out.read_text())
    out.unlink()
    return {
        "performance": lh["categories"]["performance"]["score"],
        "accessibility": lh["categories"]["accessibility"]["score"],
        "lcp_ms": lh["audits"]["largest-contentful-paint"]["numericValue"],
        "cls": lh["audits"]["cumulative-layout-shift"]["numericValue"],
        "tbt_ms": lh["audits"]["total-blocking-time"]["numericValue"],
    }


def run(builds: dict[str, Path]) -> dict:
    res: dict = {
        "measured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runs_per_screen": RUNS,
        "method": "Lighthouse mobile defaults, performance+accessibility, --headless=new, "
        "local static server, median of 3 (the gate's invocation); lab data",
        "builds": {},
    }
    for label, web in builds.items():
        out = web / "out"
        _Handler.out_dir = out
        server = _Server(("127.0.0.1", 0), functools.partial(_Handler, directory=str(out)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        screens = {}
        for screen in SCREENS:
            runs = [one_run(web, base, screen) for _ in range(RUNS)]
            med = {k: statistics.median(r[k] for r in runs) for k in runs[0]}
            screens[screen] = {"runs": runs, "median": med}
            print(
                f"  {label} {screen}: {json.dumps({k: round(v, 3) for k, v in med.items()})}",
                flush=True,
            )
        server.shutdown()
        server.server_close()
        res["builds"][label] = {"commit": _commit(web), "screens": screens}
    return res


def markdown(res: dict) -> str:
    lines = [
        "# Phase 5 Lighthouse (mobile, local, median of 3)",
        "",
        f"Measured {res['measured_at']}. {res['method']}.",
        f"Thresholds: performance >= {MIN['performance']}, accessibility = {MIN['accessibility']}, "
        f"LCP < {MAX_LCP_MS:.0f} ms, CLS < {MAX_CLS}.",
        "",
        "| build | screen | performance | accessibility | LCP | CLS | TBT | meets thresholds |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for label, data in res["builds"].items():
        for screen, s in data["screens"].items():
            m = s["median"]
            ok = (
                m["performance"] >= MIN["performance"]
                and m["accessibility"] >= MIN["accessibility"]
                and m["lcp_ms"] < MAX_LCP_MS
                and m["cls"] < MAX_CLS
            )
            lines.append(
                f"| {label} | {screen} | {m['performance']:.2f} | {m['accessibility']:.2f} "
                f"| {m['lcp_ms']:.0f} ms | {m['cls']:.3f} | {m['tbt_ms']:.0f} ms "
                f"| {'yes' if ok else 'NO'} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    builds = {}
    for arg in argv:
        label, _, path = arg.partition("=")
        builds[label] = Path(path).resolve()
    if not builds:
        print(__doc__)
        return 2
    res = run(builds)
    (ROOT / "benchmarks" / "phase5-lighthouse.json").write_text(json.dumps(res, indent=2) + "\n")
    md = markdown(res)
    (ROOT / "benchmarks" / "phase5-lighthouse.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
