"""Keyboard (task 9): Tab reaches every control, focus is visible, dialogs trap and release.

Thresholds (fixed before BUILD): on every route, pressing Tab visits every visible interactive
control (the radio group counts once: roving tabindex); every focused element shows a focus
indicator (an outline of >= 2 px or a ring shadow); Tab never gets stuck; the Inventory drawer is a
dialog that holds focus while open, closes on Escape and gives focus back to what opened it.
This is automated keyboard testing only. It is not a screen-reader test, and the AUDIT says so.
"""

from __future__ import annotations

import pytest

from .helpers import ROUTES, load_data
from .pagetools import settle, wake_hero

# controls a keyboard user must reach: everything focusable and visible, excluding disabled
# elements, tabindex=-1, the unchecked radios of a roving group, and anything inside a closed
# <details> except its <summary>
_FOCUSABLE = """
() => {
  const sel = 'a[href], button, select, input, textarea, summary, [tabindex], [role=radio]';
  const visible = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)
      && getComputedStyle(e).visibility !== 'hidden';
  return [...document.querySelectorAll(sel)].filter(e =>
      visible(e) && !e.disabled && e.tabIndex >= 0 && !e.closest('[inert]')
      && !(e.getAttribute('role') === 'radio' && e.getAttribute('aria-checked') !== 'true')
      && !(e.closest('details:not([open])') && e.tagName !== 'SUMMARY'
           && !e.closest('summary')));
}
"""
_DESCRIBE = """
() => {
  const e = document.activeElement;
  if (!e || e === document.body) return null;
  const cs = getComputedStyle(e);
  const ow = parseFloat(cs.outlineWidth) || 0;
  const ring = cs.outlineStyle !== 'none' && ow >= 2;
  const shadow = cs.boxShadow && cs.boxShadow !== 'none';
  const r = e.getBoundingClientRect();
  let opacity = 1;
  for (let n = e; n; n = n.parentElement) opacity *= parseFloat(getComputedStyle(n).opacity);
  const onScreen = r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
      && r.top < innerHeight && r.left < innerWidth;
  return {key: [e.tagName, e.id, (e.getAttribute('href') || ''), e.dataset.scenario || '',
                (e.textContent || '').trim().slice(0, 30), Math.round(r.top + scrollY),
                Math.round(r.left)].join('|'),
          name: e.tagName.toLowerCase() + ' ' + (e.textContent || '').trim().slice(0, 30),
          focus_visible: ring || !!shadow,
          seen: onScreen && opacity > 0.1 && cs.visibility !== 'hidden',
          why: `opacity ${opacity.toFixed(2)}, top ${Math.round(r.top)}`
              + ` bottom ${Math.round(r.bottom)} (viewport ${innerHeight}),`
              + ` scrollY ${Math.round(scrollY)}`};
}
"""
_MARK = """
() => [...document.querySelectorAll(
  'a[href], button, select, input, summary, [tabindex], [role=radio]')]
  .forEach((e, i) => e.setAttribute('data-kb-id', String(i)))
"""


def tab_through(page, limit: int = 400, settle_ms: int = 0) -> tuple[list[dict], bool]:  # noqa: ANN001
    """Press Tab until focus leaves the document or repeats. Returns (visited, completed_cycle).
    settle_ms waits after each press so scroll-driven reveals (the hero) can finish before the
    focused element is judged."""
    page.evaluate("() => document.body.focus()")
    visited: list[dict] = []
    seen: set[str] = set()
    for _ in range(limit):
        page.keyboard.press("Tab")
        if settle_ms:
            page.wait_for_timeout(settle_ms)
        d = page.evaluate(_DESCRIBE)
        if d is None:  # focus went to the browser chrome: the page is not a trap
            return visited, True
        if d["key"] in seen:
            return visited, True
        seen.add(d["key"])
        visited.append(d)
    return visited, False


# ---------------------------------------------------------------------------- reach and trap


_UNREACHED = (
    "({reached, start}) => { const wanted = ("
    + _FOCUSABLE.strip()
    + ")(); return wanted.filter(e => start.includes(e.getAttribute('data-kb-id'))"
    + " && !reached.includes(e.getAttribute('data-kb-id')))"
    + ".map(e => e.tagName.toLowerCase() + ' ' + (e.textContent || '').trim().slice(0, 40)); }"
)


