#!/usr/bin/env python3
"""Live wake word detection monitor."""

# MUST precede numpy. numpy loads Intel MKL, whose Fortran runtime hijacks
# Ctrl-C and aborts the process before Python can clean up.
import os
os.environ["FOR_DISABLE_CONSOLE_CTRL_HANDLER"] = "1"

import argparse
import sys
import time
import warnings
from collections import deque
from datetime import datetime

import numpy as np

warnings.filterwarnings("ignore")

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1280
PRETRAINED_DEFAULT = "hey_jarvis_v0.1"


def build_model(model_ref: str):
    import openwakeword
    from openwakeword.model import Model

    if model_ref.endswith(".onnx"):
        return Model(wakeword_models=[model_ref], inference_framework="onnx")

    openwakeword.utils.download_models(model_names=[model_ref])
    return Model(wakeword_models=[model_ref], inference_framework="onnx")


def meter(score: float, width: int = 32) -> str:
    filled = int(min(max(score, 0.0), 1.0) * width)
    return "#" * filled + "." * (width - filled)


def main() -> int:
    ap = argparse.ArgumentParser(description="Live wake word detection monitor.")
    ap.add_argument("--model", default=PRETRAINED_DEFAULT)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--cooldown", type=float, default=2.0)
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    import sounddevice as sd

    if args.list_devices:
        print(sd.query_devices())
        print("\nPick the index of your microphone and pass it with --device")
        return 0

    print(f"Loading model: {args.model}")
    model = build_model(args.model)
    print(f"Loaded: {', '.join(model.models.keys())}")

    if args.device is not None:
        sd.default.device = (args.device, None)
    dev_name = sd.query_devices(sd.default.device[0])["name"]
    print(f"Input device: {dev_name}")
    print(f"Threshold: {args.threshold}   Cooldown: {args.cooldown}s")
    print()
    if args.model == PRETRAINED_DEFAULT:
        print('Say "hey jarvis". Scores should spike well above the threshold.')
        print("Ordinary conversation should stay near zero.")
    print("Ctrl-C to stop and print a summary.")
    print()

    detections = []
    recent = deque(maxlen=12)
    last_fire = 0.0
    started = time.time()

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            blocksize=FRAME_SAMPLES) as stream:
            while True:
                frame, overflowed = stream.read(FRAME_SAMPLES)
                if overflowed:
                    print("  (audio buffer overflow - machine may be too loaded)")

                scores = model.predict(frame.flatten())
                top = max(scores.values())
                recent.append(top)

                now = time.time()
                if top >= args.threshold and (now - last_fire) >= args.cooldown:
                    last_fire = now
                    detections.append(now)
                    stamp = datetime.now().strftime("%H:%M:%S")
                    print(f"\r  [{stamp}] DETECTED  score={top:.3f}"
                          f"   (total {len(detections)})")

                if not args.quiet:
                    peak = max(recent)
                    print(f"\r  {meter(peak)}  {peak:.3f} ", end="", flush=True)

    except KeyboardInterrupt:
        elapsed = time.time() - started
        print("\n")
        print("--- summary ---")
        print(f"runtime:     {elapsed/60:.1f} min")
        print(f"detections:  {len(detections)}")
        if elapsed > 0:
            print(f"rate:        {len(detections)/(elapsed/3600):.2f} per hour")
        return 0


if __name__ == "__main__":
    sys.exit(main())
