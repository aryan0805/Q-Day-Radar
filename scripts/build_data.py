"""Build web/public/data/*.json and schema/*.schema.json from the result files.

  uv run python scripts/build_data.py            # write into web/public/data/
  uv run python scripts/build_data.py --verify   # rebuild into a temp dir, compare bytes

--verify ignores meta.json's generated_at and git_commit (the commit changes when the data is
committed); every other byte, including every source sha256, must match.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantum.risk import webdata  # noqa: E402

DATA_DIR = webdata.ROOT / "web" / "public" / "data"
VOLATILE = {"generated_at", "git_commit"}


def write(out: Path) -> list[Path]:
    (out / "schema").mkdir(parents=True, exist_ok=True)
    written = []
    for name, obj in webdata.build_all().items():
        p = out / f"{name}.json"
        p.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
        written.append(p)
    for name, sch in webdata.schemas().items():
        p = out / "schema" / f"{name}.schema.json"
        p.write_text(json.dumps(sch, indent=2, sort_keys=True) + "\n")
        written.append(p)
    return written


def _normalized(path: Path) -> str:
    text = path.read_text()
    if path.name == "meta.json":
        obj = json.loads(text)
        for k in VOLATILE:
            obj.pop(k, None)
        return json.dumps(obj, indent=2, sort_keys=True)
    return text


def verify() -> int:
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        fresh = write(Path(tmp))
        for p in fresh:
            rel = p.relative_to(tmp)
            existing = DATA_DIR / rel
            if not existing.exists():
                print(f"MISSING {existing}")
                ok = False
            elif _normalized(existing) != _normalized(p):
                print(f"CHANGED {existing}")
                ok = False
    print("verify:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)
    if args.verify:
        return verify()
    for p in write(DATA_DIR):
        print(f"wrote {p.relative_to(webdata.ROOT)} ({p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
