#!/usr/bin/env python3
"""Play recorded clips and label what was actually said.

Metadata drifts from audio silently. A meta.json phrase field is only as good
as somebody's memory of the session, and nothing downstream can detect that it
is wrong -- training just quietly optimises for the wrong target.

This plays each clip with its measured stats and records your answer, so the
phrase field can be set from what is on disk rather than what was intended.
"""

# MUST precede numpy. numpy loads Intel MKL, whose Fortran runtime hijacks
# Ctrl-C and aborts the process before Python can clean up.
import os
os.environ["FOR_DISABLE_CONSOLE_CTRL_HANDLER"] = "1"

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

FRAME_MS = 20


def speech_span(audio: np.ndarray, sr: int):
    """Energy-gated speech extent, matching check_clips.py."""
    f = int(sr * FRAME_MS / 1000)
    n = len(audio) // f
    if n == 0:
        return 0.0, 0.0
    rms = np.sqrt(np.mean(audio[: n * f].reshape(n, f) ** 2, axis=1))
    noise, peak = np.percentile(rms, 20), rms.max()
    if peak <= noise * 1.5:
        return 0.0, 0.0
    active = np.where(rms > noise + 0.15 * (peak - noise))[0]
    if not active.size:
        return 0.0, 0.0
    return active[0] * FRAME_MS / 1000, (active[-1] + 1) * FRAME_MS / 1000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", nargs="?", default="data/positives",
                    help="directory of .wav files, searched recursively")
    ap.add_argument("--out", default="data/clip_labels.json")
    ap.add_argument("--question",
                    default='Does this clip say "Cee-Jap" (/si: dzaep/, one word)? '
                            'Answer n if it spells out the letters "see jay ay pee".')
    ap.add_argument("--device", type=int, default=None)
    args = ap.parse_args()

    if args.device is not None:
        sd.default.device = (None, args.device)

    root = Path(args.directory)
    files = sorted(root.rglob("*.wav"))
    if not files:
        print(f"no .wav files under {root}", file=sys.stderr)
        return 1

    out = Path(args.out)
    labels = {}
    if out.exists():
        labels = json.loads(out.read_text()).get("labels", {})
        if labels:
            print(f"Resuming: {len(labels)} clip(s) already labelled.\n")

    print(args.question)
    print()
    print("  y = yes      n = no, something else     ")
    print("  r = replay   s = skip                   q = save and quit")
    print()

    todo = [f for f in files if f.as_posix() not in labels]
    if not todo:
        print("Everything is already labelled. Delete the out file to redo.")
        return 0

    for i, path in enumerate(todo, 1):
        audio, sr = sf.read(path, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        start, end = speech_span(audio, sr)
        peak = float(np.max(np.abs(audio)))

        print(f"--- {i} of {len(todo)}: {path.name} ---")
        print(f"  {len(audio)/sr:.2f}s clip, speech {end - start:.2f}s "
              f"({start:.2f}-{end:.2f}s), peak {peak:.3f}")

        while True:
            sd.play(audio, sr)
            sd.wait()
            choice = input("  y / n / r / s / q > ").strip().lower()
            if choice == "r":
                continue
            if choice in ("y", "n", "s", "q"):
                break
            print("  (y, n, r, s or q)")

        if choice == "q":
            print("\nStopped.")
            break
        if choice == "s":
            print("  skipped\n")
            continue
        labels[path.as_posix()] = "yes" if choice == "y" else "no"
        print(f"  recorded: {labels[path.as_posix()]}\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "question": args.question,
        "labelled_utc": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "yes": sum(1 for v in labels.values() if v == "yes"),
            "no": sum(1 for v in labels.values() if v == "no"),
        },
        "labels": labels,
    }, indent=2) + "\n")

    yes = sum(1 for v in labels.values() if v == "yes")
    no = sum(1 for v in labels.values() if v == "no")
    print("--- summary ---")
    print(f"  yes:       {yes}")
    print(f"  no:        {no}")
    print(f"  unlabelled: {len(files) - len(labels)}")
    print(f"\nwrote {out}")
    if no:
        print(f"\n{no} clip(s) do not match. Those are not usable as positives "
              f"for this phrase -- they are either negatives or need re-recording.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
