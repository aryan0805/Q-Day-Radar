"""Glossary (tweak round 1, task 8c): the first use of each term per page is wrapped, reachable
by keyboard, and its tooltip opens on focus, hover and tap and closes on Escape.

Rules (lead's brief, builder's design): a term's FIRST use on a page is a `.gloss` element
(tabindex 0, role button), each term wrapped once per page; one shared `role=tooltip` host opens on
hover, focus and tap, is dismissed by Escape without losing focus, and holds a real definition.
Checks read the live DOM; mutation tests plant a duplicate, a non-focusable term and an earlier
unwrapped mention and show each is caught.
"""

from __future__ import annotations

import pytest

from .helpers import ROUTES
from .pagetools import settle, wake_hero

TERMS = {
    "qubit", "shor", "grover", "rsa", "ecc", "mlkem", "transpiled", "continued", "mosca", "crqc",
    "chance", "trend", "compiled", "simulator",
}  # fmt: skip

_REPORT = """
() => {
  const main = document.querySelector('main');
  const gl = [...document.querySelectorAll('.gloss')].map(e => ({
    term: e.dataset.term, text: (e.textContent || '').trim(), tabindex: e.getAttribute('tabindex'),
    role: e.getAttribute('role'), in_interactive: !!e.parentElement.closest('a, button'),
    in_main: !!e.closest('main'),
  }));
  // reading order of every text node in main, outside terms, tooltips and non-prose chrome
  const skip = 'script, style, noscript, template, .gloss, [role=tooltip], h1, h2, h3, h4, h5, h6, '
             + 'summary, th, td, button, nav, label, select, option, code, pre';
  const nodes = [];
  const w = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const p = n.parentElement;
    if (p && !p.closest(skip)) nodes.push({node: n, text: n.textContent});
  }
  const early = [];
  for (const g of document.querySelectorAll('main .gloss')) {
    const word = (g.textContent || '').trim();
    if (!word) continue;
    const rx = new RegExp('(^|[^A-Za-z0-9])' + word.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')
                          + '($|[^A-Za-z0-9])', 'i');
    for (const {node, text} of nodes) {
      // an unwrapped mention that comes BEFORE the wrapped one in document order
      if (rx.test(text) && (node.compareDocumentPosition(g) & Node.DOCUMENT_POSITION_FOLLOWING)) {
        early.push({term: g.dataset.term, word, context: text.trim().slice(0, 60)});
        break;
      }
    }
  }
  return {gl, early};
}
"""


def report(page) -> dict:  # noqa: ANN001
    return page.evaluate(_REPORT)


def problems(rep: dict) -> dict[str, list[str]]:
    """Every way a page departs from the glossary rule. Empty lists = the rule holds."""
    gl = rep["gl"]
    seen: dict[str, int] = {}
    for g in gl:
        seen[g["term"]] = seen.get(g["term"], 0) + 1
    return {
        "duplicate": sorted(t for t, n in seen.items() if n > 1),
        "unknown": sorted({g["term"] for g in gl} - TERMS),
        "not_focusable": [g["term"] for g in gl if g["tabindex"] != "0" or g["role"] != "button"],
        "empty": [g["term"] for g in gl if not g["text"]],
        "nested_interactive": [g["term"] for g in gl if g["in_interactive"]],
        "unwrapped_before_first": [f"{e['term']}: {e['context']!r}" for e in rep["early"]],
    }


CLEAN = {
    "duplicate": [], "unknown": [], "not_focusable": [], "empty": [],
    "nested_interactive": [], "unwrapped_before_first": [],
}  # fmt: skip


def _open(open_page, route: str, **kw):  # noqa: ANN001, ANN202
    page = open_page(f"{route}?s=median", **kw)
    settle(page, "median")
    if route == "/":
        wake_hero(page)
        settle(page, "median")
    return page


def _tip(page):  # noqa: ANN001, ANN202
    return page.locator("[role=tooltip]")


# -------------------------------------------------------------------- what is on each page


