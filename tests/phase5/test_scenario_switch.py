"""Scenario switch (task 9): the scenario is global state in the URL and drives the data.

Threshold (fixed before BUILD): Inventory row order equals inventory.json's rank order for each
scenario, with the switch applied by URL, by click and by keyboard; the Overview "In this scenario"
figures trace to the selected scenario's paths; the scenario survives navigation between screens.
A precondition test proves the scenarios' orders really differ, so a reorder cannot "pass" by
standing still.
"""

from __future__ import annotations

import re

import pytest

from .helpers import SCENARIOS, load_data
from .pagetools import settle

LABEL = {"optimistic": "Optimistic", "median": "Median", "pessimistic": "Pessimistic"}


def expected_order(sc: str) -> list[str]:
    """Asset ids in rank order for a scenario: the brief's (rank, id) sort, from the data."""
    assets = load_data("inventory")["assets"]
    return [a["id"] for a in sorted(assets, key=lambda a: (a["by_scenario"][sc]["rank"], a["id"]))]


def dom_order(page) -> list[str]:  # noqa: ANN001
    return page.eval_on_selector_all(
        "tr[data-asset-id]", "rows => rows.map(r => r.getAttribute('data-asset-id'))"
    )


def checked(page) -> list[str]:  # noqa: ANN001
    return page.eval_on_selector_all(
        "[role=radiogroup] [role=radio][aria-checked=true]",
        "els => els.map(e => e.dataset.scenario)",
    )


# ------------------------------------------------------------------ the data can tell them apart


def test_scenario_the_orders_differ_so_a_reorder_can_be_seen() -> None:
    orders = {sc: expected_order(sc) for sc in SCENARIOS}
    assert len({tuple(o) for o in orders.values()}) >= 2, "all scenarios rank identically"
    inv = load_data("inventory")
    for sc in SCENARIOS:
        ranks = sorted(a["by_scenario"][sc]["rank"] for a in inv["assets"])
        assert ranks == list(range(1, len(ranks) + 1)), f"{sc}: ranks are not 1..n without ties"


# ------------------------------------------------------------------------ inventory row order


@pytest.mark.parametrize("sc", SCENARIOS)
def test_scenario_inventory_rows_follow_the_rank_order_for_the_url_scenario(open_page, sc) -> None:  # noqa: ANN001
    page = open_page(f"/inventory/?s={sc}")
    settle(page, sc)
    assert dom_order(page) == expected_order(sc)


@pytest.mark.parametrize(
    ("start", "target"),
    [("median", "optimistic"), ("optimistic", "pessimistic"), ("pessimistic", "median")],
)
def test_scenario_clicking_the_switch_reorders_the_rows(open_page, start, target) -> None:  # noqa: ANN001
    page = open_page(f"/inventory/?s={start}")
    settle(page, start)
    assert dom_order(page) == expected_order(start)
    page.get_by_role("radio", name=LABEL[target]).click()
    page.wait_for_function(
        "sc => document.querySelector('[role=radio][aria-checked=true]')?.dataset.scenario === sc",
        arg=target,
    )
    settle(page, target)
    assert dom_order(page) == expected_order(target)
    assert checked(page) == [target]
    q = page.url.split("?", 1)[1] if "?" in page.url else ""
    if target == "median":
        assert not re.search(r"\bs=(optimistic|pessimistic)\b", q), page.url
    else:
        assert f"s={target}" in q, page.url


def test_scenario_a_reload_keeps_the_scenario(open_page) -> None:  # noqa: ANN001
    page = open_page("/inventory/?s=pessimistic")
    settle(page, "pessimistic")
    page.reload(wait_until="networkidle")
    settle(page, "pessimistic")
    assert checked(page) == ["pessimistic"]
    assert dom_order(page) == expected_order("pessimistic")


def test_scenario_an_unknown_value_falls_back_to_median(open_page) -> None:  # noqa: ANN001
    page = open_page("/inventory/?s=bogus")
    settle(page, "median")
    assert checked(page) == ["median"]
    assert dom_order(page) == expected_order("median")


# ------------------------------------------------------------------- the switch as a control


def test_scenario_switch_is_a_labelled_radiogroup_with_three_radios(open_page) -> None:  # noqa: ANN001
    page = open_page("/")
    settle(page, "median")
    group = page.get_by_role("radiogroup", name="Scenario")
    assert group.count() == 1
    radios = group.get_by_role("radio")
    assert [r.inner_text().strip() for r in radios.all()] == [LABEL[s] for s in SCENARIOS]
    assert [r.get_attribute("aria-checked") for r in radios.all()] == ["false", "true", "false"]
    assert [r.get_attribute("tabindex") for r in radios.all()] == ["-1", "0", "-1"]  # roving


def test_scenario_arrow_keys_move_the_selection_and_the_data(open_page) -> None:  # noqa: ANN001
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    page.get_by_role("radio", name="Median").focus()
    page.keyboard.press("ArrowRight")
    settle(page, "pessimistic")
    assert checked(page) == ["pessimistic"] and dom_order(page) == expected_order("pessimistic")
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    settle(page, "optimistic")
    assert checked(page) == ["optimistic"] and dom_order(page) == expected_order("optimistic")
    focused = page.evaluate("() => document.activeElement?.dataset.scenario")
    assert focused == "optimistic", "focus must follow the selection (roving tabindex)"


# ------------------------------------------------------------------- the figures follow it


@pytest.mark.parametrize("sc", SCENARIOS)
def test_scenario_overview_summary_figures_trace_to_the_selected_scenario(open_page, sc) -> None:  # noqa: ANN001
    page = open_page(f"/?s={sc}")
    settle(page, sc)
    paths = page.eval_on_selector_all(
        "[data-src^='inventory:summary.']", "els => els.map(e => e.getAttribute('data-src'))"
    )
    assert paths, "no summary figure on the Overview"
    used = {m.group(1) for p in paths if (m := re.match(r"inventory:summary\.(\w+)\.", p))}
    assert used == {sc}, f"summary figures for {used} shown under {sc}"


def test_scenario_switching_changes_a_figure_that_depends_on_it(open_page) -> None:  # noqa: ANN001
    inv = load_data("inventory")
    values = {sc: inv["summary"][sc]["exposed"] for sc in SCENARIOS}
    assert len(set(values.values())) >= 2, "exposed count identical in every scenario: no signal"
    page = open_page("/?s=median")
    settle(page, "median")
    seen = {}
    for sc in SCENARIOS:
        page.get_by_role("radio", name=LABEL[sc]).click()
        settle(page, sc)
        seen[sc] = (
            page.locator(f"[data-src='inventory:summary.{sc}.exposed']").first.inner_text().strip()
        )
    assert seen == {sc: str(v) for sc, v in values.items()}
