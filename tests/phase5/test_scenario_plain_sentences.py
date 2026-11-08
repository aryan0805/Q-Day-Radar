"""Scenario sentences are derived from their inputs (lead's note, 2026-11-08), like order_notes.

For each generator that writes a sentence about a scenario (scenario_plain, order_plain,
scenario_notes), a flip-an-input test: change ONE input in a deep copy, run the builder's own
function, and the sentence must change in the matching way and only in the flipped scenario. A
sentence that stays put whatever the data says is a constant, and a constant is a typed claim.
"""

from __future__ import annotations

import copy

import pytest

from quantum.risk import inventory, webdata

from .helpers import SCENARIOS, load_data


@pytest.fixture(scope="module")
def timeline() -> dict:
    return inventory.load_timeline()


@pytest.fixture(scope="module")
def est() -> dict:
    return webdata._json(webdata.EST / "scenarios.json")


@pytest.fixture(scope="module")
def inv() -> dict:
    return load_data("inventory")


@pytest.fixture(scope="module")
def mo(timeline, est) -> dict:  # noqa: ANN001
    return webdata.model_only(timeline, est)


# --------------------------------------------------------------- the shipped text is the output


def test_scenario_shipped_plain_sentences_are_what_the_generators_return(
    timeline, est, inv, mo
) -> None:  # noqa: ANN001
    scen = load_data("scenarios")
    assert webdata.scenario_plain(timeline, est) == scen["scenario_plain"]
    assert webdata.order_plain(inv, mo) == scen["order_plain"]
    assert webdata.scenario_notes(timeline) == scen["scenario_notes"]


# ----------------------------------------------------------------------------- scenario_plain


def _plain(timeline, est):  # noqa: ANN001, ANN202
    return webdata.scenario_plain(timeline, est)


@pytest.mark.parametrize("sc", ["optimistic", "pessimistic"])
@pytest.mark.parametrize(("factor", "word"), [(10.0, "slower"), (0.1, "faster")])
def test_scenario_plain_cycle_time_flip_changes_the_sentence(
    timeline, est, sc, factor, word
) -> None:  # noqa: ANN001
    e = copy.deepcopy(est)
    median_cycle = e["scenarios"]["median"]["qec_scheme"]["cycle_time_seconds"]
    e["scenarios"][sc]["qec_scheme"]["cycle_time_seconds"] = median_cycle * factor
    after = _plain(timeline, e)[sc]
    # with a second difference the clauses are joined and "than the median" ends the sentence,
    # so assert the word, not the full phrase
    assert f"chips that run {word}" in after and after.endswith("than the median."), after
    others = [s for s in SCENARIOS if s != sc]
    assert all(_plain(timeline, e)[o] == _plain(timeline, est)[o] for o in others)


@pytest.mark.parametrize("sc", ["optimistic", "pessimistic"])
def test_scenario_plain_equal_cycle_time_drops_the_clause(timeline, est, sc) -> None:  # noqa: ANN001
    e = copy.deepcopy(est)
    e["scenarios"][sc]["qec_scheme"]["cycle_time_seconds"] = e["scenarios"]["median"]["qec_scheme"][
        "cycle_time_seconds"
    ]
    assert "chips that run" not in _plain(timeline, e)[sc]


@pytest.mark.parametrize("sc", ["optimistic", "pessimistic"])
@pytest.mark.parametrize(("factor", "word"), [(10.0, "more"), (0.1, "fewer")])
def test_scenario_plain_error_rate_flip_changes_the_sentence(
    timeline, est, sc, factor, word
) -> None:  # noqa: ANN001
    e = copy.deepcopy(est)
    e["scenarios"][sc]["physical_error_rate"] = (
        e["scenarios"]["median"]["physical_error_rate"] * factor
    )
    assert f"chips that make {word} errors than the median" in _plain(timeline, e)[sc]


def test_scenario_plain_growth_phrase_follows_the_fitted_doubling_time(timeline, est) -> None:  # noqa: ANN001
    fit = timeline["fit"]
    phrase = {
        fit["ci95"][0]: "as fast as the trend allows",
        fit["doubling_years"]: "along the central trend",
        fit["ci95"][1]: "as slowly as the trend allows",
    }
    assert len(phrase) == 3, "the three growth rates must differ for the phrases to be distinct"
    for sc in SCENARIOS:
        for years, text in phrase.items():
            t = copy.deepcopy(timeline)
            t["scenarios"][sc]["doubling_years"] = years
            assert text in _plain(t, est)[sc], (sc, years)
    t = copy.deepcopy(timeline)
    t["scenarios"]["median"]["doubling_years"] = 123.456  # a rate that is not on the fit
    assert "hardware growth from the fit" in _plain(t, est)["median"]