@pytest.mark.parametrize("route", ROUTES)
def test_glossary_each_page_wraps_each_term_once_and_first(open_page, route) -> None:  # noqa: ANN001
    page = _open(open_page, route)
    rep = report(page)
    assert len(rep["gl"]) >= 1, "a screen with no glossary term explains nothing"
    assert problems(rep) == CLEAN, {k: v for k, v in problems(rep).items() if v}


def test_glossary_the_terms_across_the_site_are_from_the_known_set(open_page) -> None:  # noqa: ANN001
    used: set[str] = set()
    for route in ROUTES:
        used |= {g["term"] for g in report(_open(open_page, route))["gl"]}
    assert used <= TERMS, used - TERMS
    assert len(used) >= 8, f"only {sorted(used)} used across the whole site"


# ------------------------------------------------------------------ opening and closing it


def _first_gloss(page):  # noqa: ANN001, ANN202
    return page.locator("main .gloss").first


def _focus_every_term(page) -> tuple[int, int]:  # noqa: ANN001
    """Focus each term and check its tooltip. Returns (terms checked, terms skipped as inert).
    A term inside an `inert` hero layer cannot take focus by design (those layers are hidden
    until the timeline shows them), so it is counted, not focused."""
    seen_text: set[str] = set()
    glosses = page.locator("main .gloss")
    checked = skipped = 0
    for i in range(glosses.count()):
        g = glosses.nth(i)
        if g.evaluate("e => !!e.closest('[inert]')"):
            skipped += 1
            continue
        g.scroll_into_view_if_needed()
        g.focus()
        _tip(page).first.wait_for(state="visible", timeout=3000)
        text = _tip(page).first.inner_text().strip()
        term = g.get_attribute("data-term")
        assert len(text) >= 20, f"{term}: tooltip says {text!r}"
        assert "undefined" not in text.lower() and "null" not in text.lower(), term
        seen_text.add(text)
        checked += 1
        page.keyboard.press("Escape")
    assert len(seen_text) == checked, "two terms share one definition"
    return checked, skipped


@pytest.mark.parametrize("route", ROUTES)
def test_glossary_focus_opens_the_tooltip_with_a_real_definition(open_page, route) -> None:  # noqa: ANN001
    page = _open(open_page, route)
    checked, _ = _focus_every_term(page)
    assert checked >= 1


def test_glossary_under_reduced_motion_every_home_term_takes_focus(open_page) -> None:  # noqa: ANN001
    # the static strip is not inert: nothing is hidden, so every term must open its tooltip
    page = open_page("/?s=median", reduced_motion=True)
    settle(page, "median")
    page.wait_for_selector("main .gloss[data-term='compiled']", timeout=10000)
    checked, skipped = _focus_every_term(page)
    assert skipped == 0, f"{skipped} terms are inert under reduced motion"
    assert checked >= 6


def test_glossary_hidden_hero_terms_are_inert_not_focusable_and_unwrapped_ones_absent(
    open_page,
) -> None:  # noqa: ANN001
    page = _open(open_page, "/")
    inert = page.locator("main .gloss").evaluate_all(
        "els => els.filter(e => e.closest('[inert]')).map(e => e.dataset.term)"
    )
    assert inert, "expected terms in the hidden hero layers (they are inert until revealed)"
    for term in inert:
        g = page.locator(f"main .gloss[data-term='{term}']").first
        g.focus()
        assert not page.evaluate("() => document.activeElement?.classList.contains('gloss')"), term


def test_glossary_the_tooltip_is_a_real_tooltip_tied_to_the_term(open_page) -> None:  # noqa: ANN001
    page = _open(open_page, "/lab/")
    g = _first_gloss(page)
    g.focus()
    tip = _tip(page).first
    tip.wait_for(state="visible", timeout=3000)
    assert tip.get_attribute("role") == "tooltip"
    tip_id = tip.get_attribute("id")
    assert tip_id, "the tooltip needs an id so the term can point at it"
    assert tip_id in (g.get_attribute("aria-describedby") or ""), (
        "the focused term is not associated with its tooltip (aria-describedby)"
    )


def test_glossary_hover_opens_and_leaving_closes(open_page) -> None:  # noqa: ANN001
    page = _open(open_page, "/lab/")
    g = _first_gloss(page)
    g.scroll_into_view_if_needed()
    g.hover()
    _tip(page).first.wait_for(state="visible", timeout=3000)
    page.mouse.move(2, 2)
    _tip(page).first.wait_for(state="hidden", timeout=3000)


