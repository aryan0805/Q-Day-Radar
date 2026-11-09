"""A figure that depends on the exposure weights must say it is a design choice (lead, 2026-11-08).

The exposure weights (internet, partner, internal) are numbers someone picked. Every figure whose
value changes when they change (rank, shortfall, the weight itself) carries "design choice" in its
provenance label; margins and CRQC years, which they cannot change, must not. "Depends on the
weights" is decided here by recomputation: the Phase 4 reference functions are run on perturbed
weights and the fields that move are the dependent ones. The page check then resolves each figure's
data-src path and requires the label exactly when the value is a dependent field. A flipped copy
(a label removed from a rank, "design choice" put on a margin) must fail.
"""

from __future__ import annotations

import copy
import inspect
import re

import pytest

from tests.phase4 import reference as ref

from .helpers import SCENARIOS, load_data
from .pagetools import settle

# "design choice" or the compound adjective "design-choice" (as in "design-choice weights"):
# both tell a visitor the figure rests on a number someone picked, so both count, in either
# direction (required on a dependent figure, forbidden on a margin or a CRQC year)
PHRASE = re.compile(r"design[\s-]+choice", re.I)
LOOSE = PHRASE
PATH = re.compile(r"^inventory:assets\[(\d+)\]\.(?:by_scenario\.(\w+)\.(\w+)|(exposure_weight))$")
FIELDS = ("rank", "shortfall", "margin_years", "crqc_year")


# ------------------------------------------------------------- dependence, by recomputation


def _outputs(inv: dict, sc: str, weights: dict[str, float]) -> dict[str, dict[str, float | int]]:
    """Per asset: margin, shortfall and rank recomputed with the reference functions."""
    rows = []
    for a in inv["assets"]:
        b = a["by_scenario"][sc]
        m = ref.margin(
            b["crqc_year"], inv["as_of_year"], a["shelf_life_years"], a["migration_years"]
        )
        rows.append((a["id"], weights[a["id"]], m))
    ranks = ref.ranks(rows)
    return {
        i: {"margin_years": m, "shortfall": ref.shortfall(w, m), "rank": ranks[i]}
        for i, w, m in rows
    }


def dependent_fields() -> set[str]:
    """Which per-asset outputs change when the exposure weights change (weights perturbed so that
    the ordering can move: each asset gets a different factor)."""
    inv = load_data("inventory")
    base_w = {a["id"]: a["exposure_weight"] for a in inv["assets"]}
    moved_w = {i: w * (1 + (n % 7) * 0.9) for n, (i, w) in enumerate(base_w.items())}
    changed: set[str] = set()
    for sc in SCENARIOS:
        before, after = _outputs(inv, sc, base_w), _outputs(inv, sc, moved_w)
        for i in before:
            for field in ("margin_years", "shortfall", "rank"):
                if before[i][field] != after[i][field]:
                    changed.add(field)
    return changed


def required_label(src: str) -> bool | None:
    """True: the figure depends on the weights and must say "design choice". False: it cannot
    depend on them and must not. None: this test makes no claim about the figure."""
    m = PATH.match(src)
    if not m:
        return None
    if m.group(4):  # the weight itself
        return True
    leaf = m.group(3)
    if leaf in dependent_fields():
        return True
    if leaf in ("margin_years", "crqc_year"):
        return False
    return None


# ----------------------------------------------------------------- data-level proofs


def test_design_choice_the_dependent_fields_are_found_by_perturbing_the_weights() -> None:
    assert dependent_fields() == {"shortfall", "rank"}, "margins must not depend on the weights"


def test_design_choice_the_margin_function_has_no_weight_to_depend_on() -> None:
    params = set(inspect.signature(ref.margin).parameters)
    assert not {"weight", "exposure_weight", "w"} & params, params
    assert {"weight"} <= set(inspect.signature(ref.shortfall).parameters)


@pytest.mark.parametrize("sc", SCENARIOS)
def test_design_choice_the_shipped_fields_are_what_the_reference_computes(sc: str) -> None:
    # so the perturbation above really describes the shipped numbers
    inv = load_data("inventory")
    weights = {a["id"]: a["exposure_weight"] for a in inv["assets"]}
    out = _outputs(inv, sc, weights)
    for a in inv["assets"]:
        b = a["by_scenario"][sc]
        assert b["rank"] == out[a["id"]]["rank"], a["id"]
        assert b["shortfall"] == pytest.approx(out[a["id"]]["shortfall"]), a["id"]
        if b["margin_years"] is not None:
            assert b["margin_years"] == pytest.approx(out[a["id"]]["margin_years"]), a["id"]


def test_design_choice_required_label_classifies_paths() -> None:
    p = "inventory:assets[3].by_scenario.median."
    assert required_label(p + "rank") is True and required_label(p + "shortfall") is True
    assert required_label("inventory:assets[3].exposure_weight") is True
    assert required_label(p + "margin_years") is False and required_label(p + "crqc_year") is False
    assert required_label(p + "crqc_basis") is None
    assert required_label("scenarios:timeline.baseline.qubits") is None


# --------------------------------------------------------------------------- on the page

_FIGURES = """
() => [...document.querySelectorAll('[data-src]')].map(e => ({
  src: e.getAttribute('data-src'), label: e.getAttribute('data-label') || ''}))
"""


