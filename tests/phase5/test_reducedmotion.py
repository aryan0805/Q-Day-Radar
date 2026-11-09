"""Reduced motion (task 11, brief): with prefers-reduced-motion the site is still and says the same.

Thresholds (fixed before BUILD): no running animation on any screen once it has settled; GSAP is
never requested; the hero shows its four end states as a static strip (nothing inert or faded, no
Replay button); the background is the SVG lattice and no WebGL context is even created; the duration
tokens are 0; scrolling is not smooth; and the eggs honour it (the shatter, the 404 paths and the
Grover stepping do not move). Each "none" has a positive control in normal motion, so a hook that
saw nothing could not pass for the right reason.
"""

from __future__ import annotations

import pytest

from .helpers import ROUTES
from .pagetools import gsap_requested, script_report, settle

HOOK = """
(() => {
  window.__ctx = [];
  const orig = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (t, ...a) {
    window.__ctx.push(String(t));
    return orig.call(this, t, ...a);
  };
})();
"""
_RUNNING = """
() => document.getAnimations().filter(a => a.playState === 'running').map(a => {
  const t = a.effect && a.effect.target;
  const name = a.animationName || a.transitionProperty || 'animation';
  const where = t ? t.tagName.toLowerCase() + '.' + String(t.className).split(' ')[0] : '?';
  return name + ' on ' + where;
})
"""
_TOKEN = """(name) => {
  const e = document.createElement('i');
  e.style.transitionDuration = 'var(' + name + ')';
  document.body.append(e);
  const d = getComputedStyle(e).transitionDuration;
  e.remove();
  return d;
}"""
KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft",
          "ArrowRight", "b", "a"]  # fmt: skip


def _page(open_page, route="/", reduced=True, **kw):  # noqa: ANN001, ANN202
    page = open_page(f"{route}?s=median", reduced_motion=reduced, init_script=HOOK, **kw)
    settle(page, "median")
    return page


def _wait_hero_strip(page) -> None:  # noqa: ANN001
    # reduced motion has no first interaction to wait for: the hero chunk loads on a timer
    page.wait_for_selector(".hero-stage .gloss[data-term='compiled']", timeout=15000)
    page.wait_for_timeout(500)


# ------------------------------------------------------------------- nothing is running


@pytest.mark.parametrize("route", ROUTES)
def test_reducedmotion_no_animation_is_running_on_any_screen(open_page, route) -> None:  # noqa: ANN001
    page = _page(open_page, route)
    if route == "/":
        _wait_hero_strip(page)
    page.wait_for_timeout(3000)  # let any finite transition end
    assert page.evaluate(_RUNNING) == []


def test_reducedmotion_the_check_sees_animations_in_normal_motion(open_page) -> None:  # noqa: ANN001
    # positive control: the same probe, with motion on, must find something moving somewhere
    found = []
    page = _page(open_page, "/no-such-page/", reduced=False)
    page.wait_for_timeout(300)
    found += page.evaluate(_RUNNING)
    assert found, "the running-animation probe sees nothing even with motion on"


def test_reducedmotion_the_404_paths_do_not_move(open_page) -> None:  # noqa: ANN001
    page = _page(open_page, "/no-such-page/")
    page.wait_for_timeout(1500)
    assert page.evaluate(_RUNNING) == []
    anim = page.evaluate(
        "() => [...document.querySelectorAll('.nf-a, .nf-b')]"
        ".map(e => getComputedStyle(e).animationDuration)"
    )
    assert anim and all(float(d.rstrip("s")) == 0 for d in anim), anim


# ------------------------------------------------------------------------ no GSAP, no smoothing


def test_reducedmotion_gsap_is_never_requested(open_page) -> None:  # noqa: ANN001
    page = _page(open_page)
    _wait_hero_strip(page)
    page.mouse.wheel(0, 600)
    page.keyboard.press("ArrowDown")
    page.mouse.click(40, 400)
    page.wait_for_timeout(1500)
    assert gsap_requested(script_report(page)) == []


@pytest.mark.parametrize("route", ROUTES)
def test_reducedmotion_scrolling_is_not_smooth_and_tokens_are_zero(open_page, route) -> None:  # noqa: ANN001
    page = _page(open_page, route)
    assert (
        page.evaluate("() => getComputedStyle(document.documentElement).scrollBehavior") != "smooth"
    )
    for token in ("--dur-ui", "--dur-reveal"):
        assert page.evaluate(_TOKEN, token) in ("0s", "0ms"), token


