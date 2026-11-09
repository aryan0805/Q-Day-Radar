"""Motion scale (human tweak round 1, task 8a): one dial, --motion-scale, scales all motion.

Rule (lead's brief, builder's CSS): the duration tokens are base x --motion-scale; every CSS
animation and transition duration and delay on the site follows the scale; the hero's Replay lasts
as long as its timeline times the scale; the slider that changes it exists only in development;
reduced motion still turns everything off whatever the scale. The generic scan reads the computed
duration and delay of EVERY element at scale 1 and again at scale 2 on every screen, so a fixed
duration someone forgets to multiply is found wherever it lives.
"""

from __future__ import annotations

import re

import pytest

from .helpers import ROUTES, WEB
from .pagetools import settle, wake_hero

TOKENS_CSS = (WEB / "src" / "styles" / "tokens.css").read_text(encoding="utf-8")
KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft",
          "ArrowRight", "b", "a"]  # fmt: skip
_TOKEN = """(name) => {
  const e = document.createElement('i');
  e.style.transitionDuration = 'var(' + name + ')';
  document.body.append(e);
  const d = getComputedStyle(e).transitionDuration;
  e.remove();
  return d.endsWith('ms') ? parseFloat(d) : parseFloat(d) * 1000;
}"""
_ALL = """() => {
  const sec = v => v.split(',').map(x => x.trim())
      .map(x => x.endsWith('ms') ? parseFloat(x) / 1000 : parseFloat(x));
  const out = [];
  [...document.querySelectorAll('*')].forEach((e, i) => {
    const cs = getComputedStyle(e);
    for (const p of ['animationDuration', 'animationDelay',
                     'transitionDuration', 'transitionDelay']) {
      sec(cs[p]).forEach((v, k) => { if (v) out.push({i, k, p, v,
          who: e.tagName.toLowerCase() + '.' + String(e.className).split(' ')[0]}); });
    }
  });
  return out;
}"""


def declared(name: str) -> tuple[float, str]:
    """(base in ms, whole declaration) of a duration token as written in tokens.css."""
    m = re.search(
        rf"{re.escape(name)}:\s*calc\(\s*([\d.]+)ms\s*\*\s*var\(--motion-scale\)\s*\)", TOKENS_CSS
    )
    assert m, f"{name} is not declared as calc(<base>ms * var(--motion-scale)) in tokens.css"
    return float(m.group(1)), m.group(0)


def _set_scale(page, value: float) -> None:  # noqa: ANN001
    page.evaluate(
        "(v) => document.documentElement.style.setProperty('--motion-scale', String(v))", value
    )


# --------------------------------------------------------------------------------- the tokens


def test_motionscale_the_scale_is_declared_once_as_a_plain_number() -> None:
    m = re.findall(r"--motion-scale:\s*([\d.]+)\s*;", TOKENS_CSS)
    assert len(m) == 1 and 0.5 <= float(m[0]) <= 2.5, "the dev slider range is 0.5 to 2.5"


def test_motionscale_base_durations_are_inside_the_spec_ranges() -> None:
    # spec section 6: UI transitions 150-250 ms, reveals 400-700 ms (at scale 1)
    assert 150 <= declared("--dur-ui")[0] <= 250
    assert 400 <= declared("--dur-reveal")[0] <= 700


@pytest.mark.parametrize("scale", [0.5, 1.0, 1.4, 2.0, 2.5])
@pytest.mark.parametrize("token", ["--dur-ui", "--dur-reveal"])
def test_motionscale_duration_tokens_are_base_times_scale(open_page, token, scale) -> None:  # noqa: ANN001
    page = open_page("/lab/?s=median")
    _set_scale(page, scale)
    got = page.evaluate(_TOKEN, token)
    assert got == pytest.approx(declared(token)[0] * scale, abs=0.6), (token, scale, got)


@pytest.mark.parametrize("token", ["--dur-ui", "--dur-reveal"])
def test_motionscale_reduced_motion_is_zero_whatever_the_scale(open_page, token) -> None:  # noqa: ANN001
    page = open_page("/lab/?s=median", reduced_motion=True)
    for scale in (1.0, 2.5):
        _set_scale(page, scale)
        assert page.evaluate(_TOKEN, token) == 0, (token, scale)


# ---------------------------------------------------------- every duration follows the scale


def _scan(page, scale: float) -> list[dict]:  # noqa: ANN001
    _set_scale(page, scale)
    return page.evaluate(_ALL)