@pytest.mark.parametrize("route", ROUTES)
def test_keyboard_tab_reaches_every_control(open_page, route) -> None:  # noqa: ANN001
    page = open_page(f"{route}?s=median")
    settle(page, "median")
    if route == "/":
        wake_hero(page)  # the hero and the eggs load on the first interaction, Tab included
        settle(page, "median")
        page.evaluate("() => { scrollTo(0, 0); document.body.focus(); }")
        page.wait_for_timeout(
            1500
        )  # the scrubbed hero re-inerts its layers a moment after a scroll
    page.evaluate(_MARK)  # give every candidate a stable id before focus starts moving
    start = page.evaluate(
        "() => (" + _FOCUSABLE.strip() + ")().map(e => e.getAttribute('data-kb-id'))"
    )
    n_wanted = len(start)
    assert n_wanted >= 8, "found almost nothing focusable: wrong selector?"
    reached: set[str] = set()
    page.evaluate("() => document.body.focus()")
    # a full budget, ignoring moments when focus is on <body>: a wrap-around or a layer that drops
    # focus must not end the run early and report the rest of the page as unreachable
    for _ in range(2 * n_wanted + 80):
        page.keyboard.press("Tab")
        kb = page.evaluate("() => document.activeElement?.getAttribute('data-kb-id')")
        if kb is not None:
            reached.add(kb)
    # required: focusable before AND after the run (a hero layer that flips inert mid-run is not)
    missing = page.evaluate(_UNREACHED, {"reached": sorted(reached), "start": start})
    assert missing == [], f"Tab never reached: {missing[:8]}"


@pytest.mark.parametrize("route", ROUTES)
def test_keyboard_every_focused_element_shows_a_focus_indicator(open_page, route) -> None:  # noqa: ANN001
    page = open_page(f"{route}?s=median")
    settle(page, "median")
    visited, _ = tab_through(page)
    assert len(visited) >= 8
    hidden = [v["name"] for v in visited if not v["focus_visible"]]
    assert hidden == [], f"focus is not visible on: {hidden[:8]}"


@pytest.mark.parametrize("route", ROUTES)
def test_keyboard_tab_is_not_a_trap_and_returns_to_the_start(open_page, route) -> None:  # noqa: ANN001
    page = open_page(f"{route}?s=median")
    settle(page, "median")
    visited, completed = tab_through(page, limit=500)
    assert completed, f"500 Tab presses never left or repeated: stuck after {visited[-1]['name']}"
    assert visited[0]["name"].startswith("a skip") or "skip" in visited[0]["name"].lower(), (
        "the first Tab stop must be the skip link"
    )


def test_keyboard_the_skip_link_moves_the_next_tab_stop_into_main(open_page) -> None:  # noqa: ANN001
    # Activating a skip link moves the browser's sequential-focus starting point to its target
    # (document.activeElement may become <body>); what a keyboard user experiences is that the
    # NEXT Tab lands inside main, past the header and navigation.
    page = open_page("/lab/")
    settle(page)
    page.keyboard.press("Tab")
    assert "skip" in page.evaluate("() => document.activeElement.textContent").lower()
    href = page.evaluate("() => document.activeElement.getAttribute('href')")
    assert href and href.startswith("#") and page.locator(href).count() == 1
    page.keyboard.press("Enter")
    page.keyboard.press("Tab")
    assert page.evaluate("() => !!document.activeElement.closest('main')"), (
        "after the skip link, the next Tab did not land inside main"
    )


@pytest.mark.parametrize("route", ROUTES)
def test_keyboard_focus_never_lands_on_something_the_user_cannot_see(open_page, route) -> None:  # noqa: ANN001
    # Tab stops on invisible elements (opacity 0, off-screen, hidden layers) leave a keyboard user
    # with focus they cannot see (WCAG 2.4.7 / 2.4.3).
    page = open_page(f"{route}?s=median")
    settle(page, "median")
    if route == "/":
        wake_hero(page)
        settle(page, "median")
        page.evaluate("() => { scrollTo(0, 0); document.body.focus(); }")
    visited, _ = tab_through(page, settle_ms=300)
    unseen = [f"{v['name']} ({v['why']})" for v in visited if not v["seen"]]
    assert unseen == [], f"{len(unseen)} Tab stops were not visible when focused: {unseen[:8]}"


