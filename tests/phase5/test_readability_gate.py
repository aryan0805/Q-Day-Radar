"""Readability of the plain layer (human tweak round 1): the gate's scorer, plus mutation tests.

The scorer is scripts/gate.py `p5_readability` and `_p5_plain_text` (no second scorer here): the
plain layer of each screen must score Flesch-Kincaid grade <= 9 and <= 20 words per sentence
(textstat), have >= 50 plain words, and have a data-layer="technical" detail. This file (1) runs it
on the real build, (2) runs it on synthetic sites to prove it FAILS on hard prose, on one overlong
sentence, on too little prose and on a missing technical layer, and PASSES on plain prose, and
(3) checks what counts as plain text. Flesch-Kincaid is a rough proxy (textstat's syllable
heuristic); the AUDIT says so. It measures sentence and word length, not whether a sentence is
true or clear.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from .helpers import REPO

SCREENS = ("index.html", "lab/index.html", "scaling/index.html", "inventory/index.html")


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("qday_gate", REPO / "scripts" / "gate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["qday_gate"] = mod  # dataclasses in gate.py look their module up by name
    spec.loader.exec_module(mod)  # defines functions and constants; main() is not run
    return mod


PLAIN = (
    "This page shows what the project found. Each dot is one piece of cryptography. "
    "The closer a dot is to the centre, the less time is left. A red dot is at risk now. "
    "You can pick a scenario at the top of the page. "
    "The numbers come from files in the data folder. "
    "Hover over a number to see where it came from. Nothing on this page is typed by hand."
)
HARD = (
    "Notwithstanding considerable methodological heterogeneity, the cryptographically relevant "
    "quantum computational infrastructure necessitates comprehensive architectural reconsideration "
    "of asymmetric authentication primitives, particularly concerning interoperability constraints "
    "inherent in institutionally entrenched certificate hierarchies. "
    "Correspondingly, organizational "
    "migration prioritization fundamentally depends upon probabilistic extrapolation methodologies "
    "whose uncertainty characterizations remain insufficiently standardized."
)
ONE_LONG_SENTENCE = (
    "This page shows the dots and each one is a piece of cryptography and the closer a dot is to "
    "the middle the less time is left and a red dot is at risk now and you can pick a scenario at "
    "the top and the numbers come from files in the data folder and you can hover over a number to "
    "see where it came from and nothing on this page is typed by hand and everything is checked."
)
TECH = '<details data-layer="technical"><summary>Technical detail</summary><p>x</p></details>'


def site(root: Path, plain: str, *, tech: bool = True, only: str | None = None) -> Path:
    """A synthetic out/ with the four screens; `only` limits the bad prose to one screen."""
    for rel in SCREENS:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        body = plain if only is None or rel == only else PLAIN
        f.write_text(
            f"<html><body><header><p>{HARD}</p></header><main><h1>Title</h1><p>{body}</p>"
            f"{TECH if tech else ''}</main><footer><p>{HARD}</p></footer></body></html>"
        )
    return root


def run(gate: ModuleType, monkeypatch, out: Path):  # noqa: ANN001, ANN202
    monkeypatch.setattr(gate, "P5_OUT", out)
    return gate.p5_readability()


# ----------------------------------------------------------------------------- the real build


def test_readability_the_real_plain_layer_passes_the_gate_scorer(gate) -> None:  # noqa: ANN001
    ok, detail = gate.p5_readability()
    assert ok, detail
    assert "grade" in detail and "tech" in detail, "the scorer reported nothing: " + detail


# ----------------------------------------------------------------------- mutations: must FAIL


def test_readability_hard_long_sentences_fail(gate, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    ok, detail = run(gate, monkeypatch, site(tmp_path, HARD))
    assert not ok
    assert "grade" in detail and "words/sentence" in detail, detail


def test_readability_one_overlong_sentence_of_easy_words_fails_on_length(
    gate, monkeypatch, tmp_path
) -> None:  # noqa: ANN001
    ok, detail = run(gate, monkeypatch, site(tmp_path, ONE_LONG_SENTENCE))
    assert not ok and "words/sentence" in detail, detail


def test_readability_one_bad_screen_fails_the_whole_check_and_names_it(
    gate, monkeypatch, tmp_path
) -> None:  # noqa: ANN001
    ok, detail = run(gate, monkeypatch, site(tmp_path, HARD, only="scaling/index.html"))
    assert not ok and "/scaling/" in detail, detail
    assert "/lab/:" not in detail.split("grade")[0], "a good screen was blamed"


def test_readability_too_little_plain_text_fails_not_scores_well(
    gate, monkeypatch, tmp_path
) -> None:  # noqa: ANN001
    ok, detail = run(gate, monkeypatch, site(tmp_path, "Short and simple."))
    assert not ok and "plain words" in detail, detail


def test_readability_a_screen_without_a_technical_layer_fails(gate, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    ok, detail = run(gate, monkeypatch, site(tmp_path, PLAIN, tech=False))
    assert not ok and "technical" in detail, detail


def test_readability_a_missing_screen_fails(gate, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    out = site(tmp_path, PLAIN)
    (out / "lab" / "index.html").unlink()
    ok, detail = run(gate, monkeypatch, out)
    assert not ok and "not built" in detail, detail


# --------------------------------------------------------------------- and plain prose PASSES


def test_readability_plain_short_sentences_pass(gate, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    ok, detail = run(gate, monkeypatch, site(tmp_path, PLAIN))
    assert ok, detail


# ---------------------------------------------------------------- what counts as plain text


def test_readability_text_in_the_technical_layer_is_not_scored(gate) -> None:  # noqa: ANN001
    html = f'<main><p>{PLAIN}</p><div data-layer="technical"><p>{HARD}</p></div></main>'
    text, n_tech = gate._p5_plain_text(html)
    assert n_tech == 1
    assert "heterogeneity" not in text and "Hover over a number" in text


def test_readability_text_outside_main_and_headings_are_not_scored(gate) -> None:  # noqa: ANN001
    html = (
        f"<header><p>{HARD}</p></header><main><h1>{HARD}</h1><p>{PLAIN}</p></main>"
        f"<footer><p>{HARD}</p></footer>"
    )
    text, _ = gate._p5_plain_text(html)
    assert "heterogeneity" not in text and "methodological" not in text
    assert text.startswith("This page shows")


def test_readability_a_hard_sentence_hidden_in_a_list_item_is_scored(gate) -> None:  # noqa: ANN001
    text, _ = gate._p5_plain_text(f"<main><ul><li>{HARD}</li></ul></main>")
    assert "heterogeneity" in text
