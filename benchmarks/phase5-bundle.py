"""Phase 5 bundle benchmark: the JS a visitor fetches, before and after an interaction.

Every figure is printed by this script from real builds (nothing typed). For each build it loads
"/" in Chromium at 390 px, with no interaction, waits for network idle plus 5 s, and sums gzip -9
of every JS response body and every executable inline script; then it scrolls once and measures
again. It does this in normal and in reduced motion. The static count is what the gate computes:
gzip -9 of the scripts index.html names. The measuring code is tests/phase5/pagetools.py, the same
code the `bundle` tests assert with.

    PYTHONPATH=. uv run python benchmarks/phase5-bundle.py before=<web dir> after=<web dir> ...

Writes benchmarks/phase5-bundle.json and benchmarks/phase5-bundle.md.
"""

from __future__ import annotations

import functools
import json
import re
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import sync_playwright

from tests.phase5.conftest import _Handler, _Server
from tests.phase5.pagetools import (
    BUDGET_BYTES,
    gsap_requested,
    gz9,
    idle_without_interacting,
    script_report,
    total_gz,
)

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


MOBILE = {"width": 390, "height": 844}


def static_count(out: Path) -> int:
    html = (out / "index.html").read_text(encoding="utf-8")
    srcs = {
        s.lstrip("/").split("?")[0] for s in re.findall(r"<script[^>]*\bsrc=[\"']([^\"']+)", html)
    }
    return sum(gz9((out / s).read_bytes()) for s in srcs)


def measure(browser, base: str, reduced: bool) -> dict:  # noqa: ANN001
    ctx = browser.new_context(
        viewport=MOBILE, reduced_motion="reduce" if reduced else "no-preference"
    )
    page = ctx.new_page()
    page.qday = SimpleNamespace(responses=[], requests=[])
    page.on("response", lambda r: page.qday.responses.append(r))
    page.on("request", lambda r: page.qday.requests.append(r.url))
    page.goto(base + "/", wait_until="load")
    idle_without_interacting(page)
    before = script_report(page)
    foreign_before = [u for u in page.qday.requests if not u.startswith(base)]
    page.mouse.move(100, 300)
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(2500)
    page.wait_for_load_state("networkidle")
    after = script_report(page)
    gsap = [s for s in after if s.gsap]
    ctx.close()
    return {
        "before_interaction_gz_bytes": total_gz(before),
        "before_interaction_scripts": len(before),
        "gsap_before_interaction": bool(gsap_requested(before)),
        "after_one_scroll_gz_bytes": total_gz(after),
        "after_one_scroll_scripts": len(after),
        "added_by_one_scroll_gz_bytes": total_gz(after) - total_gz(before),
        "gsap_after_one_scroll": bool(gsap),
        "gsap_chunk_gz_bytes": sum(s.gz for s in gsap),
        "other_origin_requests_before": foreign_before,
        "other_origin_requests_total": [u for u in page.qday.requests if not u.startswith(base)],
    }


def run(builds: dict[str, Path]) -> dict:
    result: dict = {
        "measured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "budget_gz_bytes": BUDGET_BYTES,
        "viewport": MOBILE,
        "method": "gzip -9 of each JS response body and executable inline script; network idle "
        "+ 5 s with no interaction, then one wheel scroll",
        "builds": {},
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for label, web in builds.items():
            out = web / "out"
            handler = functools.partial(_Handler, directory=str(out))
            _Handler.out_dir = out
            server = _Server(("127.0.0.1", 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            result["builds"][label] = {
                "commit": _commit(web),
                "static_index_html_gz_bytes": static_count(out),
                "normal_motion": measure(browser, base, reduced=False),
                "reduced_motion": measure(browser, base, reduced=True),
            }
            server.shutdown()
            server.server_close()
        browser.close()
    return result


def markdown(res: dict) -> str:
    b = res["budget_gz_bytes"]
    lines = [
        "# Phase 5 bundle: JS fetched on the home page",
        "",
        f"Measured {res['measured_at']} in Chromium at {res['viewport']['width']} px. "
        f"{res['method']}. Budget: {b:,} B before the first interaction.",
        "",
        "| build | mode | static (index.html) | before interaction | GSAP before "
        "| after one scroll "
        "| added by scroll | GSAP chunk | within budget |",
        "| --- | --- | ---: | ---: | :---: | ---: | ---: | ---: | :---: |",
    ]
    for label, data in res["builds"].items():
        for mode in ("normal_motion", "reduced_motion"):
            m = data[mode]
            ok = "yes" if m["before_interaction_gz_bytes"] <= b else "NO"
            gsap = "yes" if m["gsap_before_interaction"] else "no"
            lines.append(
                f"| {label} | {mode.replace('_', ' ')} | {data['static_index_html_gz_bytes']:,} B "
                f"| {m['before_interaction_gz_bytes']:,} B | {gsap} "
                f"| {m['after_one_scroll_gz_bytes']:,} B "
                f"| +{m['added_by_one_scroll_gz_bytes']:,} B "
                f"| {m['gsap_chunk_gz_bytes']:,} B | {ok} |"
            )
    lines += [
        "",
        "Other-origin requests (all builds, both modes): "
        + (
            str(
                sorted(
                    {
                        u
                        for d in res["builds"].values()
                        for k in ("normal_motion", "reduced_motion")
                        for u in d[k]["other_origin_requests_total"]
                    }
                )
            )
            or "none"
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    builds = {}
    for arg in argv:
        label, _, path = arg.partition("=")
        builds[label] = Path(path).resolve()
    if not builds:
        print(__doc__)
        return 2
    res = run(builds)
    (ROOT / "benchmarks" / "phase5-bundle.json").write_text(json.dumps(res, indent=2) + "\n")
    md = markdown(res)
    (ROOT / "benchmarks" / "phase5-bundle.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
