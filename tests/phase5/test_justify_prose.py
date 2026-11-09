"""Justified running prose (human tweak round 1, task 8b): computed text-align per element type.

Rule (lead's brief, builder's CSS): running prose (main p, li, dd) is `text-align: justify` with
`hyphens: auto` from 480 px up and left-aligned below 479 px; the contexts the builder
left-aligned on purpose (hero captions, legend, tooltips, radar card, .why, deadlines, egg cards)
stay left at every width; headings, nav, buttons, labels, table cells and code never become
justified; html[lang=en].
The check reads the COMPUTED style of every element on every route at 1440 / 1024 / 390 px, so a
container rule that only sets an inherited value (which a paragraph's own rule overrides) is caught.
Full justification works against WCAG 1.4.8 (a AAA criterion, outside the AA target); the AUDIT says
so. Screenshots of a justified paragraph per route and width go to benchmarks/phase5-screens/.
"""

from __future__ import annotations

import pytest

from .helpers import REPO, ROUTES, VIEWPORTS
from .pagetools import settle, wake_hero

SCREENS = REPO / "benchmarks" / "phase5-screens"
NARROW_BELOW = 480  # the CSS breakpoint: max-width 479px is left-aligned
# the contexts the builder left-aligned on purpose (an element inside any of these is exempt)
EXCEPTIONS = (
    ".hero-step, .hero-caption, .hero-notes, .radar-card, .why, .legend, .fig-tip-row, "
    ".egg-card, .deadlines, [role=tooltip]"
)
PROSE = "main p, main li, main dd"
OTHER_TYPES = "h1, h2, h3, h4, h5, h6, nav a, button, label, th, td, code, pre, summary, select"

_REPORT = """
([prose, exceptions, others]) => {
  const rec = e => {
    const cs = getComputedStyle(e);
    return {tag: e.tagName.toLowerCase(), cls: String(e.className).split(' ')[0],
            align: cs.textAlign, hyphens: cs.hyphens,
            text: (e.textContent || '').trim().slice(0, 36)};
  };
  const exempt = e => !!e.closest(exceptions);
  const prose_all = [...document.querySelectorAll(prose)]
      .map(e => ({...rec(e), exempt: exempt(e)}));
  const other = [...document.querySelectorAll(others)].map(rec);
  return {lang: document.documentElement.lang, prose: prose_all, other};
}
"""


def report(page) -> dict:  # noqa: ANN001
    return page.evaluate(_REPORT, [PROSE, EXCEPTIONS, OTHER_TYPES])


def violations(rep: dict, width: int) -> dict[str, list[str]]:
    """Everything that breaks the rule at this viewport width. Empty lists = the rule holds."""
    narrow = width < NARROW_BELOW
    bad: dict[str, list[str]] = {"prose": [], "exempt": [], "other": [], "hyphens": []}
    for p in rep["prose"]:
        label = f"<{p['tag']}.{p['cls']}> {p['text']!r} -> {p['align']}/{p['hyphens']}"
        if p["exempt"] or narrow:
            if p["align"] not in ("left", "start"):
                bad["exempt" if p["exempt"] else "prose"].append(label)
        else:
            if p["align"] != "justify":
                bad["prose"].append(label)
            if p["hyphens"] != "auto":
                bad["hyphens"].append(label)
    bad["other"] = [
        f"<{o['tag']}> {o['text']!r} -> {o['align']}"
        for o in rep["other"]
        if o["align"] == "justify"
    ]
    return bad


def _open(open_page, route: str, width: int, height: int):  # noqa: ANN001, ANN202
    page = open_page(f"{route}?s=median", width=width, height=height)
    settle(page, "median")
    if route == "/":
        wake_hero(page)  # the hero's captions and notes exist only after the first interaction
        settle(page, "median")
    return page


# --------------------------------------------------------------------- the rule, per viewport


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
@pytest.mark.parametrize("route", ROUTES)
def test_justify_computed_text_align_follows_the_rule(open_page, route, width, height) -> None:  # noqa: ANN001
    page = _open(open_page, route, width, height)
    rep = report(page)
    assert len(rep["prose"]) >= 3, f"found {len(rep['prose'])} prose elements: wrong selector?"
    assert rep["lang"] == "en"
    bad = violations(rep, width)
    assert bad == {"prose": [], "exempt": [], "other": [], "hyphens": []}, {
        k: v[:6] for k, v in bad.items() if v
    }


