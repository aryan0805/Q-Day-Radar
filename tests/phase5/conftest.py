"""Phase 5 fixtures. Owned by reviewer.

Browser tests use pytest-playwright's `browser` fixture (builder added the plugin in 07c0c51)
through `open_page`. Nothing here skips, because the gate rejects skip/xfail in tests/phase5.
"""

from __future__ import annotations

import functools
import http.server
import subprocess
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.sync_api import Page

from .helpers import OUT_DIR, WEB


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serves web/out like a static host with trailingSlash: /lab/ -> lab/index.html, and
    any unknown path -> 404.html with a real 404 status. Local only; Vercel's headers are not
    applied here (the live gate checks those), so header tests read the build's config."""

    out_dir: Path = OUT_DIR
    requests: list[str] = []

    def log_message(self, *args: object) -> None:  # keep pytest output clean
        pass

    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        type(self).requests.append(self.path)
        super().do_GET()

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        page = self.out_dir / "404.html"
        if code == 404 and page.is_file():
            body = page.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        super().send_error(code, message, explain)


class _Server(http.server.ThreadingHTTPServer):
    """The stdlib default listen backlog is 5; Chromium opens many parallel connections plus route
    prefetches, and the overflow shows up as a spurious net::ERR_CONNECTION_RESET in a page's
    console (seen once on /lab/, not reproducible after this). A deep backlog removes that test-
    infrastructure flake so a console error always means the site."""

    request_queue_size = 256
    daemon_threads = True


@pytest.fixture(scope="session")
def out_dir() -> Path:
    """web/out, built if missing. A failed build fails the test; it is never skipped."""
    if not (OUT_DIR / "build.json").is_file():
        subprocess.run(["npm", "ci"], cwd=WEB, check=True)
        subprocess.run(["npm", "run", "build"], cwd=WEB, check=True)
    assert (OUT_DIR / "index.html").is_file(), "web/out/index.html missing after build"
    return OUT_DIR


@pytest.fixture(scope="session")
def site(out_dir: Path) -> Iterator[str]:
    """Base URL of a static server over web/out, on an ephemeral port."""
    handler = functools.partial(_Handler, directory=str(out_dir))
    _Handler.out_dir = out_dir
    server = _Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def open_page(browser, site: str) -> Iterator[Callable[..., Page]]:  # noqa: ANN001
    """Factory: open_page("/lab/?s=optimistic", width=1440, height=900, reduced_motion=False)
    returns a loaded Page. `browser` is pytest-playwright's. Console errors, page errors,
    failed responses and every request URL are collected on `page.qday` for the assertions."""
    contexts = []

    def _open(
        route: str,
        width: int = 1440,
        height: int = 900,
        reduced_motion: bool = False,
        wait: str = "networkidle",
    ) -> Page:
        ctx = browser.new_context(
            viewport={"width": width, "height": height},
            reduced_motion="reduce" if reduced_motion else "no-preference",
        )
        contexts.append(ctx)
        page = ctx.new_page()
        log = SimpleNamespace(console=[], pageerrors=[], bad_responses=[], requests=[], base=site)
        page.on("console", lambda m: m.type == "error" and log.console.append(m.text))
        page.on("pageerror", lambda e: log.pageerrors.append(str(e)))
        page.on("request", lambda r: log.requests.append(r.url))
        page.on(
            "response",
            lambda r: r.status >= 400 and log.bad_responses.append((r.status, r.url)),
        )
        page.qday = log
        page.response = page.goto(site + route, wait_until=wait)
        return page

    yield _open
    for ctx in contexts:
        ctx.close()
