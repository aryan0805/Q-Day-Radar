"""Easter eggs, all seven (task 11, brief table "eggs"). Every claim is recomputed from scratch.

Thresholds (fixed before BUILD): shor: p*q = N and a^r = 1 (mod N) with r the true order; grover:
found in <= ceil(pi/4*sqrt(N)) steps; coin: the outcome is a key of the cited job's counts in
results/hardware; console: the CTF is solvable from the printed n, e, c alone; no network request
during any egg. Randomness is seeded (Math.random replaced before page load), so every run is the
same run. The eggs load on the first interaction (html[data-eggs=ready]).
Honest limits, stated in AUDIT: the Shift arrow is a fixed illustration beside the pointer, not a
vector computed from the rendered lattice; the coin replays stored counts (the card says so).
"""

from __future__ import annotations

import json
import math
import re
from math import gcd

from .helpers import REPO, load_data
from .pagetools import script_report, seeded_random, settle

KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft",
          "ArrowRight", "b", "a"]  # fmt: skip


# ----------------------------------------------------------------------------- the maths


def is_prime(n: int) -> bool:
    return n >= 2 and all(n % k for k in range(2, math.isqrt(n) + 1))


def order(a: int, n: int) -> int:
    return next(k for k in range(1, n + 1) if pow(a, k, n) == 1)


