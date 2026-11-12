"""`readme`: seven READMEs, and every number in them comes from data.

Falsifying checks (phase brief):
  * the seven files exist, are tracked and are not empty; the root one has a heading containing
    "How this was built" and links the live site;
  * every figure sits inside a `<!-- gen:NAME -->` block (filled by scripts/build_readme.py from
    the data) or on a line marked `<!-- literal: reason -->`; fenced code and link targets are not
    scanned; the scan here is written independently of the gate's;
  * `build_readme.py --verify` is byte-exact; hand-editing a generated block makes it fail; and a
    perturbed data value in a temp copy changes the matching block (so no block is typed text);
  * the honesty notes the plan requires are present in the root README.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.phase6 import helpers as h

BUILD = h.ROOT / "scripts" / "build_readme.py"
GEN_OPEN = re.compile(r"<!--\s*gen:([\w.-]+)\s*-->")
GEN_CLOSE = re.compile(r"<!--\s*/gen:([\w.-]+)\s*-->")
LITERAL = re.compile(r"<!--\s*literal:\s*(.*?)\s*-->")


# ------------------------------------------------------------------ the figure scan


def figures(text: str) -> list[tuple[int, str, bool]]:
    """(line, figure, has_literal_marker) for every figure outside fences and generated blocks."""
    out, gen = [], None
    for i, line in enumerate(h.strip_fences(text).splitlines(), 1):
        if m := GEN_OPEN.search(line):
            gen = m.group(1)
        if gen:
            if (c := GEN_CLOSE.search(line)) and c.group(1) == gen:
                gen = None
            continue
        marker = LITERAL.search(line)
        body = re.sub(r"<!--.*?-->", " ", line)
        body = re.sub(r"\]\([^)]*\)|<https?://[^>]*>|https?://\S+", "]", body)
        body = re.sub(r"[A-Za-z]\w*(?:-\w+)*\d[\w-]*", " ", body)  # RSA-2048, ibm_kingston, k2
        out += [(i, f, bool(marker and marker.group(1))) for f in re.findall(r"\d[\d,.]*", body)]
    return out


def untraced(text: str) -> list[str]:
    return [f"line {i}: {f}" for i, f, marked in figures(text) if not marked]


def block_problems(text: str) -> list[str]:
    """Unbalanced, nested or duplicate generated-block markers."""
    problems, open_name, names = [], None, []
    for i, line in enumerate(text.splitlines(), 1):
        if m := GEN_OPEN.search(line):
            if open_name:
                problems.append(f"line {i}: block {m.group(1)} opens inside {open_name}")
            open_name = m.group(1)
            if open_name in names:
                problems.append(f"line {i}: block {open_name} appears twice")
            names.append(open_name)
        if c := GEN_CLOSE.search(line):
            if c.group(1) != open_name:
                problems.append(f"line {i}: closes {c.group(1)} but {open_name} is open")
            open_name = None
    if open_name:
        problems.append(f"block {open_name} never closes")
    return problems


# ------------------------------------------------------------------ structure


@pytest.mark.parametrize("rel", h.READMES)
def test_readme_each_file_exists_is_tracked_and_has_content(rel):
    tracked = set(
        subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=h.ROOT,
            capture_output=True,
            text=True,
        ).stdout.split("\n")
    )
    assert rel in tracked, f"{rel} is not tracked"
    text = (h.ROOT / rel).read_text()
    assert len(text.split()) > 60, f"{rel} is almost empty"
    assert re.match(r"# \S", text), f"{rel} must start with a title"


def test_readme_root_has_how_this_was_built_and_the_live_link():
    text = (h.ROOT / "README.md").read_text()
    heads = [ln for ln in text.splitlines() if ln.startswith("#")]
    assert any("how this was built" in ln.lower() for ln in heads), heads
    assert h.LIVE_URL in h.link_targets(text) or h.LIVE_URL + "/" in h.link_targets(text)


def test_readme_how_this_was_built_names_the_method_without_pointing_at_removed_files():
    text = (h.ROOT / "README.md").read_text()
    body = text.split("How this was built", 1)[1].lower()
    for need in ("phase", "three", "gate", "approv"):
        assert need in body, f"'How this was built' does not mention '{need}'"


def test_readme_markers_are_balanced_and_every_block_is_known():
    for rel in h.READMES:
        text = (h.ROOT / rel).read_text()
        assert block_problems(text) == [], rel
    spec = importlib.util.spec_from_file_location("br", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    used = {m for rel in h.READMES for m in GEN_OPEN.findall((h.ROOT / rel).read_text())}
    assert used and used <= set(mod.BLOCKS), used - set(mod.BLOCKS)
    assert set(mod.BLOCKS) <= used, f"block never used: {set(mod.BLOCKS) - used}"


# ------------------------------------------------------------------ figures


@pytest.mark.parametrize("rel", h.READMES)
def test_readme_every_figure_is_generated_or_marked_literal(rel):
    assert untraced((h.ROOT / rel).read_text()) == []


def test_readme_every_literal_marker_gives_a_reason():
    for rel in h.READMES:
        for i, line in enumerate((h.ROOT / rel).read_text().splitlines(), 1):
            if "literal" in line and "<!--" in line:
                m = LITERAL.search(line)
                assert m and len(m.group(1)) >= 6, f"{rel}:{i} literal marker without a reason"


def test_readme_the_root_readme_has_generated_blocks():
    assert len(GEN_OPEN.findall((h.ROOT / "README.md").read_text())) >= 4


def test_readme_defect_an_untyped_figure_in_prose_is_found():
    assert untraced("# T\nabout 42 qubits were used\n")
    assert untraced("# T\nruns 3.5 times faster, see [x](a/b3.md)\n")
    assert untraced("# T\n| a | 12% |\n")


def test_readme_defect_a_figure_in_a_generated_block_is_allowed_but_outside_is_not():
    inside = "# T\n<!-- gen:x -->\n42 qubits\n<!-- /gen:x -->\n"
    assert untraced(inside) == []
    assert untraced(inside + "and 7 more\n")
    assert untraced("# T\n<!-- gen:x -->\n42\n<!-- /gen:x -->\n8 here\n")


def test_readme_defect_a_literal_marker_needs_a_reason():
    assert untraced("# T\nPython 3.11 <!-- literal: Python version -->\n") == []
    assert untraced("# T\nPython 3.11 <!-- literal: -->\n")
    assert untraced("# T\nPython 3.11 <!-- not a literal marker -->\n")


def test_readme_identifiers_fences_and_link_targets_are_not_figures():
    ok = (
        "# T\nRSA-2048 and ECC-256 on ibm_kingston, k2, [x](a/b2.md), https://e.org/1\n"
        "```\nx = 99\n```\n"
    )
    assert untraced(ok) == []


def test_readme_defect_broken_block_markers_are_found():
    assert block_problems("<!-- gen:a -->\nx\n")
    assert block_problems("<!-- gen:a -->\n<!-- gen:b -->\n<!-- /gen:b -->\n<!-- /gen:a -->\n")
    assert block_problems("<!-- gen:a -->\n<!-- /gen:b -->\n")
    assert block_problems("<!-- gen:a -->\n<!-- /gen:a -->\n<!-- gen:a -->\n<!-- /gen:a -->\n")
    assert block_problems("<!-- gen:a -->\nx\n<!-- /gen:a -->\n") == []


# ------------------------------------------------------------------ build_readme.py


def run_build(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BUILD), "--root", str(root), *flags],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def copy(tmp_path) -> Path:
    """A temp repo skeleton: the READMEs and the web data, nothing else."""
    for rel in h.READMES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(h.ROOT / rel, tmp_path / rel)
    shutil.copytree(h.ROOT / "web" / "public" / "data", tmp_path / "web" / "public" / "data")
    return tmp_path


def test_readme_verify_is_byte_exact_on_the_real_repository():
    r = run_build(h.ROOT, "--verify")
    assert r.returncode == 0, r.stdout + r.stderr


def test_readme_verify_passes_on_the_unmodified_copy_and_rewrite_changes_nothing(copy):
    assert run_build(copy, "--verify").returncode == 0
    before = {rel: (copy / rel).read_bytes() for rel in h.READMES}
    assert run_build(copy).returncode == 0
    assert {rel: (copy / rel).read_bytes() for rel in h.READMES} == before


def test_readme_defect_a_hand_edited_generated_block_fails_verify(copy):
    f = copy / "README.md"
    text = f.read_text()
    name = GEN_OPEN.search(text).group(1)
    m = re.search(rf"(<!--\s*gen:{name}\s*-->\n)(.*?)(\n<!--\s*/gen:{name}\s*-->)", text, re.S)
    f.write_text(text[: m.start(2)] + m.group(2) + " (edited by hand)" + text[m.end(2) :])
    r = run_build(copy, "--verify")
    assert r.returncode == 1 and "differ" in r.stderr


def test_readme_defect_an_unknown_block_name_fails_verify(copy):
    f = copy / "README.md"
    f.write_text(f.read_text() + "\n<!-- gen:nonsense -->\nx\n<!-- /gen:nonsense -->\n")
    r = run_build(copy, "--verify")
    assert r.returncode == 1 and "nonsense" in r.stderr


# (block, data file, path into it, new value from the old one)
PERTURB = [
    ("device", "lab", ["device", "n_qubits"], lambda v: v + 1),
    (
        "lab-table",
        "lab",
        ["circuits", 0, "ideal", "success_probability"],
        lambda v: 0.5 if v != 0.5 else 0.25,
    ),
    ("crqc", "scenarios", ["timeline", "fit", "doubling_years"], lambda v: v * 1.5),
    ("gap", "scenarios", ["gaps", "median", "ecc256", "physical_qubits"], lambda v: v * 3),
    ("inventory", "inventory", ["summary", "median", "assets_total"], lambda v: v + 7),
    ("nist", "inventory", ["deadlines", 0, "year"], lambda v: v + 1),
]


def _block(text: str, name: str) -> str:
    m = re.search(rf"<!--\s*gen:{name}\s*-->\n(.*?)\n?<!--\s*/gen:{name}\s*-->", text, re.S)
    assert m, f"block {name} not found"
    return m.group(1)


def _set(data, path, fn):
    for k in path[:-1]:
        data = data[k]
    data[path[-1]] = fn(data[path[-1]])


@pytest.mark.parametrize("block,fname,path,fn", PERTURB, ids=[p[0] for p in PERTURB])
def test_readme_perturbing_a_data_value_changes_its_block(copy, block, fname, path, fn):
    """Output must follow the data: a typed block would not change."""
    used = {m for rel in h.READMES for m in GEN_OPEN.findall((copy / rel).read_text())}
    assert block in used
    f = copy / "web" / "public" / "data" / f"{fname}.json"
    data = json.loads(f.read_text())
    _set(data, path, fn)
    f.write_text(json.dumps(data))
    # the stale README no longer verifies ...
    assert run_build(copy, "--verify").returncode == 1
    # ... and a rewrite changes exactly the block that reads this value
    old = {rel: (copy / rel).read_text() for rel in h.READMES}
    assert run_build(copy).returncode == 0
    new = {rel: (copy / rel).read_text() for rel in h.READMES}
    changed = [rel for rel in h.READMES if new[rel] != old[rel]]
    assert changed, f"perturbing {fname}:{path} changed no README"
    assert any(
        _block(old[rel], block) != _block(new[rel], block) for rel in changed if block in old[rel]
    )
    # and the rewritten README verifies again
    assert run_build(copy, "--verify").returncode == 0


# ------------------------------------------------------------------ honesty notes

NOTES = {
    "shor success means the order": r"shor.{0,20}success.{0,60}order.{0,60}not.{0,40}factored",
    "textbook circuit is compiled": r"textbook shor circuit.{0,40}`?compiled`?",
    "compiled is not evidence": r"not evidence",
    "hardware generic shor is a null check": r"null check",
    "noisy simulator overestimated hardware": r"over-?estimated.{0,40}hardware",
    "grover is not an aes projection": r"not an aes projection",
    "break years are trend extrapolations": r"trend extrapolation",
    "held-out error shown": r"held-out",
    "pessimistic differs only in cycle time": r"pessimistic.{0,80}only in.{0,40}cycle time",
    "ecc-first rests on upper bounds": r"ecc-first.{0,80}upper bounds",
    "off-family designs claim fewer qubits": r"qldpc.{0,80}fewer qubits",
    "nist deadlines beside the final year": r"nist ir.{0,200}(deadline|disallow)",
    "not measured: screen reader": r"screen-reader",
    "not measured: other browsers": r"browser other than chromium",
    "ssl labs is a, not a+": r"ssl labs.{0,40}\ba\b,? not a\+",
}


def notes_missing(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text.lower())
    return [k for k, rx in NOTES.items() if not re.search(rx, flat)]


def test_readme_root_states_every_honesty_note():
    assert notes_missing((h.ROOT / "README.md").read_text()) == []


def test_readme_nist_dates_are_shown_beside_the_final_year():
    text = (h.ROOT / "README.md").read_text()
    block = _block(text, "nist")
    for year in ("2030", "2031", "2035"):
        assert year in block, f"{year} missing from the generated NIST list"


@pytest.mark.parametrize("note", list(NOTES))
def test_readme_defect_removing_a_note_is_noticed(note):
    text = (h.ROOT / "README.md").read_text()
    flat = re.sub(r"\s+", " ", text)
    m = re.search(NOTES[note], flat, re.I)
    assert m, f"{note}: pattern does not match the real README"
    assert note in notes_missing(re.sub(NOTES[note], " ", flat, flags=re.I))
