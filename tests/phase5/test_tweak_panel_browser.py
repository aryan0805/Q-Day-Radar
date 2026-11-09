"""Tweak panel, in-browser half (task 7, spec 8.2): present in development, absent in production.

The static half (test_tweak_panel_static.py) proves the panel module is not in out/. This half runs
the real `next dev` server and checks the panel works as the spec says: `/?tweak` shows it, a plain
URL does not, the sliders and colour inputs rewrite the design tokens live on <html>, and "Copy
tokens" puts a JSON of every token on the clipboard. Production behaviour (no panel, no slider on
`/?tweak`) is checked against the built site in test_motionscale.py.

The dev server runs from a PRIVATE COPY of web/ (node_modules cloned), so it cannot race with a
`next build` in the shared checkout: both write .next/.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from .helpers import WEB

SENTINEL = "QDAY_TWEAK_PANEL"
COLOURS = ["q", "threat", "warn", "pqc", "sim", "sim-text", "text-1", "text-2"]
RANGES = {
    "glow": (0.0, 2.0),
    "motion-scale": (0.5, 2.5),
    "bg-density": (0.5, 2.0),
    "bg-speed": (0.0, 2.0),
}
_RGB = """(name) => {
  const probe = document.createElement('i');
  probe.style.color = 'var(' + name + ')';
  document.body.append(probe);
  const css = getComputedStyle(probe).color;
  probe.remove();
  const ctx = document.createElement('canvas').getContext('2d');
  ctx.fillStyle = css;
  ctx.fillRect(0, 0, 1, 1);
  return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
}"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _clone_node_modules(src: Path, dst: Path) -> None:
    """Turbopack refuses to resolve `next` through a symlink that leaves the project root, so the
    private copy needs real files. A copy-on-write clone (APFS `cp -c`, or reflinks elsewhere) costs
    almost nothing; a plain copy is the slow fallback."""
    for cmd in (
        ["cp", "-cR", str(src), str(dst)],
        ["cp", "-a", "--reflink=auto", str(src), str(dst)],
    ):
        if subprocess.run(cmd, capture_output=True).returncode == 0:
            return
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, symlinks=True)


@pytest.fixture(scope="module")
def dev_site(tmp_path_factory) -> Iterator[str]:  # noqa: ANN001
    """`next dev` on a free port from a private copy of web/; torn down with its process group."""
    root = tmp_path_factory.mktemp("web-dev")
    skip = shutil.ignore_patterns("node_modules", ".next", "out", ".vercel", "tsconfig.tsbuildinfo")
    shutil.copytree(WEB, root / "web", ignore=skip)
    _clone_node_modules(WEB / "node_modules", root / "web" / "node_modules")
    port = _free_port()
    log = (root / "dev.log").open("wb")
    proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(port)],
        cwd=root / "web",
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env={**os.environ, "NEXT_TELEMETRY_DISABLED": "1", "BROWSER": "none"},
    )
    # `localhost`, not 127.0.0.1: Next 16's dev server treats the IP as a cross-origin host and
    # blocks its dev resources, so the panel's lazily compiled chunk never mounts (seen: "Blocked
    # cross-origin request to Next.js dev resource"). We do not edit next.config.ts for a harness.
    base = f"http://localhost:{port}"
    try:
        deadline = time.time() + 240
        while True:
            if proc.poll() is not None:
                raise RuntimeError("next dev exited:\n" + (root / "dev.log").read_text()[-1500:])
            try:
                with urllib.request.urlopen(base + "/?tweak", timeout=120) as r:  # noqa: S310
                    if r.status == 200:
                        break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            if time.time() > deadline:
                raise RuntimeError(
                    "next dev did not become ready:\n" + (root / "dev.log").read_text()[-1500:]
                )
            time.sleep(1)
        yield base
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            os.killpg(proc.pid, signal.SIGKILL)
        log.close()


def _panel(browser, dev_site: str, url: str = "/?tweak"):  # noqa: ANN001, ANN202
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"]
    )
    page = ctx.new_page()
    page.goto(dev_site + url, wait_until="load", timeout=180000)
    return ctx, page


# ------------------------------------------------------------------------------ present


def test_tweak_the_panel_appears_on_the_tweak_url_in_development(browser, dev_site) -> None:  # noqa: ANN001
    ctx, page = _panel(browser, dev_site)
    panel = page.locator("[data-tweak-panel]")
    panel.wait_for(state="visible", timeout=60000)
    assert panel.get_attribute("data-tweak-panel") == SENTINEL
    assert panel.get_attribute("aria-label") == "Design tweaks (development only)"
    assert panel.evaluate("e => e.tagName") == "ASIDE"
    assert page.get_by_role("button", name="Copy tokens").count() == 1
    ctx.close()


