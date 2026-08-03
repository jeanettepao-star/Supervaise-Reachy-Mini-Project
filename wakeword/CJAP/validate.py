#!/usr/bin/env python3
"""Score a wake word model against the stratified validation manifest.

Reports recall per difficulty tier rather than one aggregate number. The set is
skewed toward easy clips, so an aggregate score is dominated by them and can sit
above 90% while every hard clip fails.

Build the manifest first:  python build_validation_set.py
"""

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

FRAME_SAMPLES = 1280        # openWakeWord's fixed streaming chunk at 16 kHz
SAMPLE_RATE = 16_000
TIERS = ["easy", "moderate", "hard"]


def load_int16(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        if w.getframerate() != SAMPLE_RATE:
            raise ValueError(f"{path.name}: {w.getframerate()} Hz, expected {SAMPLE_RATE}")
        if w.getsampwidth() != 2:
            raise ValueError(f"{path.name}: not 16-bit PCM")
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        if w.getnchannels() > 1:
            audio = audio.reshape(-1, w.getnchannels()).mean(axis=1).astype(np.int16)
    return audio


def build_model(model_ref: str):
    import openwakeword
    from openwakeword.model import Model

    if model_ref.endswith(".onnx"):
        return Model(wakeword_models=[model_ref], inference_framework="onnx")
    openwakeword.utils.download_models(model_names=[model_ref])
    return Model(wakeword_models=[model_ref], inference_framework="onnx")


def score_clip(model, audio: np.ndarray) -> float:
    """Peak score across the clip. Resets model state so clips stay independent.

    Pads the clip with 2 s of leading and 0.5 s of trailing silence. The model
    scores a *stream* through a 2 s feature window, so a file shorter than the
    window ends before the phrase is ever seen in full context and scores ~0
    regardless of content (measured: 1 s clips of a verified phrase at 0.002
    raw vs 0.742 padded). The kiosk hears a continuous stream and never has
    this problem, so the padded number is the deployment-realistic one.
    """
    if hasattr(model, "reset"):
        model.reset()
    audio = np.concatenate([np.zeros(2 * SAMPLE_RATE, dtype=audio.dtype), audio,
                            np.zeros(SAMPLE_RATE // 2, dtype=audio.dtype)])
    best = 0.0
    for i in range(0, len(audio) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
        scores = model.predict(audio[i:i + FRAME_SAMPLES])
        best = max(best, max(scores.values()))
    return float(best)


def rate(hits: int, total: int) -> str:
    return f"{100 * hits / total:5.1f}%" if total else "    --"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default="data/validation_manifest.json")
    ap.add_argument("--model", default="hey_jarvis_v0.1")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--expect", choices=["detect", "reject"], default="detect",
                    help="'detect' if the model was trained on this manifest's "
                         "phrase (fraction firing = recall). 'reject' if it was "
                         "not, e.g. a stock model (fraction firing = "
                         "false-accept rate). Same number, opposite meaning.")
    args = ap.parse_args()

    mpath = Path(args.manifest)
    if not mpath.exists():
        print(f"no manifest at {mpath}; run build_validation_set.py first",
              file=sys.stderr)
        return 1
    manifest = json.loads(mpath.read_text())
    clips = manifest["clips"]

    print(f"Loading model: {args.model}")
    try:
        model = build_model(args.model)
    except ImportError:
        print("openwakeword is not installed.  pip install openwakeword",
              file=sys.stderr)
        return 1
    print(f"Loaded: {', '.join(model.models.keys())}")
    print(f"Phrase: {manifest['phrase']}   Threshold: {args.threshold}\n")

    for c in clips:
        try:
            c["score"] = score_clip(model, load_int16(Path(c["path"])))
            c["detected"] = c["score"] >= args.threshold
        except (ValueError, FileNotFoundError, wave.Error) as e:
            print(f"  SKIP {c['path']}: {e}", file=sys.stderr)
            c["score"], c["detected"] = None, None

    scored = [c for c in clips if c["detected"] is not None]
    if not scored:
        print("nothing scored", file=sys.stderr)
        return 1

    detecting = args.expect == "detect"
    pos = [c for c in scored if c.get("label", "positive") == "positive"]
    neg = [c for c in scored if c.get("label") == "negative"]

    if not detecting:
        print(f"--expect reject: '{args.model}' was not trained on "
              f"\"{manifest['phrase']}\", so the positives are expected to miss "
              f"too. Every activation below is spurious.\n")

    print(f"{'clip':<22}{'label':<10}{'tier':<10}{'SNR':>6}{'score':>8}   result")
    print("-" * 72)
    for c in sorted(scored, key=lambda c: (c.get("label", "positive") != "positive",
                                           c["snr_db"])):
        label = c.get("label", "positive")
        should_fire = detecting and label == "positive"
        if should_fire:
            mark = "hit " if c["detected"] else "MISS"
        else:
            mark = "FALSE ACCEPT" if c["detected"] else "ok"
        print(f"{Path(c['path']).name:<22}{label:<10}{c['tier']:<10}"
              f"{c['snr_db']:>6.1f}{c['score']:>8.3f}   {mark}")

    if pos:
        metric = "recall" if detecting else "false-accept rate"
        print(f"\n--- positives: {metric} by tier ---")
        for t in TIERS:
            g = [c for c in pos if c["tier"] == t]
            if g:
                lo = min(x["snr_db"] for x in g)
                hi = max(x["snr_db"] for x in g)
                fired = sum(1 for x in g if x["detected"])
                print(f"  {t:<10}{rate(fired, len(g))}  ({fired}/{len(g)})"
                      f"   {lo:.1f}-{hi:.1f} dB")

        print(f"\n--- positives: {metric} by speaker ---")
        for s in sorted({c["speaker"] for c in pos}):
            g = [c for c in pos if c["speaker"] == s]
            fired = sum(1 for x in g if x["detected"])
            print(f"  {s:<10}{rate(fired, len(g))}  ({fired}/{len(g)})")

        p_fired = sum(1 for c in pos if c["detected"])
        n_easy = sum(1 for c in pos if c["tier"] == "easy")
        print(f"\n  {'ALL':<10}{rate(p_fired, len(pos))}  ({p_fired}/{len(pos)})")
        print(f"  Read that with care: {n_easy} of {len(pos)} positives are 'easy'.")

    if neg:
        print("\n--- negatives: false-accept rate ---")
        for s in sorted({c["speaker"] for c in neg}):
            g = [c for c in neg if c["speaker"] == s]
            fired = sum(1 for x in g if x["detected"])
            print(f"  {s:<10}{rate(fired, len(g))}  ({fired}/{len(g)})")
        n_fired = sum(1 for c in neg if c["detected"])
        print(f"\n  {'ALL':<10}{rate(n_fired, len(neg))}  ({n_fired}/{len(neg)})")
        print(f"  Resolution floor is {100 / len(neg):.0f}% with {len(neg)} clips; "
              "a real target sits far below that.")

    misses = [c for c in pos if not c["detected"]] if detecting else []
    if misses:
        print(f"\n--- {len(misses)} missed positives ---")
        for c in sorted(misses, key=lambda c: c["snr_db"]):
            flags = f"  [{', '.join(c['flags'])}]" if c["flags"] else ""
            print(f"  {Path(c['path']).name:<22}{c['snr_db']:>6.1f} dB  "
                  f"score {c['score']:.3f}{flags}")

    spurious = [c for c in scored if c["detected"]
                and not (detecting and c.get("label", "positive") == "positive")]
    if spurious:
        print(f"\n--- {len(spurious)} false accepts ---")
        for c in sorted(spurious, key=lambda c: -c["score"]):
            flags = f"  [{', '.join(c['flags'])}]" if c["flags"] else ""
            print(f"  {Path(c['path']).name:<22}{c['snr_db']:>6.1f} dB  "
                  f"score {c['score']:.3f}{flags}")

    # A near-miss below threshold is one gain change away from firing, so it
    # belongs in the report even though it did not cross the line.
    near = [c for c in scored if not c["detected"]
            and c["score"] >= args.threshold * 0.8
            and not (detecting and c.get("label", "positive") == "positive")]
    if near:
        print(f"\n--- {len(near)} near-miss (>= {args.threshold * 0.8:.2f}) ---")
        for c in sorted(near, key=lambda c: -c["score"]):
            print(f"  {Path(c['path']).name:<22}{c['snr_db']:>6.1f} dB  "
                  f"score {c['score']:.3f}")

    for w in manifest.get("warnings", []):
        print(f"\nNOTE: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
