#!/usr/bin/env python3
"""
Quality-check recorded wake word clips before training.

Measures where speech actually sits inside each clip and flags problems that
silently degrade a trained model:

  TRUNCATED-START  speech begins within 100 ms of the clip start -- the front
                   of the phrase was probably cut off
  TRUNCATED-END    speech runs to within 100 ms of the clip end -- the tail
                   was probably cut off
  VERY-SHORT       under 400 ms of speech; likely a partial phrase
  QUIET            peak below 0.08; usable but weak for this mic

Usage:
    python check_clips.py data/positives/dev0
    python check_clips.py data/positives/dev0 --play-flagged
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

FRAME_MS = 20
EDGE_GUARD_MS = 100
MIN_SPEECH_MS = 400
QUIET_PEAK = 0.08


def speech_bounds(audio: np.ndarray, sr: int):
    """Energy-based speech onset/offset. Returns (start_s, end_s) or None."""
    frame = int(sr * FRAME_MS / 1000)
    n = len(audio) // frame
    if n == 0:
        return None
    frames = audio[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))

    noise_floor = np.percentile(rms, 20)
    peak_rms = rms.max()
    if peak_rms <= noise_floor * 1.5:
        return None

    thresh = noise_floor + 0.15 * (peak_rms - noise_floor)
    active = np.where(rms > thresh)[0]
    if len(active) == 0:
        return None
    return active[0] * FRAME_MS / 1000, (active[-1] + 1) * FRAME_MS / 1000


def main() -> int:
    ap = argparse.ArgumentParser(description="QC wake word clips.")
    ap.add_argument("directory")
    ap.add_argument("--play-flagged", action="store_true")
    args = ap.parse_args()

    d = Path(args.directory)
    files = sorted(d.glob("*.wav"))
    if not files:
        print(f"no .wav files in {d}")
        return 1

    print(f"{'file':<20} {'dur':>6} {'speech':>7} {'start':>6} {'end':>6} "
          f"{'peak':>6} flags")
    print("-" * 78)

    durations, flagged = [], []
    for f in files:
        audio, sr = sf.read(f, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        total = len(audio) / sr
        peak = float(np.max(np.abs(audio)))

        bounds = speech_bounds(audio, sr)
        flags = []
        if bounds is None:
            flags.append("NO-SPEECH")
            start = end = dur = 0.0
        else:
            start, end = bounds
            dur = end - start
            durations.append(dur)
            if start < EDGE_GUARD_MS / 1000:
                flags.append("TRUNCATED-START")
            if end > total - EDGE_GUARD_MS / 1000:
                flags.append("TRUNCATED-END")
            if dur < MIN_SPEECH_MS / 1000:
                flags.append("VERY-SHORT")
        if peak < QUIET_PEAK:
            flags.append("QUIET")

        if flags:
            flagged.append(f)
        print(f"{f.name:<20} {total:>5.2f}s {dur:>6.2f}s {start:>5.2f}s "
              f"{end:>5.2f}s {peak:>6.3f} {' '.join(flags)}")

    print()
    print("--- summary ---")
    print(f"clips:            {len(files)}")
    if durations:
        arr = np.array(durations)
        print(f"speech duration:  mean {arr.mean():.2f}s  "
              f"min {arr.min():.2f}s  max {arr.max():.2f}s")
        print(f"speech occupies:  {100 * arr.mean() / total:.0f}% of the clip")
    print(f"flagged:          {len(flagged)}")
    print()
    if not flagged:
        print("All clean. Good to use for training.")
    else:
        print("Flagged clips are not automatically bad -- listen before deleting.")
        print("Many TRUNCATED flags means increase --seconds when recording.")

    if args.play_flagged and flagged:
        import sounddevice as sd
        for f in flagged:
            print(f"playing {f.name} ...")
            audio, sr = sf.read(f, dtype="float32")
            sd.play(audio, sr)
            sd.wait()

    return 0


if __name__ == "__main__":
    sys.exit(main())
