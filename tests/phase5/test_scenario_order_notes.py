"""Scenario order notes are built from the data (lead's item 2).

The note for a scenario says whether the computed family order equals the order from the cost model
alone. That sentence must hold exactly when the two lists are equal, so: (1) the shipped notes agree
with the shipped lists in every scenario; (2) the builder's own generator, run on a flipped copy of
the model-only order, changes the sentence; (3) no sentence is the same constant text whatever the
data says (the retired "put RSA first" claim was one).
"""

from __future__ import annotations

import copy

import pytest

from quantum.risk import inventory, webdata

from .helpers import SCENARIOS, load_data

SAME = "equals the order from the base cost model alone"
DIFFERENT = "differs from the order from the base cost model alone"


@pytest.fixture(scope="module")
def inputs() -> tuple[dict, dict, dict]:
    timeline = inventory.load_timeline()
    est = webdata._json(webdata.EST / "scenarios.json")
    return timeline, est, webdata.model_only(timeline, est)


def _says(note: str) -> str:
    assert (SAME in note) != (DIFFERENT in note), (
        f"must make exactly one claim about the order: {note!r}"
    )
    return "same" if SAME in note else "different"


# ------------------------------------------------------------------ the shipped data agrees


@pytest.mark.parametrize("sc", SCENARIOS)
def test_scenario_shipped_note_matches_the_two_shipped_orders(sc: str) -> None:
    scen = load_data("scenarios")
    computed = load_data("inventory")["family_order"][sc]
    model_only = scen["model_only"][sc]["family_order"]
    assert _says(scen["order_notes"][sc]) == ("same" if computed == model_only else "different")


@pytest.mark.parametrize("sc", SCENARIOS)
def test_scenario_shipped_note_lists_exactly_the_families_with_a_finite_year(sc: str) -> None:
    # pessimistic: the RSA attack exceeds the runtime cap, so only ECC has a year and the note
    # lists just ECC. The listed families are the finite-year prefix of the computed order.
    note = load_data("scenarios")["order_notes"][sc]
    listed = note.split("(", 1)[1].split(")", 1)[0].split(" > ")
    computed = load_data("inventory")["family_order"][sc]
    targets = inventory.load_timeline()["scenarios"][sc]["targets"]
    finite = [f for f in computed if webdata._family_year(targets, f) != float("inf")]
    assert listed == finite and listed == computed[: len(listed)] and listed


def test_scenario_the_shipped_notes_are_what_the_generator_returns(inputs) -> None:  # noqa: ANN001
    timeline, est, mo = inputs
    assert webdata.order_notes(timeline, est, mo) == load_data("scenarios")["order_notes"]


# ---------------------------------------------------------------- the flipped copy changes it


def test_scenario_flipping_the_model_only_order_changes_the_sentence(inputs) -> None:  # noqa: ANN001
    timeline, est, mo = inputs
    before = webdata.order_notes(timeline, est, mo)
    for sc in SCENARIOS:
        assert _says(before[sc]) == "same", "this test assumes today's data: order unchanged"
        flipped = copy.deepcopy(mo)
        order = flipped[sc]["family_order"]
        order[0], order[1] = order[1], order[0]  # swap the first two families
        after = webdata.order_notes(timeline, est, flipped)
        assert _says(after[sc]) == "different", sc
        assert after[sc] != before[sc]
        for other in SCENARIOS:  # only the flipped scenario's note moves
            if other != sc:
                assert after[other] == before[other], (sc, other)


def test_scenario_making_the_orders_differ_then_equal_again_round_trips(inputs) -> None:  # noqa: ANN001
    timeline, est, mo = inputs
    base = webdata.order_notes(timeline, est, mo)
    broken = copy.deepcopy(mo)
    broken["median"]["family_order"].reverse()
    assert _says(webdata.order_notes(timeline, est, broken)["median"]) == "different"
    assert webdata.order_notes(timeline, est, mo) == base  # the original was not mutated


def test_scenario_no_note_is_a_constant_sentence(inputs) -> None:  # noqa: ANN001
    # a sentence about the order must depend on the order; strip the data-driven parts and
    # prove the claim changes with the data in both directions
    timeline, est, mo = inputs
    claims = set()
    for sc in SCENARIOS:
        for flip in (False, True):
            m = copy.deepcopy(mo)
            if flip:
                m[sc]["family_order"].reverse()
            claims.add(_says(webdata.order_notes(timeline, est, m)[sc]))
    assert claims == {"same", "different"}


def test_scenario_notes_do_not_assert_unsourced_history(inputs) -> None:  # noqa: ANN001
    timeline, est, mo = inputs
    for note in webdata.order_notes(timeline, est, mo).values():
        assert "put RSA first" not in note and "Roetteler" not in note and "Litinski" not in note
