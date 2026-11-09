"""Smoke: every route and the 404 load cleanly at 1440 / 1024 / 390 px (task 9, brief table).

Threshold (fixed before BUILD): 0 console errors, 0 page errors, 0 failed requests, 0 other-origin
requests, on every route and viewport. The 404 route answers 404 and is allowed exactly one console
line: the browser's own report that the document itself returned 404. Also checked: no horizontal
overflow, one h1 and one main landmark, a distinct title per route, lang="en", a viewport meta.
Screenshots (full page, settled) go to benchmarks/phase5-screens/ for the human to review.
"""

from __future__ import annotations

import re

import pytest

from .helpers import REPO, ROUTES, VIEWPORTS
from .pagetools import settle

SCREENS = REPO / "benchmarks" / "phase5-screens"
ALL_ROUTES = (*ROUTES, "/no-such-page/")
CASES = [(r, w, h) for r in ALL_ROUTES for (w, h) in VIEWPORTS]


def _slug(route: str) -> str:
    return "home" if route == "/" else route.strip("/").replace("/", "-")


@pytest.mark.parametrize(("route", "width", "height"), CASES)
def test_smoke_route_loads_cleanly(open_page, route, width, height) -> None:  # noqa: ANN001
    page = open_page(route, width=width, height=height)
    settle(page)
    log = page.qday
    is_404 = route == "/no-such-page/"
    assert page.response.status == (404 if is_404 else 200)

    errors = list(log.console)
    if is_404:  # the browser logs "Failed to load resource ... 404" for the document itself
        errors = [e for e in errors if not re.search(r"\b404\b|Not Found", e)]
    assert errors == [], errors
    assert log.pageerrors == [], log.pageerrors

    bad = [(s, u) for s, u in log.bad_responses if not (is_404 and u == page.url)]
    assert bad == [], bad
    foreign = [u for u in log.requests if not u.startswith(log.base)]
    assert foreign == [], foreign

    # layout: no sideways scrolling at any width
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 1, f"{overflow}px of horizontal overflow at {width}px"

    SCREENS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENS / f"{_slug(route)}-{width}.png"), full_page=True)


@pytest.mark.parametrize("route", ALL_ROUTES)
def test_smoke_document_structure(open_page, route) -> None:  # noqa: ANN001
    page = open_page(route)
    settle(page)
    assert page.locator("h1").count() == 1, "exactly one h1"
    assert page.locator("main").count() == 1, "exactly one main landmark"
    assert page.locator("nav").count() >= 1
    assert page.evaluate("() => document.documentElement.lang") == "en"
    assert page.locator("meta[name=viewport]").count() == 1
    assert page.title().strip()


def test_smoke_titles_are_distinct_per_route(open_page) -> None:  # noqa: ANN001
    titles = {}
    for route in ROUTES:
        page = open_page(route)
        titles[route] = page.title()
    assert len(set(titles.values())) == len(ROUTES), titles


def test_smoke_unknown_path_serves_the_404_page_not_the_home_page(open_page) -> None:  # noqa: ANN001
    page = open_page("/no-such-page/")
    assert page.response.status == 404
    assert "not found" in page.locator("h1").inner_text().lower()
    assert page.locator("[role=radiogroup]").count() >= 1, "the 404 keeps the site shell"
    for route in ("/lab/nope/", "/inventory/x/y/"):
        assert open_page(route).response.status == 404


def test_smoke_every_internal_link_resolves(open_page, site) -> None:  # noqa: ANN001
    import urllib.request
    from urllib.parse import urljoin, urlsplit

    seen: set[str] = set()
    for route in ROUTES:
        page = open_page(route)
        settle(page)
        for href in page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.getAttribute('href'))"
        ):
            url = urljoin(site + route, href)
            parts = urlsplit(url)
            if parts.netloc == urlsplit(site).netloc and not href.startswith("#"):
                seen.add(parts.path)
    assert len(seen) >= 4, seen
    for path in sorted(seen):
        with urllib.request.urlopen(site + path, timeout=10) as r:  # noqa: S310
            assert r.status == 200, path
