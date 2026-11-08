"""Self-tests of the Phase 5 test helpers (no site needed).

Deliberately named so they do NOT contain any gate keyword (security, tweak, provenance, scenario,
keyboard, smoke, reducedmotion, longtask, easteregg): they must not make those keyword checks
go green before the real site tests exist. They prove the comparison rules catch wrong answers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from .helpers import (
    DATA_DIR,
    SCENARIOS,
    figure_matches,
    load_data,
    parse_shown,
    read_dotenv_values,
    resolve_path,
    resolve_src,
    scan_tree,
)

# ---- path resolution ----


def test_resolve_path_walks_keys_and_indexes() -> None:
    d = {"a": {"b": [{"c": 1}, {"c": 2.5}]}}
    assert resolve_path(d, "a.b[1].c") == 2.5


@pytest.mark.parametrize("bad", ["a.x", "a.b[9]", "a.b[0].z"])
def test_resolve_path_missing_step_raises(bad: str) -> None:
    with pytest.raises((KeyError, IndexError)):
        resolve_path({"a": {"b": [{"c": 1}]}}, bad)


def test_resolve_src_reads_the_real_inventory() -> None:
    inv = load_data("inventory")
    got = resolve_src("inventory:assets[0].by_scenario.median.rank")
    assert got == inv["assets"][0]["by_scenario"]["median"]["rank"]


def test_data_files_the_brief_names_exist() -> None:
    for name in ("inventory", "lab", "scaling", "scenarios", "meta"):
        assert (DATA_DIR / f"{name}.json").is_file(), name
    assert set(SCENARIOS) == set(load_data("inventory")["scenarios"])


# ---- half-last-digit rule ----


@pytest.mark.parametrize(
    ("text", "value", "tol"),
    [
        ("8.73", 8.73, 0.005),
        ("1,234", 1234.0, 0.5),
        ("42%", 42.0, 0.5),
        ("−3.1", -3.1, 0.05),
        ("6.35e6", 6.35e6, 0.5e4),
        ("6.35 × 10⁶", 6.35e6, 0.5e4),
        ("1.12×10^7", 1.12e7, 0.5e5),
    ],
)
def test_parse_shown(text: str, value: float, tol: float) -> None:
    s = parse_shown(text)
    assert s.value == pytest.approx(value)
    assert s.tolerance == pytest.approx(tol)


def test_parse_shown_rejects_prose() -> None:
    with pytest.raises(ValueError):
        parse_shown("about eight")


def test_figure_matches_accepts_rounding_and_rejects_a_wrong_figure() -> None:
    assert figure_matches("8.73", 8.7349)[0]  # rounds to 8.73
    assert figure_matches("8.73", 8.7251)[0]  # rounds to 8.73
    assert not figure_matches("8.73", 8.74)[0]  # off by one in the last digit
    assert not figure_matches("8.73", 87.3)[0]  # decimal slip
    assert not figure_matches("2037", 2038.2)[0]  # the exact kind of slip we guard against


def test_figure_matches_scale_for_percent() -> None:
    assert figure_matches("42%", 0.4249, scale=100)[0]
    assert not figure_matches("42%", 0.4249)[0]  # forgot data-scale


def test_figure_matches_strings_and_nulls() -> None:
    assert figure_matches("ibm_kingston", "ibm_kingston")[0]
    assert not figure_matches("ibm_brisbane", "ibm_kingston")[0]
    assert figure_matches("n/a", None)[0]
    assert not figure_matches("2041.6", None)[0]  # null must show no figure


# ---- secret scan ----


def test_scan_tree_catches_planted_value_and_pattern(tmp_path: Path) -> None:
    (tmp_path / "a.js").write_text("console.log('hello')")
    (tmp_path / "bin.woff2").write_bytes(b"\x00\x01zzCANARY-VALUE-123456zz\x02")
    rx = {"bearer": re.compile(r"Bearer [A-Za-z0-9]{20,}")}
    assert scan_tree(tmp_path, ["CANARY-VALUE-123456"], rx)[0].kind == "value"
    (tmp_path / "b.html").write_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")
    kinds = {(h.file, h.kind) for h in scan_tree(tmp_path, [], rx)}
    assert kinds == {("b.html", "pattern")}


def test_scan_tree_clean_tree_has_no_hits_and_never_leaks_value(tmp_path: Path) -> None:
    (tmp_path / "a.js").write_text("nothing here")
    assert scan_tree(tmp_path, ["SOME-SECRET-VALUE"], {}) == []
    (tmp_path / "a.js").write_text("SOME-SECRET-VALUE")
    (hit,) = scan_tree(tmp_path, ["SOME-SECRET-VALUE"], {})
    assert "SOME-SECRET-VALUE" not in repr(hit)  # failure output must not print the secret


def test_read_dotenv_values_skips_comments_and_trivial_values(tmp_path: Path) -> None:
    f = tmp_path / "env"
    f.write_text("# c\nA=short\nB='a-long-secret-value'\nC=\nnot a pair\n")
    assert read_dotenv_values(f) == ["a-long-secret-value"]
    assert read_dotenv_values(tmp_path / "missing") == []