@pytest.mark.parametrize("route", ROUTES)
def test_justify_there_is_justified_prose_above_the_breakpoint_and_none_below(
    open_page, route
) -> None:  # noqa: ANN001
    wide = report(_open(open_page, route, 1440, 900))
    narrow = report(_open(open_page, route, 390, 844))
    assert any(p["align"] == "justify" for p in wide["prose"]), "nothing is justified at 1440 px"
    assert not any(p["align"] == "justify" for p in narrow["prose"]), "justified at 390 px"


@pytest.mark.parametrize(("width", "justified"), [(479, False), (480, True)])
def test_justify_the_breakpoint_is_at_480(open_page, width, justified) -> None:  # noqa: ANN001
    page = _open(open_page, "/lab/", width, 900)
    rep = report(page)
    plain = [p for p in rep["prose"] if not p["exempt"]]
    assert plain
    assert all((p["align"] == "justify") == justified for p in plain), (
        f"at {width}px: {sorted({p['align'] for p in plain})}"
    )


# ------------------------------------------------------------------ the 404 and the language


def test_justify_the_404_page_follows_the_same_rule(open_page) -> None:  # noqa: ANN001
    page = open_page("/no-such-page/")
    settle(page)
    rep = report(page)
    assert rep["lang"] == "en"
    assert violations(rep, 1440)["other"] == []


# ---------------------------------------------------------------------------- it can fail


def test_justify_a_left_aligned_paragraph_is_caught(open_page) -> None:  # noqa: ANN001
    page = _open(open_page, "/lab/", 1440, 900)
    assert violations(report(page), 1440)["prose"] == []
    page.evaluate(
        """() => { const p = [...document.querySelectorAll('main p')]
                     .find(e => !e.closest('.hero-caption, .legend, .radar-card, .why'));
                   p.style.textAlign = 'left'; }"""
    )
    assert len(violations(report(page), 1440)["prose"]) == 1


def test_justify_a_justified_heading_or_button_is_caught(open_page) -> None:  # noqa: ANN001
    page = _open(open_page, "/lab/", 1440, 900)
    assert violations(report(page), 1440)["other"] == []
    page.evaluate(
        """() => { document.querySelector('h1').style.textAlign = 'justify';
                   document.querySelector('button').style.textAlign = 'justify'; }"""
    )
    assert len(violations(report(page), 1440)["other"]) == 2


def test_justify_a_justified_exempt_paragraph_is_caught(open_page) -> None:  # noqa: ANN001
    page = _open(open_page, "/", 1440, 900)
    assert violations(report(page), 1440)["exempt"] == []
    mutated = page.evaluate(
        """([prose, exceptions]) => {
             const e = [...document.querySelectorAll(prose)].find(n => n.closest(exceptions));
             if (!e) return false;
             e.style.textAlign = 'justify';
             return true;
           }""",
        [PROSE, EXCEPTIONS],
    )
    assert mutated, "no exempt paragraph, list item or dd on this page to mutate"
    assert len(violations(report(page), 1440)["exempt"]) == 1


def test_justify_the_boundary_helper_is_what_the_rule_says() -> None:
    fake = {
        "lang": "en",
        "prose": [{"tag": "p", "cls": "x", "align": "justify", "hyphens": "auto",
                   "text": "t", "exempt": False}],
        "other": [],
    }  # fmt: skip
    assert violations(fake, 1440) == {"prose": [], "exempt": [], "other": [], "hyphens": []}
    assert violations(fake, 390)["prose"], "justified text below 480 px must be reported"
    fake["prose"][0]["hyphens"] = "manual"
    assert violations(fake, 1440)["hyphens"], "hyphens must be auto when justified"


# ---------------------------------------------------------------------------- screenshots


@pytest.mark.parametrize(("width", "height"), VIEWPORTS)
@pytest.mark.parametrize("route", ROUTES)
def test_justify_screenshot_of_a_justified_paragraph(open_page, route, width, height) -> None:  # noqa: ANN001
    page = _open(open_page, route, width, height)
    target = page.evaluate_handle(
        """([prose, exceptions]) => [...document.querySelectorAll(prose)]
             .filter(e => !e.closest(exceptions)
                          && (e.textContent || '').trim().split(/\\s+/).length > 25
                          && e.offsetWidth > 0)[0] || null""",
        [PROSE, EXCEPTIONS],
    ).as_element()
    assert target is not None, "no long running paragraph on this screen to photograph"
    target.scroll_into_view_if_needed()
    SCREENS.mkdir(parents=True, exist_ok=True)
    slug = "home" if route == "/" else route.strip("/")
    target.screenshot(path=str(SCREENS / f"justify-{slug}-{width}.png"))
