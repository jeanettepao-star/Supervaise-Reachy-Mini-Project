#!/usr/bin/env python3
"""Move ear-confirmed candidate clips into the positives set.

segment_takes.py stages new clips outside data/positives/ because that set is
ear-verified and one unheard clip makes the whole set unverified. This is the
other half: it promotes only clips review_clips.py labelled "yes", and updates
the speaker's meta.json in the same step so counts, durations and next_index
cannot drift from what is on disk.

Clips labelled "no" stay in the staging directory. Unlabelled clips stay too --
an unheard clip is not a rejected one, and silently promoting it would defeat
the point of staging.

    python review_clips.py data/candidates/pao --device 4
    python promote_candidates.py
    python build_validation_set.py
"""

import argparse
import json
import shutil
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path


def duration_s(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", default="data/candidates")
    ap.add_argument("--positives", default="data/positives")
    ap.add_argument("--labels", default="data/clip_labels.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lpath = Path(args.labels)
    if not lpath.exists():
        print(f"no labels at {lpath}; run review_clips.py first", file=sys.stderr)
        return 1
    # Key on filename only: a clip keeps its name across the move, so one label
    # stays valid whether the clip is still staged or already promoted.
    heard = {Path(p).name: v
             for p, v in json.loads(lpath.read_text()).get("labels", {}).items()}

    croot = Path(args.candidates)
    if not croot.is_dir():
        print(f"no candidates directory at {croot}", file=sys.stderr)
        return 1

    total_moved = 0
    for cdir in sorted(p for p in croot.iterdir() if p.is_dir()):
        speaker = cdir.name
        wavs = sorted(cdir.glob("*.wav"))
        if not wavs:
            continue

        promote = [w for w in wavs if heard.get(w.name) == "yes"]
        rejected = [w for w in wavs if heard.get(w.name) == "no"]
        unheard = [w for w in wavs if w.name not in heard]

        print(f"{speaker}: {len(promote)} promote, {len(rejected)} rejected, "
              f"{len(unheard)} unheard")
        for w in unheard:
            print(f"    unheard, staying put: {w.name}")
        if not promote:
            continue

        dest = Path(args.positives) / speaker
        meta_path = dest / "meta.json"
        if not meta_path.exists():
            print(f"    no meta.json at {meta_path}; skipping", file=sys.stderr)
            continue
        meta = json.loads(meta_path.read_text())

        collisions = [w.name for w in promote if (dest / w.name).exists()]
        if collisions:
            print(f"    REFUSING: {', '.join(collisions)} already exist in "
                  f"{dest}. Renumber before promoting -- overwriting a verified "
                  f"clip is not recoverable.", file=sys.stderr)
            continue

        durations = dict(meta.get("clip_durations_s", {}))
        for w in promote:
            durations[w.name] = round(duration_s(w), 2)
            if not args.dry_run:
                shutil.move(str(w), str(dest / w.name))
            print(f"    {w.name}")

        if not args.dry_run:
            on_disk = sorted(dest.glob("*.wav"))
            idx = [int(p.stem.rsplit("_", 1)[1]) for p in on_disk
                   if p.stem.rsplit("_", 1)[1].isdigit()]
            meta["clips"] = len(on_disk)
            meta["clip_durations_s"] = {k: durations[k] for k in sorted(durations)
                                        if (dest / k).exists()}
            meta["next_index"] = (max(idx) + 1) if idx else 0
            meta.setdefault("promotions", []).append({
                "utc": datetime.now(timezone.utc).isoformat(),
                "clips": [w.name for w in promote],
                "from": cdir.as_posix(),
                "basis": "review_clips.py label 'yes' (heard, one clip at a time)",
            })
            meta_path.write_text(json.dumps(meta, indent=2) + "\n")

        total_moved += len(promote)

        if not args.dry_run and not list(cdir.glob("*.wav")):
            shutil.rmtree(cdir)
            print(f"    staging dir emptied and removed")

    if args.dry_run:
        print(f"\ndry run -- nothing moved ({total_moved} would move)")
    else:
        print(f"\npromoted {total_moved} clip(s)")
        if total_moved:
            print("Next: python apply_clip_labels.py && python build_validation_set.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