@pytest.mark.parametrize("route", ROUTES)
def test_motionscale_every_animation_and_transition_duration_doubles_with_the_scale(
    open_page, route
) -> None:  # noqa: ANN001
    page = open_page(f"{route}?s=median")
    settle(page, "median")
    if route == "/":
        wake_hero(page)
        settle(page, "median")
    one = _scan(page, 1.0)
    two = _scan(page, 2.0)
    assert len(one) > 10, f"only {len(one)} timed elements on {route}: wrong probe?"
    key = lambda d: (d["i"], d["p"], d["k"])  # noqa: E731
    b = {key(d): d for d in two}
    stuck, vanished = [], []
    for d in one:
        other = b.get(key(d))
        if other is None:
            vanished.append(f"{d['who']} {d['p']}")
        elif abs(other["v"] - 2 * d["v"]) > 0.02 * 2 * d["v"] + 1e-6:
            stuck.append(f"{d['who']} {d['p']}: {d['v']:g}s -> {other['v']:g}s")
    assert vanished == [], vanished[:5]
    assert stuck == [], (
        f"{len(stuck)} durations do not follow --motion-scale: {sorted(set(stuck))[:8]}"
    )


def test_motionscale_the_scan_can_see_a_duration_that_does_not_scale(open_page) -> None:  # noqa: ANN001
    page = open_page("/lab/?s=median")
    settle(page, "median")
    page.evaluate(
        """() => { const e = document.querySelector('main p');
                   e.style.transition = 'opacity 0.37s'; }"""
    )
    one, two = _scan(page, 1.0), _scan(page, 2.0)
    fixed = [d for d in one if d["p"] == "transitionDuration" and abs(d["v"] - 0.37) < 1e-6]
    assert len(fixed) == 1
    same = [d for d in two if d["p"] == "transitionDuration" and abs(d["v"] - 0.37) < 1e-6]
    assert len(same) == 1, "a hard-coded 0.37s must stay 0.37s so the scan above would flag it"


def test_motionscale_the_konami_shatter_scales(open_page) -> None:  # noqa: ANN001
    page = open_page("/?s=median")
    settle(page, "median")
    page.mouse.wheel(0, 40)
    page.wait_for_selector("html[data-eggs=ready]", timeout=15000)
    for key in KONAMI:
        page.keyboard.press(key)
    page.wait_for_selector("html[data-qday=on]")
    seen = {}
    for scale in (1.0, 2.0):
        _set_scale(page, scale)
        seen[scale] = page.evaluate(
            """() => { const d = document.querySelector('.dot[data-family="RSA"]');
                       return parseFloat(getComputedStyle(d).animationDuration); }"""
        )
    assert seen[1.0] == pytest.approx(0.7, abs=0.01)
    assert seen[2.0] == pytest.approx(1.4, abs=0.02)


# ------------------------------------------------------------------- the hero's Replay


def _replay_seconds(open_page, scale: float) -> float:  # noqa: ANN001
    page = open_page(
        "/?s=median",
        init_script=(
            "document.addEventListener('DOMContentLoaded', () =>"
            f" document.documentElement.style.setProperty('--motion-scale', '{scale}'));"
        ),
    )
    settle(page, "median")
    assert (
        float(
            page.evaluate(
                "() => getComputedStyle(document.documentElement)"
                ".getPropertyValue('--motion-scale')"
            )
        )
        == scale
    )
    wake_hero(page)
    page.get_by_role("button", name="Replay the sequence").wait_for(state="visible", timeout=10000)
    page.evaluate("() => scrollTo(0, 0)")
    page.wait_for_timeout(600)
    return page.evaluate(
        """async () => {
             const last = () => parseFloat(getComputedStyle(
                 document.querySelectorAll('.hero-layer')[3]).opacity);
             const before = last();
             const btn = [...document.querySelectorAll('button')]
                 .find(b => /Replay/.test(b.textContent));
             btn.click();
             const t0 = performance.now();
             while (performance.now() - t0 < 60000) {
               await new Promise(r => requestAnimationFrame(r));
               if (last() >= 0.95) return { s: (performance.now() - t0) / 1000, before };
             }
             return { s: -1, before };
           }"""
    )


def test_motionscale_the_hero_replay_lasts_twice_as_long_at_twice_the_scale(open_page) -> None:  # noqa: ANN001
    one = _replay_seconds(open_page, 1.0)
    two = _replay_seconds(open_page, 2.0)
    assert one["before"] < 0.5 and two["before"] < 0.5, "the last hero layer was already visible"
    assert one["s"] > 2 and two["s"] > 0, f"the replay never finished: {one}, {two}"
    assert two["s"] / one["s"] == pytest.approx(2.0, rel=0.2), (
        f"replay took {one['s']:.1f}s at scale 1 and {two['s']:.1f}s at scale 2"
    )


# --------------------------------------------------------------- the slider is dev-only


def test_motionscale_a_production_build_has_no_slider_or_tweak_panel(open_page) -> None:  # noqa: ANN001
    page = open_page("/?tweak&s=median")
    settle(page, "median")
    page.wait_for_timeout(1500)
    assert page.locator("input[type=range]").count() == 0
    assert page.locator("[data-tweak-panel]").count() == 0
    assert page.get_by_label("Design tweaks (development only)").count() == 0