def test_scenario_plain_no_sentence_is_constant(timeline, est) -> None:  # noqa: ANN001
    base = _plain(timeline, est)
    assert len(set(base.values())) == 3, "three scenarios, three different sentences"
    e = copy.deepcopy(est)
    e["scenarios"]["median"]["qec_scheme"]["cycle_time_seconds"] *= 100
    assert _plain(timeline, e) != base  # moving the reference moves every comparison with it


# ----------------------------------------------------------------------------------- order_plain


def test_scenario_order_plain_names_the_first_family_from_the_order(inv, mo) -> None:  # noqa: ANN001
    first = {s: webdata.PLAIN_FAMILY[inv["family_order"][s][0]] for s in SCENARIOS}
    for sc, sentence in webdata.order_plain(inv, mo).items():
        assert sentence.lower().startswith(first[sc].lower()), (sc, sentence)


def test_scenario_order_plain_swapping_the_first_two_families_swaps_the_sentence(inv, mo) -> None:  # noqa: ANN001
    i = copy.deepcopy(inv)
    order = i["family_order"]["median"]
    dated = [
        f
        for f in order
        if any(
            a["family"] == f and a["by_scenario"]["median"]["crqc_basis"] == inventory.CRQC_LABEL
            for a in i["assets"]
        )
    ]
    assert len(dated) >= 2, "this test needs two families with a break date in median"
    a, b = order.index(dated[0]), order.index(dated[1])
    order[a], order[b] = order[b], order[a]
    after = webdata.order_plain(i, mo)["median"]
    assert after.lower().startswith(webdata.PLAIN_FAMILY[dated[1]].lower()), after
    assert after != webdata.order_plain(inv, mo)["median"]


def test_scenario_order_plain_no_dated_family_says_nothing_finishes(inv, mo) -> None:  # noqa: ANN001
    i = copy.deepcopy(inv)
    for a in i["assets"]:
        a["by_scenario"]["median"]["crqc_basis"] = "none"
    assert "No quantum attack finishes" in webdata.order_plain(i, mo)["median"]


@pytest.mark.parametrize("sc", SCENARIOS)
def test_scenario_order_plain_keeps_acronyms_in_capitals(inv, mo, sc) -> None:  # noqa: ANN001
    # str.capitalize() lowercases the rest of the string: "(ECC)" would become "(ecc)"
    sentence = webdata.order_plain(inv, mo)[sc]
    for term in webdata.PLAIN_FAMILY.values():
        if term.lower() in sentence.lower():
            assert term[0].upper() + term[1:] in sentence or term in sentence, (
                f"{term!r} lost its capitals in {sentence!r}"
            )
    assert "(ecc)" not in sentence, sentence


# ------------------------------------------------------------------------------- scenario_notes


def test_scenario_notes_follow_the_runtime_cap_and_runtimes(timeline) -> None:  # noqa: ANN001
    base = webdata.scenario_notes(timeline)
    t = copy.deepcopy(timeline)
    t["runtime_cap_years"] = 1e-12  # every Shor attack now exceeds the cap
    low = webdata.scenario_notes(t)
    assert all("exceeds the" in low[s] and "runtime cap" in low[s] for s in SCENARIOS)
    assert any(low[s] != base[s] for s in SCENARIOS)
    t["runtime_cap_years"] = 1e12  # nothing exceeds it
    high = webdata.scenario_notes(t)
    assert all("fits inside the runtime cap" in high[s] for s in SCENARIOS)


def test_scenario_notes_print_the_runtimes_they_are_derived_from(timeline) -> None:  # noqa: ANN001
    t = copy.deepcopy(timeline)
    t["runtime_cap_years"] = 1e-12
    note = webdata.scenario_notes(t)["median"]
    for target in ("rsa2048", "ecc256"):
        years = (
            t["scenarios"]["median"]["targets"][target]["runtime_seconds"]
            / webdata.SECONDS_PER_YEAR
        )
        assert f"{target} {years:.3g} y" in note
    assert "aes128" not in note, "Grover is not a Shor attack"
