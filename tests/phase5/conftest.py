"""Phase 5 fixtures. Owned by reviewer.

Playwright is imported lazily inside fixtures, so collecting this directory never needs it. A test
that needs a browser errors loudly if pytest-playwright is missing (builder adds it in task 6);
nothing here skips, because the gate rejects skip/xfail in tests/phase5.
"""

from __future__ import annotations

import functools
import http.server
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

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
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser() -> Iterator[object]:
    """One headless Chromium for the session (sync API)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            yield b
        finally:
            b.close()
