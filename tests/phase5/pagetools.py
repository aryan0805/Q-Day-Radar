"""Browser-side helpers for the Phase 5 page tests. Owned by reviewer.

figure_audit(page) is the live-DOM version of the brief's provenance check: every number a person
can read must be inside an element that says where it came from (data-src), is a chart tick
(data-axis), or carries a stated reason (data-literal); every data-src must equal the data to the
digits shown.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Page

from .helpers import figure_matches, resolve_src

# Collect traced elements and walk every visible text node outside a traced element.
_COLLECT = """
() => {
  const TRACED = '[data-src],[data-axis],[data-literal]';
  const traced = [...document.querySelectorAll('[data-src]')].map(e => ({
    src: e.getAttribute('data-src'),
    scale: e.getAttribute('data-scale'),
    text: e.textContent.trim(),
    tag: e.tagName.toLowerCase(),
    visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length),
  }));
  const literals = [...document.querySelectorAll('[data-literal]')].map(e => ({
    reason: e.getAttribute('data-literal'), text: e.textContent.trim().slice(0, 60),
  }));
  const loose = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const p = n.parentElement;
    if (!p || p.closest('script,style,noscript,template') || p.closest(TRACED)) continue;
    if (!(p.offsetWidth || p.offsetHeight || p.getClientRects().length)) continue;
    const t = n.textContent;
    if (/\\d/.test(t)) loose.push({text: t.trim().slice(0, 160), tag: p.tagName.toLowerCase()});
  }
  return {traced, literals, loose};
}
"""

# A figure: digits not glued to a letter, underscore or hyphen on either side. This leaves
# identifiers such as RSA-2048, ML-KEM-768, SHA-256, AES-128, ibm_kingston and ISO-ish ids alone,
# which the brief says are not figures. Anything else with digits must be traced.
FIGURE_RE = r"(?<![A-Za-z_\-\d.])[-−+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z_\d])"


def figure_audit(page: Page) -> dict[str, Any]:
    """Audit the page as rendered. Returns lists of problems; all empty = every figure is traced
    and equal to the data (to the digits shown)."""
    import re

    raw = page.evaluate(_COLLECT)
    mismatches: list[str] = []
    unresolved: list[str] = []
    for t in raw["traced"]:
        try:
            actual = resolve_src(t["src"])
        except (KeyError, IndexError, ValueError, FileNotFoundError) as e:
            unresolved.append(f"{t['src']}: {type(e).__name__} {e}")
            continue
        scale = float(t["scale"]) if t["scale"] else 1.0
        try:
            ok, why = figure_matches(t["text"], actual, scale)
        except ValueError as e:  # text that is not a readable figure for a numeric value
            ok, why = False, str(e)
        if not ok:
            mismatches.append(f"{t['src']} shows {t['text']!r}: {why}")
    untraced = [
        f"<{n['tag']}> {n['text']!r}" for n in raw["loose"] if re.search(FIGURE_RE, n["text"])
    ]
    return {
        "n_traced": len(raw["traced"]),
        "mismatches": mismatches,
        "unresolved": unresolved,
        "untraced": untraced,
        "literals": raw["literals"],
    }


def settle(
    page: Page, scenario: str | None = None, quiet_ms: int = 400, timeout_ms: int = 10000
) -> None:
    """Wait until the page has finished hydrating: the scenario switch shows the requested scenario
    (the brief applies ?s= on hydration) and the number of traced figures has stopped changing.
    Auditing before this would test a half-rendered page and could miss figures."""
    if scenario:
        page.wait_for_function(
            "sc => document.querySelector('[role=radio][aria-checked=true]')"
            "?.dataset.scenario === sc",
            arg=scenario,
            timeout=timeout_ms,
        )
    waited, stable, last = 0, 0, -1
    while waited < timeout_ms and stable < quiet_ms:
        n = page.locator("[data-src]").count()
        stable = stable + 100 if n == last else 0
        last = n
        page.wait_for_timeout(100)
        waited += 100
    assert stable >= quiet_ms, f"the page never settled ({last} traced figures still changing)"


def wake_hero(page: Page, timeout_ms: int = 10000) -> None:
    """Make the first interaction (the hero and the eggs load on it, builder 5c) and wait until the
    hero has rendered its glossary term for the compiled circuit. Without this the hero's text and
    figures do not exist yet."""
    page.mouse.move(200, 300)
    page.mouse.wheel(0, 300)
    page.wait_for_selector(".hero-stage .gloss[data-term='compiled']", timeout=timeout_ms)


# ---------------------------------------------------------------------------- script budget

GSAP_MARKERS = ("GSAP target", "gsap.com")
BUDGET_BYTES = 200_000  # gzip -9 of the JS fetched before the first interaction (lead, 2026-11-08)
# inline <script> bodies that are executable (the CSP rule in helpers.INLINE_JS_TYPES)
_INLINE = """
() => [...document.scripts]
  .filter(s => !s.src && s.textContent.trim() &&
               ['', 'text/javascript', 'application/javascript', 'module'].includes(s.type))
  .map(s => s.textContent)
"""


@dataclass(frozen=True)
class Script:
    url: str
    gz: int  # gzip -9 of the body, in bytes
    gsap: bool  # the body contains GSAP (found by content, so a renamed chunk is still found)
    inline: bool = False


def gz9(data: bytes) -> int:
    return len(gzip.compress(data, 9))


def script_report(page: Page) -> list[Script]:
    """Every script the page has received so far: each JS response body and each executable inline
    script, gzip -9 each. Needs `page.qday.responses` (conftest.open_page collects them)."""
    out: list[Script] = []
    for r in page.qday.responses:
        ctype = r.headers.get("content-type", "")
        if not (r.url.split("?")[0].endswith(".js") or "javascript" in ctype):
            continue
        try:
            body = r.body()
        except Exception:  # an aborted request has no body; it was not delivered either
            continue
        out.append(Script(r.url, gz9(body), any(m.encode() in body for m in GSAP_MARKERS)))
    for i, text in enumerate(page.evaluate(_INLINE)):
        out.append(Script(f"inline#{i}", gz9(text.encode("utf-8")), False, inline=True))
    return out


def total_gz(scripts: list[Script]) -> int:
    return sum(s.gz for s in scripts)


def gsap_requested(scripts: list[Script]) -> list[str]:
    return [s.url for s in scripts if s.gsap]


def idle_without_interacting(page: Page, extra_ms: int = 5000) -> None:
    """The load-time state the budget is measured in: network idle, then a further wait for any
    timer-started chunk (builder: a hero chunk loads 1.2 s after load in reduced motion)."""
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(extra_ms)


def seeded_random(seed: int) -> str:
    """An init script that replaces Math.random with a seeded generator (mulberry32), so egg tests
    that use randomness are deterministic and repeatable."""
    return (
        "(() => { let a = "
        + str(seed)
        + " >>> 0; Math.random = () => { a = (a + 0x6D2B79F5) | 0;"
        + " let t = Math.imul(a ^ (a >>> 15), 1 | a);"
        + " t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;"
        + " return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; })();"
    )
