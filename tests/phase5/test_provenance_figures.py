"""Provenance, live DOM: every figure on every screen traces to the data (task 9, brief row 1).

Threshold (fixed before BUILD): 0 untraced figures, 0 mismatches beyond half the last digit shown,
in each of the 3 scenarios on each of the 4 screens; each screen has >= 1 traced value; a planted
wrong figure fails. The static (build output) half of the same rule is the gate's.
"""

from __future__ import annotations

import re

import pytest

from .helpers import ROUTES, SCENARIOS, load_data
from .pagetools import FIGURE_RE, figure_audit, settle, wake_hero

COMBOS = [(r, s) for r in ROUTES for s in SCENARIOS]


@pytest.mark.parametrize(("route", "scenario"), COMBOS)
def test_provenance_every_figure_is_traced_and_equals_the_data(open_page, route, scenario) -> None:  # noqa: ANN001
    page = open_page(f"{route}?s={scenario}")
    settle(page, scenario)
    audit = figure_audit(page)
    assert audit["n_traced"] >= 1, "a screen with no traced value shows nothing from the data"
    assert audit["unresolved"] == [], audit["unresolved"][:5]
    assert audit["mismatches"] == [], audit["mismatches"][:5]
    assert audit["untraced"] == [], audit["untraced"][:8]
    for lit in audit["literals"]:
        assert lit["reason"].strip(), f"data-literal with no reason: {lit['text']!r}"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_provenance_home_hero_discloses_that_the_circuit_is_compiled(open_page, scenario) -> None:  # noqa: ANN001
    # The plain-language copy says "simplified demo version" and carries the exact term in the
    # glossary tooltip ("Exact term: compiled"). The data says compiled; the page must too, in a
    # way a keyboard user can reach, and must never call the circuit generic.
    page = open_page(f"/?s={scenario}")
    settle(page, scenario)
    wake_hero(page)
    assert load_data("hero")["circuit"]["kind"] == "compiled"
    term = page.locator(".hero-stage .gloss[data-term='compiled']")
    assert term.count() == 1
    assert term.get_attribute("tabindex") == "0", "the disclosure must be keyboard-reachable"
    term.focus()
    tip = page.locator("[role=tooltip]")
    tip.wait_for(state="visible", timeout=3000)
    shown = tip.inner_text().lower()
    assert "compiled" in shown and "already built in" in shown, shown
    hero_text = page.locator(".hero-stage").inner_text().lower()
    assert "generic" not in hero_text, "the hero must not describe the circuit as generic Shor"
    assert load_data("hero")["hardware"]["backend"] in hero_text


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_provenance_home_figures_are_traced_after_the_hero_loads(open_page, scenario) -> None:  # noqa: ANN001
    # the hero's own figures (job ids, counts, finish time) only exist once its chunk has loaded
    page = open_page(f"/?s={scenario}")
    settle(page, scenario)
    before = figure_audit(page)["n_traced"]
    wake_hero(page)
    settle(page, scenario)
    audit = figure_audit(page)
    assert audit["n_traced"] > before, "waking the hero added no traced figure: is it a no-op?"
    assert any(True for _ in page.locator("[data-src^='hero:']").all()), (
        "no hero:* figure on screen"
    )
    assert audit["unresolved"] == [] and audit["mismatches"] == [], (
        audit["unresolved"][:3] + audit["mismatches"][:3]
    )
    assert audit["untraced"] == [], audit["untraced"][:8]


# ------------------------------------------------------------- the audit can fail (mutations)


def _first_numeric_src(page) -> str:  # noqa: ANN001
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-src]')]
            .find(e => /^[-−]?\\d[\\d,.]*$/.test(e.textContent.trim()) && !e.dataset.scale
                       && !e.dataset.src.startsWith('hero:'))?.dataset.src"""
    )


def test_provenance_a_planted_wrong_figure_is_caught(open_page) -> None:  # noqa: ANN001
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    assert figure_audit(page)["mismatches"] == []
    src = _first_numeric_src(page)
    assert src, "no plain numeric figure to mutate"
    page.evaluate(
        """src => { const e = document.querySelector(`[data-src="${src}"]`);
                   e.textContent = String(Number(e.textContent.replace(/,/g, '')) + 1); }""",
        src,
    )
    mism = figure_audit(page)["mismatches"]
    assert len(mism) == 1 and mism[0].startswith(src), mism


def test_provenance_a_planted_untraced_figure_is_caught(open_page) -> None:  # noqa: ANN001
    page = open_page("/scaling/?s=median")
    settle(page, "median")
    assert figure_audit(page)["untraced"] == []
    page.evaluate(
        "() => document.querySelector('main')"
        ".insertAdjacentHTML('beforeend', '<p>Q-Day is 2031.5</p>')"
    )
    assert any("2031.5" in u for u in figure_audit(page)["untraced"])


def test_provenance_a_planted_dead_path_is_caught(open_page) -> None:  # noqa: ANN001
    page = open_page("/lab/?s=median")
    settle(page, "median")
    page.evaluate(
        "() => document.querySelector('[data-src]')"
        ".setAttribute('data-src', 'lab:circuits[999].nope')"
    )
    assert len(figure_audit(page)["unresolved"]) == 1


def test_provenance_a_dropped_data_scale_is_caught(open_page) -> None:  # noqa: ANN001
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    scaled = page.locator("[data-src][data-scale]")
    assert scaled.count() >= 1, "expected at least one percent-style figure on Inventory"
    src = scaled.first.get_attribute("data-src")
    scaled.first.evaluate("e => e.removeAttribute('data-scale')")
    assert any(m.startswith(src) for m in figure_audit(page)["mismatches"])


def test_provenance_a_data_literal_without_a_reason_is_listed(open_page) -> None:  # noqa: ANN001
    page = open_page("/scaling/?s=median")
    settle(page, "median")
    page.evaluate(
        "() => document.querySelector('main').insertAdjacentHTML("
        "'beforeend', '<p><span data-literal=\"\">768</span></p>')"
    )
    lits = figure_audit(page)["literals"]
    assert any(not l["reason"].strip() for l in lits)  # noqa: E741


# --------------------------------------------------- what counts as a figure (the regex itself)


@pytest.mark.parametrize(
    "identifier",
    [
        "RSA-2048",
        "ECC-256",
        "AES-128",
        "ML-KEM-768",
        "ML-DSA-65",
        "SHA-256",
        "ecc256",
        "rsa2048",
        "ibm_kingston",
        "google2026_physical_qubits_ecc256",
        "P-256",
        "Shor15",
        "SLH-DSA-128s",
    ],
)
def test_provenance_identifiers_are_not_figures(identifier: str) -> None:
    assert re.search(FIGURE_RE, f"uses {identifier} here") is None


@pytest.mark.parametrize("figure", ["2037.2", "13", "1,234", "6.35e6", "-3.1", "42", "(2030)"])
def test_provenance_numbers_are_figures(figure: str) -> None:
    assert re.search(FIGURE_RE, f"value {figure} here")
