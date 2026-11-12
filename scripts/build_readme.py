"""Fill the generated blocks of the READMEs from the result files and the web data.

A README holds a figure only in one of two places:

* between ``<!-- gen:NAME -->`` and ``<!-- /gen:NAME -->``: this script writes that text from
  ``web/public/data/*.json`` (which ``build_data.py`` builds from ``results/``);
* on a line that ends ``<!-- literal: reason -->`` (a version, a phase number, an RFC number).

    uv run python scripts/build_readme.py            # rewrite every generated block
    uv run python scripts/build_readme.py --verify   # exit 1 if any block differs from the data

Blocks are plain Markdown. Nothing is typed by hand: change a data file and the block changes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "public" / "data"
READMES = [
    "README.md", "quantum/README.md", "web/README.md", "tests/README.md",
    "results/README.md", "scripts/README.md", "benchmarks/README.md",
]
SCENARIOS = ("optimistic", "median", "pessimistic")


def load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text())


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def year(x: float | None) -> str:
    return "none inside the runtime cap" if x is None else f"{x:.1f}"


def big(x: float) -> str:
    return f"{x:,.0f}"


def table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


# --- blocks -------------------------------------------------------------------------------


def block_device() -> str:
    lab = load("lab")
    d, s = lab["device"], lab["hardware_summary"]
    return (f"Hardware runs used **{d['name']}** ({d['n_qubits']} qubits). "
            f"{s['ran']} circuits ran on it: {s['above']} came out above random guessing, "
            f"{s['no_better']} were no better than random guessing.")


def block_lab_table() -> str:
    rows = []
    for c in load("lab")["circuits"]:
        h = c.get("hardware_headline")
        rows.append([
            f"`{c['name']}`", c["kind"], pct(c["ideal"]["success_probability"]),
            pct(c["noisy"]["success_probability"]),
            pct(h["success_probability"]) if h else "not run",
            pct(h["chance_baseline"]) if h else pct(c["noisy"]["chance_baseline"]),
            h["verdict"] if h else "not run on hardware",
        ])
    return table(["circuit", "kind", "ideal simulator", "noisy simulator", "hardware (raw run)",
                  "random guessing", "hardware vs random guessing"], rows)


def block_crqc() -> str:
    sc = load("scenarios")
    t = sc["timeline"]
    rows = []
    for name in SCENARIOS:
        tg = t["scenarios"][name]["targets"]
        rows.append([name, year(tg["ecc256"]["crqc_year"]), year(tg["rsa2048"]["crqc_year"])])
    h = t["fit"]["holdout"]
    head = (f"Doubling time of the largest machine built each year: "
            f"{t['fit']['doubling_years']:.2f} years. "
            f"Held-out check: the fit predicted {big(h['predicted'])} qubits for {h['year']}, "
            f"the real figure was {big(h['actual'])} "
            f"(error {pct(h['rel_error'])}).\n\n")
    return head + table(["scenario", "ECC-256 reachable (year)", "RSA-2048 reachable (year)"], rows)


def block_gap() -> str:
    g = load("scenarios")["gaps"]["median"]
    dev = load("lab")["device"]
    rows = [[k.upper().replace("ECC256", "ECC-256").replace("RSA2048", "RSA-2048"),
             big(v["physical_qubits"]), f"{v['over_device']:,.0f}×",
             f"{v['over_record']:,.0f}×"] for k, v in (("ecc256", g["ecc256"]),
                                                       ("rsa2048", g["rsa2048"]))]
    base = load("scenarios")["timeline"]["baseline"]
    return table(["target", "physical qubits needed (published estimate)",
                  f"times {dev['name']} ({dev['n_qubits']} qubits)",
                  f"times the record chip ({big(base['qubits'])} qubits, {base['year']})"], rows)


def block_inventory() -> str:
    inv = load("inventory")
    s = inv["summary"]["median"]
    top = sorted(inv["assets"], key=lambda a: a["by_scenario"]["median"]["rank"])[:5]
    rows = [[str(a["by_scenario"]["median"]["rank"]), a["name"], a["algorithm"],
             f"{a['by_scenario']['median']['margin_years']:+.1f}"] for a in top]
    head = (f"The demo inventory has {s['assets_total']} assets. In the median scenario "
            f"{s['exposed']} are already exposed (their Mosca margin is negative) and "
            f"{s['classically_deprecated']} are classically deprecated. "
            f"Soonest break: {s['soonest_crqc_year']:.1f}.\n\n")
    return head + table(["rank", "asset", "algorithm", "Mosca margin (years)"], rows)


def block_nist() -> str:
    rows = [f"- {d['year']}: {d['scope']}" for d in load("inventory")["deadlines"]]
    return "\n".join(rows)


BLOCKS: dict[str, Callable[[], str]] = {
    "device": block_device,
    "lab-table": block_lab_table,
    "crqc": block_crqc,
    "gap": block_gap,
    "inventory": block_inventory,
    "nist": block_nist,
}

PATTERN = re.compile(r"(<!--\s*gen:([\w.-]+)\s*-->\n)(.*?)(\n?<!--\s*/gen:\2\s*-->)", re.S)


def render(text: str) -> tuple[str, list[str]]:
    """Text with every generated block refilled, and the names of unknown blocks."""
    unknown: list[str] = []

    def fill(m: re.Match) -> str:
        name = m.group(2)
        if name not in BLOCKS:
            unknown.append(name)
            return m.group(0)
        return f"{m.group(1)}{BLOCKS[name]()}\n{m.group(4).lstrip(chr(10))}"

    return PATTERN.sub(fill, text), unknown


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--verify", action="store_true", help="exit 1 if a block differs from the data")
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (for tests)")
    args = ap.parse_args(argv)
    global DATA
    DATA = args.root / "web" / "public" / "data"
    bad = 0
    n_blocks = 0
    for rel in READMES:
        f = args.root / rel
        if not f.exists():
            continue
        text = f.read_text()
        new, unknown = render(text)
        n_blocks += len(PATTERN.findall(text))
        for u in unknown:
            print(f"{rel}: unknown block '{u}'", file=sys.stderr)
            bad += 1
        if new != text:
            if args.verify:
                print(f"{rel}: generated blocks differ from the data", file=sys.stderr)
                bad += 1
            else:
                f.write_text(new)
                print(f"updated {rel}")
    if args.verify:
        print("verify: OK" if not bad else f"verify: {bad} problems", file=sys.stderr if bad
              else sys.stdout)
    else:
        print(f"{n_blocks} blocks filled")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
