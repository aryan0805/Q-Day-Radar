"""AUDIT.md section 3 must say what the data says about the family order (P5 correction).

The heading once claimed "The family order depends on the Google bound" next to a table showing the
order unchanged without paper feeds. The sentence is now generated, and this test ties it to the
data in both directions, so a stale or hand-edited claim fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "tests" / "phase4" / "AUDIT.md"
DATA = ROOT / "web" / "public" / "data"

SAME = "The family order does not depend on the paper feeds."
DIFFERENT = "The family order depends on the paper feeds"


def _orders_equal() -> bool:
    inv = json.loads((DATA / "inventory.json").read_text())
    model_only = json.loads((DATA / "scenarios.json").read_text())["model_only"]
    assert set(model_only) == set(inv["family_order"]) and model_only
    return all(model_only[s]["family_order"] == inv["family_order"][s] for s in model_only)


def _section3() -> str:
    text = AUDIT.read_text(encoding="utf-8")
    m = re.search(r"\n## 3\..*?(?=\n## 4\.)", text, re.S)
    assert m, "AUDIT.md has no section 3 before section 4"
    return m.group(0)


def test_audit_order_claim_matches_the_data() -> None:
    sec = _section3()
    says_same, says_different = SAME in sec, DIFFERENT in sec
    assert says_same != says_different, "section 3 must make exactly one claim about the order"
    assert says_same == _orders_equal(), (
        f"AUDIT.md claims the order {'is' if says_same else 'is not'} independent of the feeds, "
        f"but the data says {'it is' if _orders_equal() else 'it is not'}"
    )


def test_audit_never_says_the_order_depends_on_the_google_bound() -> None:
    # the retired claim: the order rests on Google's logical counts, not on its physical figure
    assert "depends on the Google bound" not in AUDIT.read_text(encoding="utf-8")


def test_audit_table_and_claim_use_the_same_comparison() -> None:
    sec = _section3()
    rows = re.findall(r"^\| (optimistic|median|pessimistic) \| (.+?) \| (.+?) \|$", sec, re.M)
    assert {r[0] for r in rows} == {"optimistic", "median", "pessimistic"}
    table_equal = all(r[1].strip() == r[2].strip() for r in rows)
    assert table_equal == (SAME in sec)
