"""
W1.4 Step 2 — verify the corpus pin. Recomputes both hash levels from the
xlsx on disk and compares against the committed corpus_snapshot.json. Exits
NONZERO on ANY drift (changed/added/removed source file or doc row).

Run before every eval run / in CI:
    python scripts/verify_pin.py   # exit 0 = pinned corpus intact
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_corpus_snapshot import compute_snapshot, SNAPSHOT_PATH  # noqa: E402


def main() -> int:
    if not SNAPSHOT_PATH.exists():
        print(f"[verify_pin] FAIL: {SNAPSHOT_PATH.name} not found — corpus not pinned.")
        return 2
    pinned = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    current = compute_snapshot()

    problems: list[str] = []

    # 1. source-file digests
    pin_files = {f["filename"]: f for f in pinned["source_files"]}
    cur_files = {f["filename"]: f for f in current["source_files"]}
    for name in sorted(set(pin_files) | set(cur_files)):
        if name not in pin_files:
            problems.append(f"source file ADDED: {name}")
        elif name not in cur_files:
            problems.append(f"source file REMOVED: {name}")
        else:
            for k in ("sha256", "bytes", "row_count", "sheet"):
                if pin_files[name][k] != cur_files[name][k]:
                    problems.append(
                        f"{name}: {k} drift {pin_files[name][k]!r} -> {cur_files[name][k]!r}")

    # 2. per-doc row hashes
    pin_docs, cur_docs = pinned["docs"], current["docs"]
    missing = sorted(set(pin_docs) - set(cur_docs))
    added = sorted(set(cur_docs) - set(pin_docs))
    changed = sorted(d for d in (set(pin_docs) & set(cur_docs))
                     if pin_docs[d] != cur_docs[d])
    if missing:
        problems.append(f"{len(missing)} doc(s) REMOVED: {missing[:10]}")
    if added:
        problems.append(f"{len(added)} doc(s) ADDED: {added[:10]}")
    if changed:
        problems.append(f"{len(changed)} doc(s) CONTENT-CHANGED: {changed[:10]}")

    if problems:
        print("[verify_pin] FAIL — corpus drifted from the pin:")
        for p in problems:
            print("   -", p)
        return 1
    print(f"[verify_pin] PASS — {len(cur_docs)} docs across "
          f"{len(cur_files)} source files match corpus_snapshot.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