def shor_problems(n: int, a: int, r: int, p: int, q: int) -> list[str]:
    bad = []
    if p * q != n:
        bad.append(f"{p}*{q} != {n}")
    if not (is_prime(p) and is_prime(q) and p != q):
        bad.append(f"factors {p}, {q} are not two distinct primes")
    if gcd(a, n) != 1:
        bad.append(f"base {a} shares a factor with {n}")
        return bad
    true_r = order(a, n)
    if r != true_r:
        bad.append(f"period {r} is not the order of {a} mod {n} (which is {true_r})")
    if true_r % 2 or pow(a, true_r // 2, n) == n - 1:
        bad.append("this base cannot factor n")
    else:
        h = pow(a, true_r // 2, n)
        if {gcd(h - 1, n), gcd(h + 1, n)} != {p, q}:
            bad.append("the factors are not gcd(a^(r/2) -+ 1, n)")
    return bad


def grover_bound(n: int) -> int:
    return math.ceil(math.pi / 4 * math.sqrt(n))


def grover_success(steps: int, n: int) -> float:
    return math.sin((2 * steps + 1) * math.asin(1 / math.sqrt(n))) ** 2


def solve_ctf(n: int, e: int, c: int) -> int:
    p = next(k for k in range(2, math.isqrt(n) + 1) if n % k == 0)
    d = pow(e, -1, (p - 1) * (n // p - 1))
    return pow(c, d, n)


# ------------------------------------------------------------------------------ the browser


def _eggs(open_page, route: str = "/", seed: int = 1234, **kw):  # noqa: ANN001, ANN202
    page = open_page(f"{route}?s=median", init_script=seeded_random(seed), **kw)
    settle(page, "median")
    return page


def _ready(page) -> int:  # noqa: ANN001
    """Make the first interaction and wait for the egg chunk; returns the request count then."""
    page.mouse.move(300, 300)
    page.mouse.wheel(0, 40)
    page.wait_for_selector("html[data-eggs=ready]", timeout=15000)
    page.wait_for_timeout(300)
    return len(page.qday.requests)


def _no_requests_since(page, mark: int) -> None:  # noqa: ANN001
    new = page.qday.requests[mark:]
    assert new == [], f"an egg made {len(new)} network request(s): {new[:3]}"


def _card(page, kind: str):  # noqa: ANN001, ANN202
    return page.locator(f"aside.egg-card[data-egg-result='{kind}']")


def _dismiss(page) -> None:  # noqa: ANN001
    page.keyboard.press("Escape")
    page.locator("aside.egg-card").wait_for(state="detached", timeout=3000)


# ------------------------------------------------------------------------- lazy loading


def test_easteregg_the_chunk_loads_on_first_interaction_not_before(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    assert page.evaluate("() => document.documentElement.dataset.eggs") is None
    assert page.evaluate("() => typeof window.qday") == "undefined"
    _ready(page)
    assert page.evaluate("() => document.documentElement.dataset.eggs") == "ready"


# ------------------------------------------------------------------------- 1. Konami code


_RGB = """(name) => {
  // resolve any CSS colour (hex, rgb or oklch) to rgb by painting it on a 1x1 canvas
  const probe = document.createElement('i');
  probe.style.color = 'var(' + name + ')';
  document.body.append(probe);
  const css = getComputedStyle(probe).color;
  probe.remove();
  const ctx = document.createElement('canvas').getContext('2d');
  ctx.fillStyle = css;
  ctx.fillRect(0, 0, 1, 1);
  return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
}"""


def _close(a: list[float], b: list[float], tol: float = 3.0) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def test_easteregg_konami_flips_the_palette_to_threat_and_back(open_page) -> None:  # noqa: ANN001
    # compared as rendered colours: --threat is written in OKLCH, the egg's override in hex
    page = _eggs(open_page)
    mark = _ready(page)
    before = page.evaluate(_RGB, "--q")
    threat = page.evaluate(_RGB, "--threat")
    assert not _close(before, threat), "--q already equals --threat before the code is typed"
    for key in KONAMI:
        page.keyboard.press(key)
    page.wait_for_selector("html[data-qday=on]", timeout=3000)
    banner = page.locator(".egg-banner")
    assert banner.inner_text().strip() == "harvest-now-decrypt-later: engaged"
    assert _close(page.evaluate(_RGB, "--q"), threat), "Q-Day mode must flip the accent to --threat"
    for key in KONAMI:  # the same code reverts
        page.keyboard.press(key)
    page.wait_for_function("() => !document.documentElement.dataset.qday", timeout=3000)
    assert page.locator(".egg-banner").count() == 0
    assert _close(page.evaluate(_RGB, "--q"), before)
    _no_requests_since(page, mark)


# --------------------------------------------------------------------------------- 2. shor


def _shor_rows(page) -> list[dict]:  # noqa: ANN001
    return page.eval_on_selector_all(
        "aside.egg-card [data-egg-row='shor']",
        "ps => ps.map(p => ({n: +p.dataset.n, a: +p.dataset.a, r: +p.dataset.r, p: +p.dataset.p,"
        " q: +p.dataset.q, text: p.textContent.replace(/\\s+/g, ' ').trim()}))",
    )


def test_easteregg_shor_factors_15_and_a_random_semiprime_correctly(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    mark = _ready(page)
    seen = []
    for _ in range(10):  # 10 seeded runs: the second row is a different semiprime each time
        page.keyboard.type("shor")
        _card(page, "shor").wait_for(state="visible", timeout=3000)
        rows = _shor_rows(page)
        assert len(rows) == 2, rows
        assert (rows[0]["n"], rows[0]["a"], rows[0]["r"]) == (15, 7, 4), (
            "first row is textbook N=15"
        )
        for row in rows:
            assert shor_problems(row["n"], row["a"], row["r"], row["p"], row["q"]) == [], row
            assert f"{row['n']} = {row['p']} × {row['q']}" in row["text"]
            assert f"period {row['r']}" in row["text"]
        seen.append(rows[1]["n"])
        _dismiss(page)
    assert len(set(seen)) >= 5, "the second semiprime is not random"
    _no_requests_since(page, mark)


def test_easteregg_shor_says_it_is_a_classical_simulation(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    _ready(page)
    page.keyboard.type("shor")
    text = _card(page, "shor").inner_text().lower()
    assert "classical simulation in your browser" in text
    assert "not by a quantum computer" in text


def test_easteregg_shor_checker_rejects_wrong_answers() -> None:
    assert shor_problems(15, 7, 4, 3, 5) == []
    assert shor_problems(15, 7, 4, 3, 6), "3 * 6 != 15"
    assert shor_problems(15, 7, 2, 3, 5), "period 2 is not the order of 7 mod 15"
    assert shor_problems(15, 5, 2, 3, 5), "base 5 shares a factor with 15"
    assert shor_problems(15, 14, 2, 3, 5), "14 = -1 mod 15: a^(r/2) = -1 cannot give a factor"
    assert shor_problems(21, 8, 2, 3, 7) == [], "8 has order 2 mod 21 and does factor it"


# ------------------------------------------------------------------------------- 3. grover


def test_easteregg_grover_finds_the_key_within_the_step_bound(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    mark = _ready(page)
    for _ in range(3):
        page.keyboard.type("grover")
        card = _card(page, "grover")
        card.wait_for(state="visible", timeout=3000)
        page.wait_for_function(
            "() => /Key \\d+ found in \\d+ steps/.test("
            "document.querySelector('aside.egg-card')?.textContent || '')",
            timeout=8000,
        )
        d = card.evaluate("e => ({n: +e.dataset.n, key: +e.dataset.key, steps: +e.dataset.steps,"
                          " bound: +e.dataset.bound, text: e.textContent})")  # fmt: skip
        assert d["n"] == 256 and 0 <= d["key"] < d["n"]
        assert d["bound"] == grover_bound(d["n"])
        assert 1 <= d["steps"] <= grover_bound(d["n"])
        assert grover_success(d["steps"], d["n"]) > 0.99, "too few steps to claim the key was found"
        assert f"Key {d['key']} found in {d['steps']} steps" in d["text"]
        assert f"at most {d['bound']} for {d['n']} keys" in d["text"]
        hits = card.evaluate(
            "e => [...e.querySelectorAll('.grover-grid i')]"
            ".map((i, k) => i.classList.contains('hit') ? k : -1)"
            ".filter(k => k >= 0)"
        )
        assert hits == [d["key"]], f"the highlighted cell {hits} is not the key {d['key']}"
        assert "classical simulation in your browser" in d["text"].lower()
        _dismiss(page)
    _no_requests_since(page, mark)


def test_easteregg_grover_math_checker_is_right() -> None:
    assert grover_bound(256) == 13
    assert grover_success(12, 256) > 0.9999
    assert grover_success(1, 256) < 0.05, "one step is not enough for 256 keys"
    assert grover_success(25, 256) < 0.5, "too many steps overshoot"


# -------------------------------------------------------------------------------- 4. coin


def _real_counts() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for f in (REPO / "results" / "hardware").glob("*/jobs/*.json"):
        j = json.loads(f.read_text())
        if j.get("status") == "DONE" and j.get("counts"):
            out[j["job_id"]] = {k: int(v) for k, v in j["counts"].items()}
    return out


def _coin_data(page) -> dict:  # noqa: ANN001
    return _card(page, "coin").evaluate(
        "e => ({job: e.dataset.job, outcome: e.dataset.outcome, bit: e.dataset.bit,"
        " text: e.textContent.replace(/\\s+/g, ' ')})"
    )


def test_easteregg_coin_outcome_is_a_key_of_the_cited_jobs_measured_counts(open_page) -> None:  # noqa: ANN001
    real = _real_counts()
    hero_jobs = {j["job_id"] for j in load_data("hero")["hardware"]["jobs"]}
    assert hero_jobs <= set(real), "a hero job is not in results/hardware"
    page = _eggs(open_page)
    mark = _ready(page)
    for _ in range(12):
        page.locator("[data-egg='coin']").click()
        _card(page, "coin").wait_for(state="visible", timeout=3000)
        d = _coin_data(page)
        assert d["job"] in real, f"unknown job {d['job']}"
        assert d["outcome"] in real[d["job"]], (
            f"{d['outcome']} is not a measured outcome of {d['job']}"
        )
        assert d["bit"] == d["outcome"][-1] and d["bit"] in "01"
        assert "ibm_kingston" in d["text"] and d["job"] in d["text"]
        assert "Replayed from stored counts, not a live measurement" in d["text"]
        _dismiss(page)
    _no_requests_since(page, mark)


def test_easteregg_coin_works_from_the_keyboard_and_before_the_chunk_has_loaded(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    coin = page.locator("[data-egg='coin']")
    assert coin.evaluate("e => e.tagName") == "BUTTON" and coin.get_attribute("type") == "button"
    assert "quantum coin" in page.locator(".coin .sr-only").inner_text().lower()
    coin.click()  # a click is the first interaction: it must be replayed once the chunk is in
    _card(page, "coin").wait_for(state="visible", timeout=15000)
    _dismiss(page)
    coin.focus()
    page.keyboard.press("Enter")
    _card(page, "coin").wait_for(state="visible", timeout=3000)


# --------------------------------------------------------------- 5. the console (Bloch + CTF)


def test_easteregg_console_prints_a_bloch_sphere_and_a_solvable_ctf(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    logs: list[str] = []
    page.on("console", lambda m: logs.append(m.text))
    _ready(page)
    text = "\n".join(logs)
    assert "|0>" in text and "|1>" in text and "Bloch sphere" in text
    n, e, c = (int(re.search(rf"\b{k} = (\d+)", text).group(1)) for k in "nec")
    assert not re.search(r"BEGIN [A-Z ]*(KEY|MESSAGE)", text), "the brief says integers, not a PEM"
    m = solve_ctf(n, e, c)  # solved from the three printed integers only
    flag = page.evaluate("(m) => window.qday.flag(m)", m)
    assert flag.startswith("QDAY{") and flag.endswith("}")
    assert page.evaluate("(m) => window.qday.flag(m)", m + 1) == "not the message"
    assert str(m) not in text.replace(f"{n}", "").replace(f"{c}", ""), "the answer is printed"
    assert flag not in text, "the flag is printed"


def test_easteregg_ctf_solver_is_right() -> None:
    assert solve_ctf(3233, 17, pow(1234, 17, 3233)) == 1234
    assert solve_ctf(15, 3, pow(7, 3, 15)) == 7


# ------------------------------------------------------------------------ 6. hold Shift


def test_easteregg_shift_shows_a_vector_at_the_pointer_and_removes_it(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    mark = _ready(page)
    page.mouse.move(420, 310)
    assert page.locator(".egg-vector").count() == 0
    page.keyboard.down("Shift")
    vec = page.locator(".egg-vector")
    vec.wait_for(state="visible", timeout=3000)
    assert "Easy in 2D. Try 768 dimensions." in vec.inner_text()
    assert vec.get_attribute("aria-hidden") == "true"
    box = vec.bounding_box()
    assert abs(box["x"] - 420) < 30 and abs(box["y"] - 310) < 40, box
    page.mouse.move(700, 500)
    page.wait_for_function(
        "() => Math.abs(document.querySelector('.egg-vector').getBoundingClientRect().x - 700) < 30"
    )
    page.keyboard.up("Shift")
    page.locator(".egg-vector").wait_for(state="detached", timeout=3000)
    _no_requests_since(page, mark)


# --------------------------------------------------------------------------------- 7. 404


def test_easteregg_the_404_page_collapses_on_observation(open_page) -> None:  # noqa: ANN001
    page = open_page("/no-such-page/")
    assert page.response.status == 404
    text = page.locator("main").inner_text()
    assert "This page collapsed to |not found⟩ on observation" in text
    svg = page.get_by_role("img", name="Two paths in superposition that collapse into one")
    assert svg.count() == 1
    assert page.locator(".nf-a").count() == 1 and page.locator(".nf-b").count() == 1
    anim = page.evaluate(
        "() => [...document.querySelectorAll('.nf-a, .nf-b')]"
        ".map(e => getComputedStyle(e).animationName)"
    )
    assert all(a != "none" for a in anim), f"the two paths are not animated: {anim}"


# --------------------------------------------------------------------- the rest of the eggs


def test_easteregg_humans_txt_credits_the_three_claude_sessions(open_page, site) -> None:  # noqa: ANN001
    import urllib.request

    with urllib.request.urlopen(site + "/humans.txt", timeout=10) as r:  # noqa: S310
        text = r.read().decode()
    assert "Claude" in text and all(w in text for w in ("lead", "builder", "reviewer"))
    assert "personal project" in text


def test_easteregg_typing_in_a_form_control_does_not_trigger_an_egg(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page, "/inventory/")
    _ready(page)
    select = page.get_by_label("Family")
    select.focus()
    page.keyboard.type("shor")
    page.wait_for_timeout(400)
    assert page.locator("aside.egg-card").count() == 0, "an egg fired while typing in a select"


def test_easteregg_keys_typed_before_the_chunk_has_loaded_are_not_lost(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    page.keyboard.type("shor")  # the very first interaction: the chunk is not in yet
    _card(page, "shor").wait_for(state="visible", timeout=15000)
    assert len(_shor_rows(page)) == 2


def test_easteregg_escape_and_the_close_button_dismiss_the_card(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    _ready(page)
    page.keyboard.type("shor")
    _card(page, "shor").wait_for(state="visible")
    page.get_by_role("button", name="Close").click()
    page.locator("aside.egg-card").wait_for(state="detached", timeout=3000)
    page.keyboard.type("shor")
    _card(page, "shor").wait_for(state="visible")
    _dismiss(page)


# ------------------------------------------------- the light set (human decision, 2026-11-08)

EGG_MARK = "harvest-now-decrypt-later"  # text only the egg chunk contains


def test_easteregg_nothing_egg_related_is_fetched_before_the_first_interaction(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    page.wait_for_timeout(2500)
    before = [s.url for s in script_report(page) if _has(page, s.url, EGG_MARK)]
    assert before == [], f"the egg chunk was fetched before any interaction: {before}"
    _ready(page)
    assert [s for s in script_report(page) if _has(page, s.url, EGG_MARK)], "the chunk never loaded"


def _has(page, url: str, needle: str) -> bool:  # noqa: ANN001
    for r in page.qday.responses:
        if r.url == url:
            try:
                return needle.encode() in r.body()
            except Exception:  # noqa: BLE001
                return False
    return False


def test_easteregg_all_seven_trigger_and_revert_with_no_errors_and_no_requests(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page)
    errors: list[str] = []
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    mark = _ready(page)
    # 1. Konami on, and off again with the same code
    for key in KONAMI:
        page.keyboard.press(key)
    page.wait_for_selector("html[data-qday=on]")
    for key in KONAMI:
        page.keyboard.press(key)
    page.wait_for_function("() => !document.documentElement.dataset.qday")
    assert page.locator(".egg-banner").count() == 0
    # 2. shor, 3. grover, 4. coin: each opens a card and Escape closes it
    page.keyboard.type("shor")
    _card(page, "shor").wait_for(state="visible")
    _dismiss(page)
    page.keyboard.type("grover")
    _card(page, "grover").wait_for(state="visible")
    _dismiss(page)
    page.locator("[data-egg='coin']").click()
    _card(page, "coin").wait_for(state="visible")
    _dismiss(page)
    # 5. console art: printed once the chunk is in (checked in the console test); 6. Shift vector
    page.mouse.move(300, 300)
    page.keyboard.down("Shift")
    page.locator(".egg-vector").wait_for(state="visible")
    page.keyboard.up("Shift")
    page.locator(".egg-vector").wait_for(state="detached")
    _no_requests_since(page, mark)
    # 7. the 404 page
    nf = open_page("/no-such-page/")
    nf_errors = [e for e in nf.qday.console if "404" not in e and "Not Found" not in e]
    assert "collapsed to |not found⟩" in nf.locator("main").inner_text()
    assert errors == [] and nf_errors == [], (errors, nf_errors)


def test_easteregg_the_konami_listener_traps_no_keyboard_focus(open_page) -> None:  # noqa: ANN001
    page = _eggs(open_page, "/inventory/")
    _ready(page)
    page.evaluate(  # registered after the site's listeners, so it sees what they did to each key
        "() => { window.__prevented = []; addEventListener('keydown', e => {"
        " if (e.defaultPrevented) window.__prevented.push(e.key); }); }"
    )
    for key in [*KONAMI, "Tab", "Tab"]:
        page.keyboard.press(key)
    assert page.evaluate("() => window.__prevented") == [], "the egg listener swallowed a key"
    before = page.evaluate("() => document.activeElement?.tagName")
    page.keyboard.press("Tab")
    after = page.evaluate("() => document.activeElement?.tagName")
    assert before and after and page.evaluate("() => document.activeElement !== document.body")
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("() => document.activeElement !== document.body"), "Tab got stuck"