@pytest.mark.parametrize("route", ROUTES)
def test_glossary_escape_closes_the_tooltip_and_keeps_focus(open_page, route) -> None:  # noqa: ANN001
    page = _open(open_page, route)
    g = _first_gloss(page)
    g.scroll_into_view_if_needed()
    g.focus()
    _tip(page).first.wait_for(state="visible", timeout=3000)
    page.keyboard.press("Escape")
    _tip(page).first.wait_for(state="hidden", timeout=3000)
    still = page.evaluate("() => document.activeElement?.classList.contains('gloss')")
    assert still, "Escape moved focus away from the term (WCAG 1.4.13: dismiss without moving)"


def test_glossary_tap_opens_the_tooltip_on_a_touch_screen(browser, site) -> None:  # noqa: ANN001
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    page = ctx.new_page()
    page.goto(site + "/lab/?s=median", wait_until="networkidle")
    settle(page, "median")
    g = page.locator("main .gloss").first
    g.scroll_into_view_if_needed()
    g.tap()
    _tip(page).first.wait_for(state="visible", timeout=3000)
    assert len(_tip(page).first.inner_text().strip()) >= 20
    page.keyboard.press("Escape")
    _tip(page).first.wait_for(state="hidden", timeout=3000)
    ctx.close()


def test_glossary_only_one_tooltip_is_open_at_a_time(open_page) -> None:  # noqa: ANN001
    page = _open(open_page, "/lab/")
    glosses = page.locator("main .gloss")
    assert glosses.count() >= 2
    glosses.nth(0).focus()
    _tip(page).first.wait_for(state="visible", timeout=3000)
    glosses.nth(1).focus()
    page.wait_for_timeout(300)
    assert _tip(page).filter(visible=True).count() == 1


# ------------------------------------------------------------------------- it can fail


def test_glossary_the_checks_catch_each_planted_defect(open_page) -> None:  # noqa: ANN001
    page = _open(open_page, "/lab/")
    assert problems(report(page)) == CLEAN
    # 1. a second wrapper for a term that is already wrapped
    page.evaluate(
        """() => { const g = document.querySelector('main .gloss');
                   const d = g.cloneNode(true); d.setAttribute('data-planted', '1');
                   g.parentElement.append(' ', d); }"""
    )
    assert len(problems(report(page))["duplicate"]) == 1
    page.evaluate("() => document.querySelector('[data-planted]').remove()")
    assert problems(report(page))["duplicate"] == []
    # 2. a term a keyboard user cannot reach
    page.evaluate("() => document.querySelector('main .gloss').removeAttribute('tabindex')")
    assert len(problems(report(page))["not_focusable"]) == 1
    page.evaluate("() => document.querySelector('main .gloss').setAttribute('tabindex', '0')")
    # 3. an unwrapped mention BEFORE the wrapped first use
    word = page.evaluate("() => document.querySelector('main .gloss').textContent.trim()")
    page.evaluate(
        """(w) => { const p = document.createElement('p'); p.textContent = 'About ' + w + ' here.';
                   document.querySelector('main').prepend(p); }""",
        word,
    )
    assert len(problems(report(page))["unwrapped_before_first"]) >= 1
    # 4. an unknown term
    page.evaluate("() => document.querySelector('main .gloss').dataset.term = 'blockchain'")
    assert "blockchain" in problems(report(page))["unknown"]


def test_glossary_problems_helper_accepts_clean_and_flags_each_kind() -> None:
    good = {"gl": [{"term": "shor", "text": "Shor", "tabindex": "0", "role": "button",
                    "in_interactive": False, "in_main": True}], "early": []}  # fmt: skip
    assert problems(good) == CLEAN
    broken = dict(good["gl"][0], tabindex=None, in_interactive=True, text="")
    bad = {"gl": [dict(good["gl"][0]), broken],
           "early": [{"term": "shor", "word": "Shor", "context": "x"}]}  # fmt: skip
    assert all(v for k, v in problems(bad).items() if k != "unknown")
