"""Bundle: the JS a visitor fetches before the first interaction, and that GSAP stays lazy.

Thresholds (lead, 2026-11-08; the budget counts JS fetched before first interaction):
  * load "/" in Chromium at 390 px, NO interaction, network idle then 5 s more; gzip -9 of every
    JS response body plus every executable inline script <= 200,000 B, in normal AND reduced motion
    (reduced motion is the riskier one: a hero chunk loads on a timer there);
  * the GSAP chunk (found by content) is not fetched before the first interaction, IS fetched after
    one scroll and after a click on Replay, and is never fetched under reduced motion;
  * 0 other-origin requests in any of those states;
  * mutation probes on synthetic pages: an eager GSAP import and an oversized bundle both fail.
The static count the gate also computes (gzip -9 of the scripts index.html names) is asserted too.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from .helpers import OUT_DIR
from .pagetools import (
    BUDGET_BYTES,
    gsap_requested,
    gz9,
    idle_without_interacting,
    script_report,
    total_gz,
)

MOBILE = {"width": 390, "height": 844}


def _home(open_page, reduced: bool):  # noqa: ANN001, ANN202
    page = open_page("/", reduced_motion=reduced, wait="load", **MOBILE)
    idle_without_interacting(page)
    return page


def _scroll(page) -> None:  # noqa: ANN001
    page.mouse.move(100, 300)
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(2500)
    page.wait_for_load_state("networkidle")


# ----------------------------------------------------------------- before any interaction


@pytest.mark.parametrize("reduced", [False, True], ids=["normal-motion", "reduced-motion"])
def test_bundle_before_interaction_is_within_budget(open_page, reduced) -> None:  # noqa: ANN001
    page = _home(open_page, reduced)
    scripts = script_report(page)
    total = total_gz(scripts)
    assert total <= BUDGET_BYTES, (
        f"{total:,} B gzip -9 of JS fetched before any interaction "
        f"({len(scripts)} scripts) exceeds {BUDGET_BYTES:,} B"
    )
    assert total > 20_000, "implausibly small: were the response bodies read?"


@pytest.mark.parametrize("reduced", [False, True], ids=["normal-motion", "reduced-motion"])
def test_bundle_gsap_is_not_fetched_before_the_first_interaction(open_page, reduced) -> None:  # noqa: ANN001
    page = _home(open_page, reduced)
    assert gsap_requested(script_report(page)) == []


@pytest.mark.parametrize("reduced", [False, True], ids=["normal-motion", "reduced-motion"])
def test_bundle_no_other_origin_request_before_interaction(open_page, reduced) -> None:  # noqa: ANN001
    page = _home(open_page, reduced)
    foreign = [u for u in page.qday.requests if not u.startswith(page.qday.base)]
    assert foreign == [], foreign


# ------------------------------------------------------------------- after an interaction


def test_bundle_gsap_is_fetched_after_one_scroll(open_page) -> None:  # noqa: ANN001
    page = _home(open_page, reduced=False)
    before = total_gz(script_report(page))
    assert gsap_requested(script_report(page)) == []
    _scroll(page)
    scripts = script_report(page)
    assert len(gsap_requested(scripts)) >= 1, "the hero never loaded GSAP: it would not animate"
    assert total_gz(scripts) > before, "an interaction added no script"
    foreign = [u for u in page.qday.requests if not u.startswith(page.qday.base)]
    assert foreign == []


@pytest.mark.parametrize("trigger", ["wheel", "keydown", "pointerdown"])
def test_bundle_every_first_interaction_loads_gsap(open_page, trigger) -> None:  # noqa: ANN001
    # builder 5c: the hero's layers and GSAP load on the first scroll, wheel, touchmove, keydown or
    # pointerdown. (touchmove needs a touch device and is covered by the scroll case in spirit.)
    page = _home(open_page, reduced=False)
    assert gsap_requested(script_report(page)) == []
    if trigger == "wheel":
        page.mouse.move(100, 300)
        page.mouse.wheel(0, 300)
    elif trigger == "keydown":
        page.keyboard.press("ArrowDown")
    else:
        page.mouse.click(40, 400)
    page.wait_for_timeout(2500)
    page.wait_for_load_state("networkidle")
    assert len(gsap_requested(script_report(page))) >= 1, f"{trigger} did not load GSAP"


def test_bundle_replay_works_once_the_hero_is_awake(open_page) -> None:  # noqa: ANN001
    # Replay is rendered by the hero chunk, so it cannot be what loads GSAP; after the first
    # interaction it must exist and be usable without any error or new foreign request.
    page = _home(open_page, reduced=False)
    assert page.get_by_role("button", name="Replay the sequence").count() == 0
    _scroll(page)
    replay = page.get_by_role("button", name="Replay the sequence")
    replay.wait_for(state="attached", timeout=8000)
    replay.click()
    page.wait_for_timeout(1500)
    assert len(gsap_requested(script_report(page))) >= 1
    assert page.qday.pageerrors == []
    assert [u for u in page.qday.requests if not u.startswith(page.qday.base)] == []


def test_bundle_gsap_is_never_fetched_under_reduced_motion(open_page) -> None:  # noqa: ANN001
    page = _home(open_page, reduced=True)
    _scroll(page)
    page.keyboard.press("Tab")
    page.keyboard.press("ArrowDown")
    page.mouse.click(50, 400)
    page.wait_for_timeout(2000)
    assert gsap_requested(script_report(page)) == []
    assert page.get_by_role("button", name="Replay the sequence").count() == 0, (
        "reduced motion shows the static strip: there is nothing to replay"
    )


# ------------------------------------------------------------------------ the static count


def _static_total(out: Path) -> int:
    html = (out / "index.html").read_text(encoding="utf-8")
    srcs = {
        s.lstrip("/").split("?")[0] for s in re.findall(r"<script[^>]*\bsrc=[\"']([^\"']+)", html)
    }
    return sum(gz9((out / s).read_bytes()) for s in srcs)


def test_bundle_static_count_the_gate_uses_is_within_budget() -> None:
    total = _static_total(OUT_DIR)
    assert 20_000 < total <= BUDGET_BYTES, f"{total:,} B"


# ---------------------------------------------------------------- the probes can fail


def _synthetic_site(root: Path, *, eager_gsap: bool, extra_bytes: int) -> None:
    root.mkdir()
    chunk = "/* GSAP target not found. https://gsap.com */ window.__gsap = 1;\n"
    (root / "gsap.js").write_text(chunk)
    # incompressible filler so gzip cannot shrink it below the budget
    import os

    (root / "big.js").write_bytes(b"/*" + os.urandom(extra_bytes).hex().encode() + b"*/")
    loader = (
        '<script src="/gsap.js"></script>'
        if eager_gsap
        else "<script>addEventListener('wheel',()=>{const s=document.createElement('script');"
        "s.src='/gsap.js';document.head.append(s)},{once:true})</script>"
    )
    big = '<script src="/big.js"></script>' if extra_bytes else ""
    (root / "index.html").write_text(f"<!doctype html><title>t</title><body>x{big}{loader}</body>")


def test_bundle_the_probe_fails_a_page_that_imports_gsap_eagerly(
    open_page,
    serve_dir,
    tmp_path,
    browser,  # noqa: ANN001
) -> None:
    eager, lazy = tmp_path / "eager", tmp_path / "lazy"
    _synthetic_site(eager, eager_gsap=True, extra_bytes=0)
    _synthetic_site(lazy, eager_gsap=False, extra_bytes=0)
    for root, expect in ((eager, True), (lazy, False)):
        base = serve_dir(root)
        ctx = browser.new_context(viewport=MOBILE)
        page = ctx.new_page()
        page.qday = type("L", (), {"responses": []})()
        page.on("response", lambda r, p=page: p.qday.responses.append(r))
        page.goto(base + "/", wait_until="load")
        idle_without_interacting(page, extra_ms=500)
        assert bool(gsap_requested(script_report(page))) is expect, root.name
        if not expect:  # the lazy page must still load it on interaction: the probe sees both ways
            page.mouse.wheel(0, 300)
            page.wait_for_timeout(1000)
            assert gsap_requested(script_report(page))
        ctx.close()


def test_bundle_the_probe_fails_an_oversized_bundle(serve_dir, tmp_path, browser) -> None:  # noqa: ANN001
    root = tmp_path / "big"
    _synthetic_site(
        root, eager_gsap=False, extra_bytes=300_000
    )  # ~260 kB of hex: incompressible-ish
    base = serve_dir(root)
    ctx = browser.new_context(viewport=MOBILE)
    page = ctx.new_page()
    page.qday = type("L", (), {"responses": []})()
    page.on("response", lambda r: page.qday.responses.append(r))
    page.goto(base + "/", wait_until="load")
    idle_without_interacting(page, extra_ms=500)
    assert total_gz(script_report(page)) > BUDGET_BYTES, (
        "the budget check would not notice this page"
    )
    ctx.close()


def test_bundle_gz9_is_what_the_gate_means_by_gzip_9() -> None:
    import gzip

    blob = (b"abc" * 5000) + bytes(range(256)) * 4
    assert gz9(blob) == len(gzip.compress(blob, 9)) < len(blob)
