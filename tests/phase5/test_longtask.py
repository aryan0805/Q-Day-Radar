"""Long tasks during the hero (task 11, brief table "hero").

Threshold (fixed before BUILD): Chromium at 4x CPU throttle, a PerformanceObserver for `longtask`,
from the hero's start (the first interaction, when its chunks load) to its end (scrolled through and
replayed): no long task. A long task is by definition one over 50 ms, so "no long task > 50 ms" is
zero entries. Proofs that a zero means something: the throttle is real (the same workload takes
clearly longer), and a deliberate 120 ms busy loop IS reported.
"""

from __future__ import annotations

import pytest

from .pagetools import settle

OBSERVER = """
(() => {
  window.__lt = [];
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) window.__lt.push({start: e.startTime, dur: e.duration});
  }).observe({type: 'longtask', buffered: true});
})();
"""
_WORK = """() => {
  const t = performance.now(); let x = 0;
  for (let i = 0; i < 4e6; i += 1) x += Math.sqrt(i);
  return performance.now() - t;
}"""
THROTTLE = 4.0


def _best_of(page, n: int = 9) -> float:  # noqa: ANN001
    return min(page.evaluate(_WORK) for _ in range(n))


def _hero_run(page) -> None:  # noqa: ANN001
    """Wake the hero, scroll through its whole runway, then replay it to the end."""
    page.mouse.move(200, 300)
    page.mouse.wheel(0, 120)
    page.wait_for_selector(".hero-stage .gloss[data-term='compiled']", timeout=30000)
    page.wait_for_timeout(800)
    runway = page.evaluate(
        "() => document.querySelector('.hero-wrap').getBoundingClientRect().height"
    )
    y = 0
    while y < runway:
        page.mouse.wheel(0, 120)
        page.wait_for_timeout(60)
        y += 120
    page.wait_for_timeout(1500)
    page.evaluate("() => scrollTo(0, 0)")
    page.wait_for_timeout(800)
    page.get_by_role("button", name="Replay the sequence").click()
    page.wait_for_function(
        "() => parseFloat(getComputedStyle("
        "document.querySelectorAll('.hero-layer')[3]).opacity) >= 0.95",
        timeout=60000,
    )
    page.wait_for_timeout(1000)


# ----------------------------------------------------------------- the throttle is real


def test_longtask_the_cpu_throttle_really_slows_the_page_down(open_page) -> None:  # noqa: ANN001
    # CDP rate 4 is a setting, not a measured factor: over 19 trials on this machine the same JS
    # workload took 1.6 to 3.3 times as long, and the spread follows machine load. Without any
    # throttle the ratio sits near 1.0, so the claim tested is "clearly slowed" (above 1.4); the
    # AUDIT reports the measured range and states the long-task result at that slowdown.
    fast = _best_of(open_page("/?s=median", init_script=OBSERVER))
    slow = _best_of(open_page("/?s=median", init_script=OBSERVER, cpu_throttle=THROTTLE))
    assert slow / fast > 1.4, (
        f"throttled {slow:.1f} ms vs {fast:.1f} ms: the throttle is not applied"
    )
    unthrottled_again = _best_of(open_page("/?s=median", init_script=OBSERVER))
    assert 0.6 < unthrottled_again / fast < 1.6, "the unthrottled timing is too noisy to compare"


def test_longtask_the_observer_reports_a_deliberate_long_task_under_throttle(open_page) -> None:  # noqa: ANN001
    # The busy loop must run as a page task (a timer), the way real site code runs: work executed
    # through the DevTools protocol (page.evaluate) is not attributed as a long task, which this
    # test found out the hard way when its first version saw nothing.
    page = open_page("/?s=median", init_script=OBSERVER, cpu_throttle=THROTTLE)
    settle(page, "median")
    page.evaluate(
        "() => { setTimeout(() => { const t = performance.now();"
        " while (performance.now() - t < 120); }, 0); }"
    )
    page.wait_for_timeout(800)
    tasks = page.evaluate("() => window.__lt")
    assert any(t["dur"] >= 100 for t in tasks), f"a 120 ms busy loop was not reported: {tasks}"


# ------------------------------------------------------------------------------ the hero


def test_longtask_there_is_no_long_task_from_hero_start_to_end(open_page) -> None:  # noqa: ANN001
    page = open_page("/?s=median", init_script=OBSERVER, cpu_throttle=THROTTLE)
    settle(page, "median")
    page.wait_for_timeout(1000)
    t0 = page.evaluate("() => performance.now()")  # the hero starts at the first interaction
    _hero_run(page)
    tasks = [t for t in page.evaluate("() => window.__lt") if t["start"] >= t0]
    assert tasks == [], (
        f"{len(tasks)} long task(s) during the hero at {THROTTLE:g}x throttle; "
        f"longest {max(t['dur'] for t in tasks):.0f} ms: {tasks[:4]}"
    )


@pytest.mark.parametrize("route", ["/lab/", "/scaling/", "/inventory/"])
def test_longtask_no_long_task_while_the_other_screens_animate_in(open_page, route) -> None:  # noqa: ANN001
    page = open_page(f"{route}?s=median", init_script=OBSERVER, cpu_throttle=THROTTLE)
    settle(page, "median")
    t0 = page.evaluate("() => performance.now()")
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(1500)
    page.mouse.wheel(0, -600)
    page.wait_for_timeout(1500)
    tasks = [t for t in page.evaluate("() => window.__lt") if t["start"] >= t0]
    assert tasks == [], f"{route}: {tasks[:4]}"
