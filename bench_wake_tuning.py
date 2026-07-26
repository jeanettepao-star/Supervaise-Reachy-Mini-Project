"""WAKE-LIVE-1 — live wake-word bench-tuning harness + evidence capture.

Runs the SAME code path as wake_demo.py (mic -> STT -> the PRODUCTION wake matcher)
and logs every trial/utterance to an append-only CSV, so bench_wake_report.py can score
live real-voice behavior against the acceptance targets. This measures what the live STT
actually TRANSCRIBES from accented speech — the offline self-test only proved the text
matcher. It does NOT modify the matcher, the variant list, or config.WAKE_PHRASE.

Modes:
  --mode wake  : interactive. Press Enter to arm a trial, speak; one row logged.
                 Requires --speaker; --distance {near,far} stamps every row.
  --mode soak  : continuous listen for --minutes (default 15); logs EVERY utterance;
                 ANY wake fire is flagged false_accept.
  --simulate   : headless self-check — feeds canned transcripts through the matcher path
                 (no mic, no STT) so the CSV write/append + report are verifiable offline.

Bench:      CJ_WAKE_WORD_ENABLED=1 python bench_wake_tuning.py --mode wake --speaker sheena --distance near
Self-check: python bench_wake_tuning.py --simulate --outdir <dir>
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

try:                                    # console-safe unicode (Windows cp1252 chokes on “ ” ≥)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config          # noqa: E402
import wake_word       # noqa: E402  (the production matcher/detector — never duplicated here)

COLS = ["timestamp", "mode", "speaker", "distance", "trial", "transcript",
        "matched_variant", "wake_fired", "score", "false_accept", "notes"]

# canned transcripts for --simulate: a clean hit, a second hit, and an accented mishear
# ("si jap") that the matcher misses — exactly the kind of live form the missed-transcripts
# report is meant to surface for a (separate, reviewed) variant addition.
SIMULATE_TRANSCRIPTS = ["hey see jap", "cee jap", "si jap"]


def csv_path(outdir: Path) -> Path:
    return outdir / f"wake_bench_{datetime.now().strftime('%Y-%m-%d')}.csv"


def log_row(path: Path, row: dict) -> None:
    """Append one row. utf-8-sig on file creation (BOM once), plain utf-8 on append so
    no BOM is ever written mid-file; round-trips cleanly under csv + utf-8-sig reads."""
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerow(row)


def make_row(mode, speaker, distance, trial, res, false_accept="") -> dict:
    return {"timestamp": datetime.now().isoformat(timespec="seconds"), "mode": mode,
            "speaker": speaker, "distance": distance, "trial": trial,
            "transcript": res.heard, "matched_variant": res.variant or "NONE",
            "wake_fired": "Y" if res.fired else "N", "score": res.score,
            "false_accept": false_accept, "notes": ""}


def run_simulate(path: Path, speaker: str, distance: str) -> int:
    """Headless: feed canned transcripts through the PRODUCTION matcher path."""
    matcher = wake_word.make_detector().matcher      # the production matcher instance
    print(f"[simulate] matcher={matcher} -> {path}")
    for i, text in enumerate(SIMULATE_TRANSCRIPTS, 1):
        res = matcher.match(text)
        log_row(path, make_row("simulate", speaker, distance, i, res))
        print(f"  trial {i}: {text!r:16} -> fired={res.fired} variant={res.variant} score={res.score}")
    print(f"[simulate] wrote {len(SIMULATE_TRANSCRIPTS)} rows (append-only) to {path}")
    return 0


def run_wake(path: Path, speaker: str, distance: str, window: float) -> int:
    """Interactive: Enter arms a trial, operator speaks, one row logged."""
    detector = wake_word.make_detector()
    gen = wake_word.MicAudioSource(window_s=window).windows()   # one recording per next()
    print(f"[wake] speaker={speaker} distance={distance} window={window}s -> {path}")
    print(f"[wake] say “{config.WAKE_PHRASE}”. Enter to arm a trial; 'q' then Enter to finish.")
    trial = 1
    while True:
        cmd = input(f"  arm trial {trial}? [Enter=go / q=quit] ").strip().lower()
        if cmd in ("q", "quit"):
            break
        wav = next(gen)                              # records one window AFTER the operator is ready
        res = detector.detect(wav)
        log_row(path, make_row("wake", speaker, distance, trial, res))
        print(f"    trial {trial}: fired={'Y' if res.fired else 'N'}  variant={res.variant}  "
              f"heard={res.heard!r}")
        trial += 1
    print(f"[wake] {trial-1} trials logged to {path}")
    return 0


def run_soak(path: Path, speaker: str, distance: str, minutes: float) -> int:
    """Continuous listen; log every utterance; any fire = false accept."""
    detector = wake_word.make_detector()
    windows = wake_word.MicAudioSource(window_s=config.WAKE_WINDOW_S).windows()
    deadline = time.time() + minutes * 60.0
    print(f"[soak] speaker={speaker} for {minutes:.0f} min -> {path} (Ctrl-C to stop early)")
    i = 0
    for wav in windows:
        if time.time() >= deadline:
            break
        res = detector.detect(wav)
        i += 1
        fa = "Y" if res.fired else "N"
        log_row(path, make_row("soak", speaker, distance, i, res, false_accept=fa))
        if res.fired:
            print(f"  !! FALSE ACCEPT utterance {i}: heard={res.heard!r} -> {res.variant}")
    print(f"[soak] {i} utterances logged to {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Live wake-word bench-tuning harness (WAKE-LIVE-1). Two modes: "
                    "--mode wake (interactive trials) and --mode soak (false-accept soak). "
                    "--simulate runs a headless self-check.")
    ap.add_argument("--mode", choices=["wake", "soak"], help="wake = interactive trials; soak = continuous false-accept soak")
    ap.add_argument("--speaker", help="speaker id stamped on every row (required in wake mode)")
    ap.add_argument("--distance", choices=["near", "far"], default="near", help="near (~1m) | far (~2-3m)")
    ap.add_argument("--minutes", type=float, default=15.0, help="soak duration (default 15)")
    ap.add_argument("--window", type=float, default=None, help="wake trial record window s (default config.WAKE_WINDOW_S)")
    ap.add_argument("--simulate", action="store_true", help="headless self-check via canned transcripts (no mic/STT)")
    ap.add_argument("--outdir", default="evidence", help="output dir for wake_bench_<date>.csv (default: evidence/)")
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    path = csv_path(outdir)

    if args.simulate:
        return run_simulate(path, args.speaker or "sim", args.distance)
    if not args.mode:
        ap.error("choose --mode wake|soak, or --simulate for the headless check")
    if args.mode == "wake" and not args.speaker:
        ap.error("--mode wake requires --speaker (e.g. --speaker sheena)")
    window = args.window or float(config.WAKE_WINDOW_S)
    if args.mode == "wake":
        return run_wake(path, args.speaker, args.distance, window)
    return run_soak(path, args.speaker or "ambient", args.distance, args.minutes)


if __name__ == "__main__":
    raise SystemExit(main())
