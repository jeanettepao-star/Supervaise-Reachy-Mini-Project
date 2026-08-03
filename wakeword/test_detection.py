#!/usr/bin/env python3
"""
Live wake word detection monitor.

Phase 0:  prove the mic -> detection chain with a pretrained model.
Phase 4:  point --model at your trained hey_cee_jap.onnx, run against gallery
          ambient, and read false-accepts-per-hour off the summary.

Examples
--------
    python test_detection.py --list-devices
    python test_detection.py --device 1
    python test_detection.py --device 1 --cooldown 3.0
    python test_detection.py --model models/hey_cee_jap.onnx --threshold 0.6

    # unattended one-hour ambient run, logged to CSV
    python test_detection.py --device 1 --model models/hey_cee_jap.onnx \
        --duration 3600 --log ambient_run1.csv --quiet
"""

# MUST precede numpy. numpy pulls in Intel MKL, whose Fortran runtime installs
# its own console handler and aborts the process on Ctrl-C before Python can
# raise KeyboardInterrupt. Without this you never see the summary on Windows.
import os
os.environ["FOR_DISABLE_CONSOLE_CTRL_HANDLER"] = "1"

import argparse
import csv
import signal
import sys
import time
import warnings
from collections import deque
from datetime import datetime

import numpy as np

warnings.filterwarnings("ignore")

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1280          # 80 ms at 16 kHz; openWakeWord's expected frame
PRETRAINED_DEFAULT = "hey_jarvis_v0.1"

_stop = False


def _handle_stop(signum, frame):
    global _stop
    _stop = True


def build_model(model_ref: str, vad_threshold: float = 0.0):
    """Load a pretrained model by name, or a custom .onnx from disk."""
    import openwakeword
    from openwakeword.model import Model

    if model_ref.endswith(".onnx"):
        if not os.path.exists(model_ref):
            raise SystemExit(f"model file not found: {model_ref}")
        # Shared feature extractors are still required for a custom head.
        openwakeword.utils.download_models(model_names=[])
        return Model(wakeword_models=[model_ref],
                     inference_framework="onnx",
                     vad_threshold=vad_threshold)

    openwakeword.utils.download_models(model_names=[model_ref])
    return Model(wakeword_models=[model_ref],
                 inference_framework="onnx",
                 vad_threshold=vad_threshold)


def meter(score: float, width: int = 32) -> str:
    filled = int(min(max(score, 0.0), 1.0) * width)
    return "#" * filled + "." * (width - filled)


def print_summary(detections, started, threshold, model_ref) -> None:
    elapsed = max(time.time() - started, 1e-9)
    print("\n")
    print("--- summary ---")
    print(f"model:       {model_ref}")
    print(f"threshold:   {threshold}")
    print(f"runtime:     {elapsed / 60:.1f} min")
    print(f"detections:  {len(detections)}")
    print(f"rate:        {len(detections) / (elapsed / 3600):.2f} per hour")
    if detections:
        scores = [s for _, s in detections]
        print(f"scores:      min {min(scores):.3f}  "
              f"median {sorted(scores)[len(scores) // 2]:.3f}  "
              f"max {max(scores):.3f}")
    print()
    print("Phase 0: detections should equal the number of times you spoke.")
    print("Phase 4: against ambient audio, every detection is a false accept.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Live wake word detection monitor.")
    ap.add_argument("--model", default=PRETRAINED_DEFAULT,
                    help="pretrained name, or path to a .onnx model")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--device", type=int, default=None, help="input device index")
    ap.add_argument("--cooldown", type=float, default=2.0,
                    help="seconds to suppress repeat triggers")
    ap.add_argument("--vad-threshold", type=float, default=0.0,
                    help="0 disables; 0.3-0.5 gates on speech presence and "
                         "cuts false accepts from non-speech noise")
    ap.add_argument("--duration", type=float, default=None,
                    help="stop automatically after N seconds")
    ap.add_argument("--log", default=None, help="append detections to a CSV file")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress the live meter; use for long unattended runs")
    args = ap.parse_args()

    import sounddevice as sd

    if args.list_devices:
        print(sd.query_devices())
        print("\nPick the index of your microphone and pass it with --device")
        return 0

    signal.signal(signal.SIGINT, _handle_stop)

    print(f"Loading model: {args.model}")
    model = build_model(args.model, vad_threshold=args.vad_threshold)
    print(f"Loaded: {', '.join(model.models.keys())}")

    if args.device is not None:
        sd.default.device = (args.device, None)
    try:
        dev_name = sd.query_devices(sd.default.device[0])["name"]
    except Exception:
        dev_name = "<default>"

    print(f"Input device: {dev_name}")
    print(f"Threshold: {args.threshold}   Cooldown: {args.cooldown}s"
          f"   VAD: {args.vad_threshold or 'off'}")
    if args.duration:
        print(f"Duration:  {args.duration / 60:.1f} min then auto-stop")
    if args.log:
        print(f"Logging to: {args.log}")
    print()
    if args.model == PRETRAINED_DEFAULT:
        print('Say "hey jarvis". Scores should spike well above the threshold.')
        print("Ordinary conversation should stay near zero.")
    print("Ctrl-C to stop early and print the summary.")
    print()

    log_fh = log_writer = None
    if args.log:
        new_file = not os.path.exists(args.log)
        log_fh = open(args.log, "a", newline="")
        log_writer = csv.writer(log_fh)
        if new_file:
            log_writer.writerow(["iso_time", "score", "model", "threshold"])

    detections = []
    recent = deque(maxlen=12)
    last_fire = 0.0
    started = time.time()

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            blocksize=FRAME_SAMPLES) as stream:
            while not _stop:
                if args.duration and (time.time() - started) >= args.duration:
                    break

                frame, overflowed = stream.read(FRAME_SAMPLES)
                if overflowed:
                    print("\r  (audio buffer overflow — machine under load)"
                          + " " * 20)

                top = max(model.predict(frame.flatten()).values())
                recent.append(top)

                now = time.time()
                if top >= args.threshold and (now - last_fire) >= args.cooldown:
                    last_fire = now
                    detections.append((now, top))
                    stamp = datetime.now().strftime("%H:%M:%S")
                    print(f"\r  [{stamp}] DETECTED  score={top:.3f}"
                          f"   (total {len(detections)})" + " " * 12)
                    if log_writer:
                        log_writer.writerow([
                            datetime.now().isoformat(timespec="seconds"),
                            f"{top:.4f}", args.model, args.threshold,
                        ])
                        log_fh.flush()

                if not args.quiet:
                    peak = max(recent)
                    print(f"\r  {meter(peak)}  {peak:.3f} ", end="", flush=True)

    except KeyboardInterrupt:
        pass
    finally:
        if log_fh:
            log_fh.close()

    print_summary(detections, started, args.threshold, args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