def label_problems(figures: list[dict]) -> dict[str, list[str]]:
    """Every figure that carries a label the rule forbids or lacks one it requires."""
    missing, forbidden, checked = [], [], {"dependent": 0, "independent": 0}
    for f in figures:
        need = required_label(f["src"])
        if need is None:
            continue
        if need:
            checked["dependent"] += 1
            if not PHRASE.search(f["label"]):
                missing.append(f"{f['src']} -> {f['label']!r}")
        else:
            checked["independent"] += 1
            if LOOSE.search(f["label"]):
                forbidden.append(f"{f['src']} -> {f['label']!r}")
    return {"missing": missing, "forbidden": forbidden, "n_dependent": [str(checked["dependent"])],
            "n_independent": [str(checked["independent"])]}  # fmt: skip


def _open_first_drawer(page, sc: str) -> None:  # noqa: ANN001
    inv = load_data("inventory")
    first = min(inv["assets"], key=lambda a: a["by_scenario"][sc]["rank"])
    page.locator(f"tr[data-asset-id='{first['id']}']").get_by_role("button").first.click()
    page.get_by_role("dialog").wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(300)


@pytest.mark.parametrize("sc", SCENARIOS)
def test_design_choice_every_dependent_figure_says_so_and_no_margin_does(open_page, sc) -> None:  # noqa: ANN001
    page = open_page(f"/inventory/?s={sc}")
    settle(page, sc)
    table = label_problems(page.evaluate(_FIGURES))
    assert int(table["n_dependent"][0]) >= 42, "the table shows a rank for every asset"
    assert int(table["n_independent"][0]) >= 42, "the table shows a margin for every asset"
    assert table["missing"] == [], table["missing"][:4]
    assert table["forbidden"] == [], table["forbidden"][:4]
    _open_first_drawer(page, sc)  # the drawer is where the "why" of a score is shown
    drawer = label_problems(page.evaluate(_FIGURES))
    assert drawer["missing"] == [] and drawer["forbidden"] == [], drawer


def test_design_choice_the_tooltip_a_visitor_sees_says_it_too(open_page) -> None:  # noqa: ANN001
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    shown = {}
    for leaf in ("rank", "margin_years"):
        fig = page.locator(f"[data-src$='.{leaf}']").first
        fig.scroll_into_view_if_needed()
        fig.hover()
        page.locator("[role=tooltip]").first.wait_for(state="visible", timeout=3000)
        shown[leaf] = page.locator("[role=tooltip]").first.inner_text()
        page.mouse.move(2, 2)
    assert PHRASE.search(shown["rank"]), shown["rank"]
    assert not LOOSE.search(shown["margin_years"].split("\n")[0]), shown["margin_years"]


# ------------------------------------------------------------------- the flipped copy fails


def test_design_choice_a_label_removed_from_a_rank_is_caught(open_page) -> None:  # noqa: ANN001
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    assert label_problems(page.evaluate(_FIGURES))["missing"] == []
    page.evaluate(
        "() => document.querySelector(\"[data-src$='.rank']\").removeAttribute('data-label')"
    )
    assert len(label_problems(page.evaluate(_FIGURES))["missing"]) == 1


def test_design_choice_a_margin_labelled_design_choice_is_caught(open_page) -> None:  # noqa: ANN001
    page = open_page("/inventory/?s=median")
    settle(page, "median")
    assert label_problems(page.evaluate(_FIGURES))["forbidden"] == []
    page.evaluate(
        "() => document.querySelector(\"[data-src$='.margin_years']\")"
        ".setAttribute('data-label', 'design choice')"
    )
    assert len(label_problems(page.evaluate(_FIGURES))["forbidden"]) == 1


def test_design_choice_a_label_that_never_mentions_it_does_not_satisfy_the_rule() -> None:
    rank = "inventory:assets[0].by_scenario.median.rank"
    assert label_problems([{"src": rank, "label": "computed from data"}])["missing"]
    assert label_problems([{"src": rank, "label": ""}])["missing"]
    for ok in ("design choice", "computed from data, using design-choice exposure weights"):
        assert label_problems([{"src": rank, "label": ok}])["missing"] == [], ok
    margin = "inventory:assets[0].by_scenario.median.margin_years"
    assert label_problems([{"src": margin, "label": "computed from data"}])["forbidden"] == []
    assert label_problems([{"src": margin, "label": "using design-choice weights"}])["forbidden"]


def test_design_choice_the_checker_is_not_vacuous_on_a_flipped_data_copy() -> None:
    # if the weights did not matter, perturbing them would move nothing and the rule would be empty
    inv = copy.deepcopy(load_data("inventory"))
    base = {a["id"]: a["exposure_weight"] for a in inv["assets"]}
    flat = dict.fromkeys(base, 1.0)  # equal weights: shortfall is then just -margin
    ranks_real = {i: v["rank"] for i, v in _outputs(inv, "median", base).items()}
    ranks_flat = {i: v["rank"] for i, v in _outputs(inv, "median", flat).items()}
    assert ranks_real != ranks_flat, (
        "equal weights give the same ranking: the weights do not matter"
    )