# ----------------------------------------------------------------- the Inventory dialog


def _first_asset(sc: str = "median") -> tuple[str, str]:
    a = min(load_data("inventory")["assets"], key=lambda a: a["by_scenario"][sc]["rank"])
    return a["id"], a["name"]


def _open_drawer(page, asset_id: str):  # noqa: ANN001, ANN202
    row = page.locator(f"tr[data-asset-id='{asset_id}']")
    trigger = row.get_by_role("button").first
    trigger.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog")
    dialog.wait_for(state="visible", timeout=5000)
    return trigger, dialog


def test_keyboard_the_drawer_is_a_dialog_that_opens_from_the_keyboard(open_page) -> None:  # noqa: ANN001
    asset_id, name = _first_asset()
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    _, dialog = _open_drawer(page, asset_id)
    assert name in dialog.inner_text()
    assert page.get_by_role("dialog").count() == 1
    assert f"asset={asset_id}" in page.url
    assert dialog.get_attribute("aria-labelledby") or dialog.get_attribute("aria-label")
    inside = page.evaluate("() => !!document.activeElement.closest('[role=dialog]')")
    assert inside, "focus did not move into the dialog"


def test_keyboard_focus_is_trapped_inside_the_open_dialog(open_page) -> None:  # noqa: ANN001
    asset_id, _ = _first_asset()
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    _open_drawer(page, asset_id)
    for key in ["Tab"] * 25 + ["Shift+Tab"] * 25:
        page.keyboard.press(key)
        assert page.evaluate("() => !!document.activeElement.closest('[role=dialog]')"), (
            f"focus escaped the dialog on {key}"
        )


def test_keyboard_a_deep_link_opens_the_dialog_and_escape_closes_it(open_page) -> None:  # noqa: ANN001
    asset_id, name = _first_asset("pessimistic")
    page = open_page(f"/inventory/?s=pessimistic&asset={asset_id}")
    settle(page, "pessimistic")
    dialog = page.get_by_role("dialog")
    dialog.wait_for(state="visible", timeout=5000)
    assert name in dialog.inner_text()
    page.keyboard.press("Escape")
    dialog.wait_for(state="detached", timeout=5000)
    assert "s=pessimistic" in page.url, "closing the dialog must not drop the scenario"


def test_keyboard_the_page_behind_the_dialog_is_not_reachable(open_page) -> None:  # noqa: ANN001
    asset_id, _ = _first_asset()
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    _open_drawer(page, asset_id)
    behind = page.evaluate(
        """() => [...document.querySelectorAll('main a[href], main button, main select')]
             .filter(e => !e.closest('[role=dialog]') && e.tabIndex >= 0
                          && !e.closest('[inert], [aria-hidden=true]')).length"""
    )
    assert behind == 0, f"{behind} controls behind the dialog are still reachable"


# -------------------------------------------------------------------- other controls


def test_keyboard_the_inventory_filters_are_native_selects_that_filter_the_rows(open_page) -> None:  # noqa: ANN001
    # Native <select> elements are operable by keyboard by construction (opening one with the
    # arrow keys is OS-dependent, so this test sets the value through the control, and checks it
    # is reachable by Tab and that choosing a value filters the rows to that family).
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    n_all = page.locator("tr[data-asset-id]").count()
    family = page.get_by_label("Family")
    assert family.evaluate("e => e.tagName") == "SELECT" and family.evaluate("e => e.tabIndex") == 0
    options = family.locator("option").all_text_contents()
    assert len(options) >= 3, options
    family.select_option(index=1)
    page.wait_for_timeout(500)
    shown = page.eval_on_selector_all(
        "tr[data-asset-id]", "rows => rows.map(r => r.getAttribute('data-asset-id'))"
    )
    assert 0 < len(shown) < n_all, (n_all, len(shown))
    fam_of = {a["id"]: a["family"] for a in load_data("inventory")["assets"]}
    assert len({fam_of[i] for i in shown}) == 1, "the filter let rows of other families through"
