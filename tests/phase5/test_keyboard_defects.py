"""Keyboard defects the builder must fix (kept apart from test_keyboard_access.py until then).

1. Closing the Inventory drawer must return focus to the control that opened it (it drops to body).
"""

from __future__ import annotations

from .pagetools import settle
from .test_keyboard_access import _first_asset, _open_drawer


def test_keyboard_escape_closes_the_dialog_and_returns_focus(open_page) -> None:  # noqa: ANN001
    asset_id, _ = _first_asset()
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    trigger, _ = _open_drawer(page, asset_id)
    page.keyboard.press("Escape")
    page.get_by_role("dialog").wait_for(state="detached", timeout=5000)
    assert "asset=" not in page.url, page.url
    back = page.evaluate(
        "id => document.activeElement?.closest('tr')?.getAttribute('data-asset-id') === id",
        asset_id,
    )
    assert back, "focus did not return to the control that opened the dialog"
