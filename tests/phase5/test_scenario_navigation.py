"""The scenario survives navigation, in the URL (brief: scenario is global state in the URL).

Kept apart from test_scenario_switch.py while the builder fixes it: the nav links are plain
"/lab/" etc., so a click-through keeps the scenario in memory but drops it from the address bar
(the URL then says median while the page shows another scenario; a reload flips it).
"""

from __future__ import annotations

import pytest

from .pagetools import settle
from .test_scenario_switch import checked


@pytest.mark.parametrize("route", ["/", "/lab/", "/scaling/", "/inventory/"])
def test_scenario_survives_navigation_between_screens(open_page, route) -> None:  # noqa: ANN001
    page = open_page(f"{route}?s=optimistic")
    settle(page, "optimistic")
    for name in ("Overview", "Lab", "Scaling", "Inventory"):
        link = page.get_by_role("navigation").get_by_role("link", name=name).first
        link.click()
        page.wait_for_load_state("networkidle")
        settle(page, "optimistic")
        assert "s=optimistic" in page.url, f"lost the scenario going to {name}: {page.url}"
        assert checked(page) == ["optimistic"]
