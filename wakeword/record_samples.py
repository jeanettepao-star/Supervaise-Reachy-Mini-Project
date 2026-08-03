#!/usr/bin/env python3
"""
Collect real voice recordings for wake word training.

openWakeWord expects 16 kHz mono. This enforces that and gives immediate level
feedback so bad takes are caught at record time, not during training.

Examples
--------
    python record_samples.py --list-devices
    python record_samples.py --device 1 --speaker dev0
    python record_samples.py --device 1 --speaker maria --count 20

    # confusable phrases for EVALUATION ONLY -- never train on these
    python record_samples.py --device 1 --speaker dev0 --count 10 \
        --outdir data/eval_hard --phrase "Chief Justice"

Speaker diversity beats raw count. Twenty clips each from five people is
worth far more than a hundred from one.
"""

# MUST precede numpy. numpy loads Intel MKL, whose Fortran runtime hijacks
# Ctrl-C and aborts the process before Python can clean up.
import os
os.environ["FOR_DISABLE_CONSOLE_CTRL_HANDLER"] = "1"

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

SAMPLE_RATE = 16_000
CHANNELS = 1
CLIP_SECONDS = 3.5          # onset lag runs ~1.2s; 2.5 truncated the tail

QUIET_PEAK = 0.08           # calibrated to real speech at 0.145-0.412
LOUD_PEAK = 0.98            # above this the mic is clipping


def record_clip(seconds: float) -> np.ndarray:
    frames = int(seconds * SAMPLE_RATE)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS,
                   dtype="float32")
    sd.wait()
    return audio.reshape(-1)


def describe_level(audio: np.ndarray):
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio ** 2)))
    bars = int(min(peak, 1.0) * 40)
    meter = "#" * bars + "." * (40 - bars)

    if peak < QUIET_PEAK:
        return f"[{meter}] peak {peak:.3f} rms {rms:.3f}  TOO QUIET", False
    if peak > LOUD_PEAK:
        return f"[{meter}] peak {peak:.3f} rms {rms:.3f}  CLIPPING", False
    return f"[{meter}] peak {peak:.3f} rms {rms:.3f}  ok", True


def tone(freq: float, ms: int, amp: float = 0.25) -> np.ndarray:
    """Short click-free beep. Audible cues beat visual ones for timing."""
    t = np.arange(int(SAMPLE_RATE * ms / 1000)) / SAMPLE_RATE
    env = np.minimum(1, np.minimum(t * 200, (t[-1] - t) * 200))
    return (amp * env * np.sin(2 * np.pi * freq * t)).astype("float32")


def countdown(n: int = 3) -> None:
    for i in range(n, 0, -1):
        print(f"  {i}...        ", end="\r", flush=True)
        sd.play(tone(660, 120), SAMPLE_RATE)
        sd.wait()
        time.sleep(0.45)
    print("  >>> SPEAK NOW <<<", end="\r", flush=True)
    sd.play(tone(990, 160), SAMPLE_RATE)
    sd.wait()


def main() -> int:
    ap = argparse.ArgumentParser(description="Record wake word training samples.")
    ap.add_argument("--speaker", help="short speaker id, e.g. 'maria'")
    ap.add_argument("--count", type=int, default=20)
    # One two-syllable word, /si: dzaep/ -- NOT spelled letters. The spelled
    # "see jay ay pee" form is retired per WW-5 (2026-07-27): spoken "C-J" must
    # leave the detector silent. Canonical source is config.py section 12.
    ap.add_argument("--phrase", default="Hey Cee-Jap")
    ap.add_argument("--outdir", default="data/positives")
    ap.add_argument("--seconds", type=float, default=CLIP_SECONDS)
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        print("\nPick your microphone index and pass it with --device")
        return 0

    if not args.speaker:
        ap.error("--speaker is required (e.g. --speaker dev0)")

    if args.device is not None:
        sd.default.device = (args.device, None)

    outdir = Path(args.outdir) / args.speaker
    outdir.mkdir(parents=True, exist_ok=True)

    existing = sorted(outdir.glob(f"{args.speaker}_*.wav"))
    # Use max index + 1, never the count. Deleting clips creates gaps, and
    # counting would reuse indices and silently overwrite surviving files.
    used = set()
    for pth in existing:
        try:
            used.add(int(pth.stem.split("_")[-1]))
        except ValueError:
            pass
    start_index = (max(used) + 1) if used else 0
    if start_index:
        print(f"Found {start_index} existing clips for '{args.speaker}'. Appending.\n")

    print(f'Phrase:  "{args.phrase}"')
    print(f"Speaker: {args.speaker}")
    print(f"Target:  {args.count} clips, {SAMPLE_RATE} Hz mono, {args.seconds}s each")
    print(f"Saving:  {outdir}")
    print()
    print("Say it the way a museum visitor would -- naturally, not carefully.")
    print("Vary distance, pace and volume between takes. Do NOT over-enunciate;")
    print("the model must learn casual speech, not your best diction.")
    print()
    print("After each take:  ENTER = keep   r = redo   p = play back   q = quit")
    print()

    kept = 0
    while kept < args.count:
        n = start_index + kept
        print(f"--- clip {kept + 1} of {args.count} ---")
        countdown()
        audio = record_clip(args.seconds)
        report, usable = describe_level(audio)
        print(f"  {report}")

        if not usable:
            print("  auto-redo (bad level)\n")
            continue

        while True:
            choice = input("  [enter]=keep  r=redo  p=play  q=quit > ").strip().lower()
            if choice == "p":
                sd.play(audio, SAMPLE_RATE)
                sd.wait()
                continue
            break

        if choice == "q":
            print("\nStopped early.")
            break
        if choice == "r":
            print("  redoing\n")
            continue

        path = outdir / f"{args.speaker}_{n:03d}.wav"
        sf.write(path, audio, SAMPLE_RATE, subtype="PCM_16")
        kept += 1
        print(f"  saved {path.name}\n")

    total = len(list(outdir.glob(f"{args.speaker}_*.wav")))
    (outdir / "meta.json").write_text(json.dumps({
        "speaker": args.speaker,
        "phrase": args.phrase,
        "sample_rate": SAMPLE_RATE,
        "clip_seconds": args.seconds,
        "clips": total,
        "last_session_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2))

    print(f"Total clips for '{args.speaker}': {total}")
    print(f"Saved in: {outdir.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
