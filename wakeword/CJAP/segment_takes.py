#!/usr/bin/env python3
"""Split a continuous repetition recording into one clip per take.

data/_originals/pao6.wav is 30 s of the phrase repeated ~14 times. It never got
converted, so those takes are absent from the set while every other original is
in it -- the largest and cheapest data gain available.

Writes to a STAGING directory, never into data/positives/. Nothing here has been
heard yet, and the positives set is ear-verified (see validation_manifest.json
-> phrase_check). Mixing unheard clips into a verified set silently downgrades
the whole set to unverified. Promote only after review_clips.py.

Resamples from the 44.1 kHz stereo original with resample_poly, the same path
the existing elaine/pao clips document in their meta.json, rather than cutting
up the already-downsampled review copy.

    python segment_takes.py                              # -> data/candidates/pao
    python review_clips.py data/candidates/pao --device 4
    python promote_candidates.py                         # after listening
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

TARGET_SR = 16_000
FRAME_MS = 20

# A wake word is decided by its edges -- the /s/ onset and the /p/ release. An
# energy gate always trims both, so pad generously; openWakeWord slides a window
# and tolerates leading/trailing room tone far better than a clipped phoneme.
PAD_S = 0.30
GATE_FRAC = 0.10            # of (peak - noise); lower than check_clips' 0.15 to
                            # catch quiet onsets rather than clip them
MERGE_GAP_S = 0.30          # gaps shorter than this are within one take
MIN_TAKE_S = 0.25


def load_16k_mono(path: Path):
    audio, sr = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:
        g = np.gcd(int(sr), TARGET_SR)
        audio = resample_poly(audio, TARGET_SR // g, int(sr) // g)
    return audio.astype("float32")


def find_takes(audio: np.ndarray):
    """-> [(start_s, end_s)] for each utterance, before padding."""
    f = int(TARGET_SR * FRAME_MS / 1000)
    n = len(audio) // f
    rms = np.sqrt(np.mean(audio[: n * f].reshape(n, f) ** 2, axis=1))
    noise, peak = float(np.percentile(rms, 20)), float(rms.max())
    if peak <= noise * 1.5:
        return [], noise, peak

    active = rms > noise + GATE_FRAC * (peak - noise)
    max_gap = int(MERGE_GAP_S * 1000 / FRAME_MS)

    takes, start, gap = [], None, 0
    for i, on in enumerate(active):
        if on:
            start, gap = (i if start is None else start), 0
        elif start is not None:
            gap += 1
            if gap > max_gap:
                end = i - gap
                if (end - start) * FRAME_MS / 1000 >= MIN_TAKE_S:
                    takes.append((start * FRAME_MS / 1000, end * FRAME_MS / 1000))
                start, gap = None, 0
    if start is not None:
        end = len(active)
        if (end - start) * FRAME_MS / 1000 >= MIN_TAKE_S:
            takes.append((start * FRAME_MS / 1000, end * FRAME_MS / 1000))
    return takes, noise, peak


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="data/_originals/pao6.wav")
    ap.add_argument("--outdir", default="data/candidates/pao")
    ap.add_argument("--speaker", default="pao")
    ap.add_argument("--start-index", type=int, default=None,
                    help="default: continue the speaker's existing series")
    ap.add_argument("--positives", default="data/positives",
                    help="read next_index from here to avoid name collisions")
    ap.add_argument("--pad", type=float, default=PAD_S)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        print(f"no source at {src}", file=sys.stderr)
        return 1

    audio = load_16k_mono(src)
    takes, noise, peak = find_takes(audio)
    if not takes:
        print(f"no takes found in {src.name}", file=sys.stderr)
        return 1

    # Continue the existing series so a promoted clip never collides. Consider
    # negatives too -- dev0_020/021 live there, and an index is only unique if
    # it is unique across every directory the speaker's clips can land in.
    if args.start_index is not None:
        nxt = args.start_index
    else:
        used = {-1}
        for d in (Path(args.positives) / args.speaker, Path("data/negatives"),
                  Path(args.outdir)):
            for w in d.glob(f"{args.speaker}_*.wav") if d.is_dir() else []:
                stem = w.stem.rsplit("_", 1)[1]
                if stem.isdigit():
                    used.add(int(stem))
        meta = Path(args.positives) / args.speaker / "meta.json"
        if meta.exists():
            used.add(json.loads(meta.read_text()).get("next_index", 0) - 1)
        nxt = max(used) + 1

    outdir = Path(args.outdir)
    if not args.dry_run:
        outdir.mkdir(parents=True, exist_ok=True)

    print(f"source:  {src}  ({len(audio)/TARGET_SR:.1f}s @ {TARGET_SR} Hz)")
    print(f"gate:    noise {noise:.4f}  peak {peak:.4f}")
    print(f"takes:   {len(takes)}   naming from {args.speaker}_{nxt:03d}\n")
    print(f"{'clip':18} {'window':>16} {'dur':>6} {'peak':>7}  note")
    print("-" * 66)

    written = []
    for i, (s, e) in enumerate(takes):
        a = max(0.0, s - args.pad)
        b = min(len(audio) / TARGET_SR, e + args.pad)
        seg = audio[int(a * TARGET_SR):int(b * TARGET_SR)]
        pk = float(np.max(np.abs(seg)))
        name = f"{args.speaker}_{nxt + i:03d}.wav"

        notes = []
        if a == 0.0 or b >= len(audio) / TARGET_SR - 1e-6:
            notes.append("EDGE-OF-SOURCE")
        if pk < 0.08:
            notes.append("QUIET")
        if not args.dry_run:
            sf.write(outdir / name, seg, TARGET_SR, subtype="PCM_16")
        written.append({"clip": name, "source_start_s": round(a, 2),
                        "source_end_s": round(b, 2),
                        "duration_s": round(b - a, 2), "peak": round(pk, 4),
                        "notes": notes})
        print(f"{name:18} {a:6.2f}-{b:5.2f}s {b-a:5.2f}s {pk:7.3f}  "
              f"{' '.join(notes)}")

    if args.dry_run:
        print(f"\ndry run -- nothing written")
        return 0

    (outdir / "meta.json").write_text(json.dumps({
        "speaker": args.speaker,
        "phrase": "Cee-Jap",
        "phrase_verified": "pending_listen",
        "status": "CANDIDATE -- not part of the validation set",
        "sample_rate": TARGET_SR,
        "clips": len(written),
        "format": "PCM_16 mono",
        "source": (f"Segmented from {src.as_posix()} (44.1 kHz stereo original) "
                   "by segment_takes.py: downmixed to mono, resampled with "
                   f"scipy.signal.resample_poly, split on an energy gate, each "
                   f"take padded by {args.pad:g}s on both sides."),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "takes": written,
    }, indent=2) + "\n")

    print(f"\nwrote {len(written)} candidate clip(s) to {outdir}")
    print(f"\nNEXT -- these have not been heard:")
    print(f"  python review_clips.py {outdir.as_posix()} --device 4")
    print("  then promote the ones labelled 'yes' into "
          f"{Path(args.positives).as_posix()}/{args.speaker}/")
    print("\nDo NOT copy them in unheard: the positives set is ear-verified, and "
          "one unverified clip makes the whole set unverified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