# ------------------------------------------------------------------------- the static strip


def test_reducedmotion_the_hero_is_a_static_strip_of_the_four_end_states(open_page) -> None:  # noqa: ANN001
    page = _page(open_page)
    _wait_hero_strip(page)
    layers = page.evaluate(
        """() => [...document.querySelectorAll('.hero-layer')].map(l => ({
            opacity: getComputedStyle(l).opacity, inert: l.inert,
            text: l.textContent.trim().slice(0, 30)}))"""
    )
    assert len(layers) == 4, layers
    assert all(float(layer["opacity"]) == 1 and not layer["inert"] for layer in layers), layers
    text = page.locator(".hero-wrap").inner_text()
    for step in (
        "First, the circuit",
        "Then a classical step",
        "The pieces re-form into a lattice",
    ):
        assert step in text, f"missing end state: {step}"
    assert "ML-KEM: what to migrate to" in text
    assert page.get_by_role("button", name="Replay the sequence").count() == 0
    h = page.evaluate("() => document.querySelector('.hero-wrap').getBoundingClientRect().height")
    vh = page.evaluate("() => innerHeight")
    assert h < 3 * vh, f"the hero still occupies a {h:.0f}px scroll runway ({h / vh:.1f} screens)"


def test_reducedmotion_the_strip_figures_are_still_traced(open_page) -> None:  # noqa: ANN001
    from .pagetools import figure_audit

    page = _page(open_page)
    _wait_hero_strip(page)
    settle(page, "median")
    audit = figure_audit(page)
    assert audit["untraced"] == [] and audit["mismatches"] == [] and audit["unresolved"] == []
    assert page.locator("[data-src^='hero']").count() >= 5


# ------------------------------------------------------------------------- SVG, not WebGL


def test_reducedmotion_the_background_is_the_svg_lattice(open_page) -> None:  # noqa: ANN001
    page = _page(open_page)
    assert page.locator("canvas").count() == 0, "a WebGL canvas is still in the page"
    svg = page.locator("svg[aria-hidden='true']").first
    assert svg.count() == 1


def test_reducedmotion_no_webgl_context_is_even_created(open_page) -> None:  # noqa: ANN001
    page = _page(open_page)
    _wait_hero_strip(page)
    calls = page.evaluate("() => window.__ctx")
    gl = [c for c in calls if "webgl" in c.lower()]
    assert gl == [], f"reduced motion still requested WebGL contexts: {gl}"


def test_reducedmotion_the_hook_sees_webgl_in_normal_motion(open_page) -> None:  # noqa: ANN001
    page = _page(open_page, reduced=False)
    assert any("webgl" in c.lower() for c in page.evaluate("() => window.__ctx")), (
        "positive control failed: the getContext hook did not see the normal-motion background"
    )


# ------------------------------------------------------------------- eggs honour it too


def _egg_ready(page) -> None:  # noqa: ANN001
    page.mouse.wheel(0, 40)
    page.wait_for_selector("html[data-eggs=ready]", timeout=15000)


def test_reducedmotion_konami_does_not_animate_the_shatter(open_page) -> None:  # noqa: ANN001
    page = _page(open_page)
    _egg_ready(page)
    for key in KONAMI:
        page.keyboard.press(key)
    page.wait_for_selector("html[data-qday=on]")
    page.wait_for_timeout(300)
    assert page.evaluate(_RUNNING) == [], "the RSA and ECC dots still animate under reduced motion"


def test_reducedmotion_the_konami_shatter_moves_in_normal_motion(open_page) -> None:  # noqa: ANN001
    page = _page(open_page, reduced=False)
    _egg_ready(page)
    for key in KONAMI:
        page.keyboard.press(key)
    page.wait_for_selector("html[data-qday=on]")
    page.wait_for_timeout(150)
    assert any("shatter" in a for a in page.evaluate(_RUNNING)), "positive control failed"


def test_reducedmotion_grover_shows_its_answer_without_the_amplifying_animation(open_page) -> None:  # noqa: ANN001
    page = _page(open_page)
    _egg_ready(page)
    page.keyboard.type("grover")
    page.locator("aside.egg-card").wait_for(state="visible")
    page.wait_for_timeout(300)  # the stepped animation takes about two seconds in normal motion
    text = page.locator("aside.egg-card").inner_text()
    assert "Amplifying" not in text and "found in" in text, (
        "the amplitude stepping still animates under reduced motion"
    )
