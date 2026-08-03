#!/usr/bin/env python3
"""Fold review_clips.py's answers back into the per-speaker meta.json files.

review_clips.py records what you heard into data/clip_labels.json and stops
there. Nothing carries that verdict into meta.json, so the phrase field stays
at "pending_listen" forever and the by-ear pass silently does not count -- the
exact drift review_clips.py exists to prevent, one step further along.

This closes that loop. Reads the labels, sets phrase_verified per speaker, and
refuses to claim a verdict it does not have: a speaker whose clips are only
partly labelled stays pending, and is reported as such.

Matching is on (speaker directory, filename), not full path, so it does not
matter which working directory review_clips.py was run from.

    python review_clips.py data/positives --device 4     # 1. listen
    python apply_clip_labels.py                          # 2. fold in
    python build_validation_set.py                       # 3. rebuild manifest
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_labels(path: Path) -> dict:
    """-> {(speaker_dir, filename): "yes"|"no"}. Keyed on the last two path
    components so a labels file written from any cwd still matches."""
    raw = json.loads(path.read_text()).get("labels", {})
    out = {}
    for p, verdict in raw.items():
        parts = Path(p).parts
        if len(parts) < 2:
            continue
        out[(parts[-2], parts[-1])] = verdict
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default="data/clip_labels.json")
    ap.add_argument("--positives", default="data/positives")
    ap.add_argument("--negatives", default="data/negatives")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change, write nothing")
    args = ap.parse_args()

    lpath = Path(args.labels)
    if not lpath.exists():
        print(f"no labels at {lpath}; run review_clips.py first", file=sys.stderr)
        return 1
    labels = load_labels(lpath)
    if not labels:
        print(f"{lpath} contains no labels", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).isoformat()
    changed = 0

    print(f"{'speaker':10} {'clips':>6} {'yes':>5} {'no':>4} {'unlabelled':>11}  verdict")
    print("-" * 62)

    for meta_path in sorted(Path(args.positives).glob("*/meta.json")):
        speaker_dir = meta_path.parent
        wavs = sorted(speaker_dir.glob("*.wav"))
        if not wavs:
            continue

        verdicts = [labels.get((speaker_dir.name, w.name)) for w in wavs]
        yes = sum(1 for v in verdicts if v == "yes")
        no = sum(1 for v in verdicts if v == "no")
        unlabelled = sum(1 for v in verdicts if v is None)

        # Only a complete pass earns a verdict. A partial one is not evidence.
        if unlabelled:
            verdict = None
        elif no == 0:
            verdict = "yes"
        elif yes == 0:
            verdict = "no"
        else:
            verdict = "mixed"

        shown = verdict or f"pending ({unlabelled} unheard)"
        print(f"{speaker_dir.name:10} {len(wavs):>6} {yes:>5} {no:>4} "
              f"{unlabelled:>11}  {shown}")

        if verdict is None:
            continue

        meta = json.loads(meta_path.read_text())
        if meta.get("phrase_verified") == verdict:
            continue
        meta["phrase_verified"] = verdict
        meta["phrase_verified_utc"] = now
        exceptions = [w.name for w, v in zip(wavs, verdicts) if v == "no"]
        if exceptions:
            meta["phrase_verified_exceptions"] = exceptions
        else:
            meta.pop("phrase_verified_exceptions", None)

        if not args.dry_run:
            meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        changed += 1

    print()
    verb = "would update" if args.dry_run else "updated"
    print(f"{verb} {changed} meta.json file(s)")

    # Negatives have no meta.json, but a "yes" there is the more serious finding:
    # the clip says the wake phrase and is filed as something the model must not
    # fire on. Report it; moving files is a judgement call, not an automation.
    negdir = Path(args.negatives)
    if negdir.is_dir():
        mis = sorted(n for (d, n), v in labels.items()
                     if d == negdir.name and v == "yes")
        if mis:
            print()
            print(f"!! {len(mis)} NEGATIVE(S) SAY THE WAKE PHRASE:")
            for n in mis:
                print(f"     {n}")
            print("   These invert the false-accept rate -- a correct detection on")
            print("   them scores as an error. Move them into a positives/ speaker")
            print("   directory (or delete them), then re-run build_validation_set.py.")

    if not args.dry_run and changed:
        print("\nNext: python build_validation_set.py   # refresh the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