def test_tweak_the_panel_does_not_appear_without_the_tweak_parameter(browser, dev_site) -> None:  # noqa: ANN001
    ctx, page = _panel(browser, dev_site, "/")
    page.wait_for_timeout(4000)
    assert page.locator("[data-tweak-panel]").count() == 0
    ctx.close()


def test_tweak_the_panel_has_every_colour_and_slider_the_spec_lists(browser, dev_site) -> None:  # noqa: ANN001
    ctx, page = _panel(browser, dev_site)
    panel = page.locator("[data-tweak-panel]")
    panel.wait_for(state="visible", timeout=60000)
    labels = panel.locator("label").all_inner_texts()
    for c in COLOURS:
        box = panel.locator(f"label:has-text('{c}') input[type=color]")
        assert box.count() >= 1, f"no colour input for {c}"
    assert panel.locator("input[type=color]").count() == len(COLOURS)
    ranges = panel.locator("input[type=range]")
    assert ranges.count() == len(RANGES), labels
    got = {}
    for i in range(ranges.count()):
        el = ranges.nth(i)
        name = el.evaluate("e => e.closest('label').textContent.trim().split(' ')[0]")
        got[name] = (float(el.get_attribute("min")), float(el.get_attribute("max")))
    assert got == RANGES
    ctx.close()


def test_tweak_every_control_has_an_accessible_name(browser, dev_site) -> None:  # noqa: ANN001
    ctx, page = _panel(browser, dev_site)
    panel = page.locator("[data-tweak-panel]")
    panel.wait_for(state="visible", timeout=60000)
    unnamed = panel.locator("input").evaluate_all(
        "els => els.filter(e => !(e.labels && e.labels.length)).length"
    )
    assert unnamed == 0, f"{unnamed} panel inputs have no label"
    ctx.close()


# ------------------------------------------------------------------------- it changes things


def test_tweak_the_motion_slider_rewrites_the_token_and_the_durations(browser, dev_site) -> None:  # noqa: ANN001
    ctx, page = _panel(browser, dev_site)
    page.locator("[data-tweak-panel]").wait_for(state="visible", timeout=60000)
    slider = page.locator("[data-tweak-panel] label:has-text('motion-scale') input[type=range]")
    slider.fill("2")
    assert (
        page.evaluate("() => document.documentElement.style.getPropertyValue('--motion-scale')")
        == "2"
    )
    ui_ms = page.evaluate(
        """() => { const e = document.createElement('i');
                   e.style.transitionDuration = 'var(--dur-ui)'; document.body.append(e);
                   const d = parseFloat(getComputedStyle(e).transitionDuration) * 1000;
                   e.remove(); return d; }"""
    )
    assert ui_ms == pytest.approx(360, abs=1), "--dur-ui is not 180 ms x 2 after the slider moved"
    ctx.close()


def test_tweak_a_colour_input_changes_the_rendered_colour_live(browser, dev_site) -> None:  # noqa: ANN001
    ctx, page = _panel(browser, dev_site)
    page.locator("[data-tweak-panel]").wait_for(state="visible", timeout=60000)
    before = page.evaluate(_RGB, "--q")
    page.locator("[data-tweak-panel] label:has-text('q') input[type=color]").first.fill("#123456")
    assert (
        page.evaluate("() => document.documentElement.style.getPropertyValue('--q')").lower()
        == "#123456"
    )
    after = page.evaluate(_RGB, "--q")
    assert after == [0x12, 0x34, 0x56] and after != before
    ctx.close()


def test_tweak_copy_tokens_puts_every_token_on_the_clipboard(browser, dev_site) -> None:  # noqa: ANN001
    ctx, page = _panel(browser, dev_site)
    page.locator("[data-tweak-panel]").wait_for(state="visible", timeout=60000)
    page.locator("[data-tweak-panel] label:has-text('motion-scale') input[type=range]").fill("1.5")
    page.locator("[data-tweak-panel] label:has-text('q') input[type=color]").first.fill("#abcdef")
    page.get_by_role("button", name="Copy tokens").click()
    page.get_by_role("button", name="Copied").wait_for(timeout=5000)
    tokens = json.loads(page.evaluate("() => navigator.clipboard.readText()"))
    assert set(tokens) == set(COLOURS) | set(RANGES)
    assert tokens["q"].lower() == "#abcdef"
    assert float(tokens["motion-scale"]) == pytest.approx(1.5)
    assert all(tokens[c].startswith("#") and len(tokens[c]) == 7 for c in COLOURS)
    ctx.close()


def test_tweak_the_panel_module_exists_only_in_the_dev_copy_of_the_source() -> None:
    # the production side of the same promise, as source: the loader gates on NODE_ENV
    loader = (WEB / "src" / "components" / "TweakLoader.tsx").read_text()
    assert 'process.env.NODE_ENV === "development"' in loader and "?tweak" in loader.replace(
        '"tweak"', "?tweak"
    )
    assert Path(WEB / "src" / "components" / "dev" / "TweakPanel.tsx").is_file()
