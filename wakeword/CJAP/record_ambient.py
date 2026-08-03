#!/usr/bin/env python3
"""Record ambient audio as wake word negatives.

record_samples.py cannot do this. It auto-rejects anything below QUIET_PEAK and
re-records, and room tone is quiet by definition -- pointing it at an empty room
loops forever. It also beeps a countdown, which would land in every clip.

So this is the inverse tool: no countdown, no quality gate, no prompting. Start
it and leave the room. Chunks a continuous stream into fixed-length clips, so
there are no gaps between them and the recording adds up to a real elapsed
duration you can compute false-accepts-per-hour against.

The one check kept is a dead-mic guard. A quiet room and an unplugged microphone
both look like silence in a level meter, and the difference matters: one is the
data you wanted, the other is an hour wasted.
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
CLIP_SECONDS = 10.0         # long enough that per-clip overhead is negligible
BLOCK = 1600                # 100 ms; meter refresh rate, not a clip boundary

# -74 dBFS. Real rooms sit well above this even when they sound silent to a
# person; below it the input is almost certainly muted or disconnected.
SILENCE_FLOOR = 0.0002


def meter(peak: float, width: int = 32) -> str:
    bars = int(min(peak, 1.0) * width)
    return "#" * bars + "." * (width - bars)


def next_index(outdir: Path, prefix: str) -> int:
    """Max existing index + 1. Counting files would reuse indices after a
    deletion and silently overwrite the survivors."""
    used = set()
    for pth in outdir.glob(f"{prefix}_*.wav"):
        try:
            used.add(int(pth.stem.split("_")[-1]))
        except ValueError:
            pass
    return (max(used) + 1) if used else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Record ambient audio as wake word negatives.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", default="data/negatives/ambient")
    ap.add_argument("--prefix", default="ambient",
                    help="filename prefix; also the 'speaker' in the manifest")
    ap.add_argument("--seconds", type=float, default=CLIP_SECONDS,
                    help=f"length of each clip (default {CLIP_SECONDS})")
    ap.add_argument("--minutes", type=float, default=None,
                    help="stop after this long; omit to run until Ctrl-C")
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--label", default="",
                    help="free-text note stored in meta.json, e.g. 'gallery, HVAC on'")
    args = ap.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        print("\nPick your microphone index and pass it with --device")
        return 0

    if args.device is not None:
        sd.default.device = (args.device, None)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    start_index = next_index(outdir, args.prefix)

    clip_frames = int(args.seconds * SAMPLE_RATE)
    limit = args.minutes * 60 if args.minutes else None

    dev_name = sd.query_devices(sd.default.device[0])["name"]
    print(f"Device:  {dev_name}")
    print(f"Saving:  {outdir}  (next index {start_index:03d})")
    print(f"Clips:   {args.seconds:g}s each, {SAMPLE_RATE} Hz mono")
    print(f"Stop:    {'after ' + str(args.minutes) + ' min' if limit else 'Ctrl-C'}")
    print()
    print("Recording ambient audio. Do NOT say the wake phrase. Ordinary room")
    print("noise and unrelated conversation are exactly what this needs.")
    print()

    written, peaks, quiet_clips = [], [], 0
    buf = np.empty(0, dtype="float32")
    started = time.time()

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                            dtype="float32", blocksize=BLOCK) as stream:
            while True:
                block, overflowed = stream.read(BLOCK)
                if overflowed:
                    print("\r  (input overflow - dropped samples)")
                buf = np.concatenate([buf, block.reshape(-1)])

                elapsed = time.time() - started
                print(f"\r  {meter(float(np.max(np.abs(block))))}  "
                      f"{len(written)} clips  {elapsed/60:5.1f} min ",
                      end="", flush=True)

                while len(buf) >= clip_frames:
                    audio, buf = buf[:clip_frames], buf[clip_frames:]
                    peak = float(np.max(np.abs(audio)))
                    n = start_index + len(written)
                    path = outdir / f"{args.prefix}_{n:03d}.wav"
                    sf.write(path, audio, SAMPLE_RATE, subtype="PCM_16")
                    written.append(path)
                    peaks.append(peak)
                    if peak < SILENCE_FLOOR:
                        quiet_clips += 1
                        print(f"\r  {path.name}: peak {peak:.5f} - is the mic "
                              f"muted or unplugged?")

                if limit and (time.time() - started) >= limit:
                    break

    except KeyboardInterrupt:
        pass

    elapsed = time.time() - started
    # The tail is discarded rather than written short, so every clip is the
    # same length and total duration is exactly clips x seconds.
    dropped = len(buf) / SAMPLE_RATE

    print("\n")
    if not written:
        print(f"No clips written (need at least {args.seconds:g}s).")
        return 1

    total_s = len(written) * args.seconds
    meta = {
        "kind": "negative",
        "subtype": "ambient",
        "prefix": args.prefix,
        "label": args.label,
        "sample_rate": SAMPLE_RATE,
        "clip_seconds": args.seconds,
        "clips": len(list(outdir.glob(f"{args.prefix}_*.wav"))),
        "clips_this_session": len(written),
        "total_seconds_this_session": round(total_s, 1),
        "peak_min": round(min(peaks), 5),
        "peak_max": round(max(peaks), 5),
        "last_session_utc": datetime.now(timezone.utc).isoformat(),
        "note": ("Ambient audio, no wake phrase. Recorded continuously and "
                 "chunked, so clips x clip_seconds is real elapsed time -- use it "
                 "for a false-accepts-per-hour figure rather than a per-clip rate."),
    }
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    print("--- summary ---")
    print(f"clips written:  {len(written)}  ({total_s/60:.1f} min of audio)")
    print(f"peak range:     {min(peaks):.5f} - {max(peaks):.5f}")
    print(f"ran for:        {elapsed/60:.1f} min")
    if dropped > 0.05:
        print(f"discarded:      {dropped:.1f}s partial tail clip")
    print()

    if quiet_clips == len(written):
        print("EVERY clip is below the silence floor. The microphone is almost")
        print("certainly muted or disconnected -- this audio is unusable.")
        return 1
    if quiet_clips:
        print(f"{quiet_clips} of {len(written)} clips are near-silent. Check the "
              f"mic if that is unexpected.")

    print(f"Saved in: {outdir.resolve()}")
    print("Next:     python build_validation_set.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
