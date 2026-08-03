#!/usr/bin/env python3
"""Stratify recorded clips into a validation manifest by acoustic difficulty.

Peak amplitude is what record_samples.py gates on, but it only catches a broken
mic -- it says nothing about whether a clip is hard to detect. Two clips can
share a peak and differ by 15 dB of SNR. SNR is what tracks difficulty, so it
is what we stratify on here.

The point is to stop reporting one averaged recall number. A set skewed toward
easy clips will report a healthy score while failing every hard clip in it.

Uses the stdlib `wave` module rather than soundfile so this runs anywhere numpy
is present; the clips are all PCM_16 mono by the time they land here.
"""

import argparse
import json
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

FRAME_MS = 20
NOISE_PCTL = 20             # frames below this are treated as room tone
SPEECH_PCTL = 95            # robust stand-in for speech level; ignores clicks

# Boundaries are the natural gaps in the current data, not received wisdom.
# dev0 sits at 23-43 dB, the externally recorded quiet takes at 12-19 dB.
EASY_DB = 25.0
MODERATE_DB = 18.0

EDGE_GUARD_MS = 100
MIN_SPEECH_MS = 400
QUIET_PEAK = 0.08           # kept only so the manifest can note the disagreement


def read_mono(path: Path):
    with wave.open(str(path)) as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"{path.name}: expected 16-bit PCM, got {sw * 8}-bit")
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    return audio, sr


def frame_rms(audio: np.ndarray, sr: int) -> np.ndarray:
    f = int(sr * FRAME_MS / 1000)
    n = len(audio) // f
    if n == 0:
        return np.array([])
    return np.sqrt(np.mean(audio[: n * f].reshape(n, f) ** 2, axis=1))


def analyse(path: Path) -> dict:
    audio, sr = read_mono(path)
    rms = frame_rms(audio, sr)
    total = len(audio) / sr
    peak = float(np.max(np.abs(audio)))

    if rms.size == 0:
        return {"error": "clip shorter than one frame"}

    noise = float(np.percentile(rms, NOISE_PCTL))
    speech = float(np.percentile(rms, SPEECH_PCTL))
    snr = 20 * np.log10(speech / max(noise, 1e-9))

    # Speech extent, same energy gate check_clips.py uses.
    flags, start, end = [], 0.0, 0.0
    peak_rms = rms.max()
    if peak_rms > noise * 1.5:
        thresh = noise + 0.15 * (peak_rms - noise)
        active = np.where(rms > thresh)[0]
        if active.size:
            start = float(active[0] * FRAME_MS / 1000)
            end = float((active[-1] + 1) * FRAME_MS / 1000)
            if start < EDGE_GUARD_MS / 1000:
                flags.append("TRUNCATED-START")
            if end > total - EDGE_GUARD_MS / 1000:
                flags.append("TRUNCATED-END")
            if end - start < MIN_SPEECH_MS / 1000:
                flags.append("VERY-SHORT")
    if not flags and end == 0.0:
        flags.append("NO-SPEECH")

    tier = "easy" if snr >= EASY_DB else "moderate" if snr >= MODERATE_DB else "hard"

    # A low peak with healthy SNR just means a soft talker; the recorder's
    # QUIET flag would reject it, which is why some clips are absent from
    # data recorded through record_samples.py.
    if peak < QUIET_PEAK and tier != "hard":
        flags.append("LOW-PEAK-GOOD-SNR")

    return {
        "sample_rate": sr,
        "duration_s": round(total, 2),
        "peak": round(peak, 4),
        "noise_rms": round(noise, 5),
        "speech_rms": round(speech, 5),
        "snr_db": round(float(snr), 1),
        "speech_start_s": round(start, 2),
        "speech_end_s": round(end, 2),
        "tier": tier,
        "flags": flags,
    }


def speaker_of(wav: Path, fallback: str) -> str:
    """dev0_003.wav -> 'dev0'. Falls back to the containing directory name."""
    stem = wav.stem
    if "_" in stem and stem.rsplit("_", 1)[1].isdigit():
        return stem.rsplit("_", 1)[0]
    return fallback


def index_of(path: str):
    """dev0_003.wav -> 3. None if the name carries no recorder index."""
    stem = Path(path).stem
    if "_" in stem and stem.rsplit("_", 1)[1].isdigit():
        return int(stem.rsplit("_", 1)[1])
    return None


def scan(root: Path, label: str, clips: list, skipped: list) -> None:
    """Collect clips under root. Handles speaker subdirs and flat files alike --
    positives are filed per speaker, negatives are usually just dumped in."""
    if not root.is_dir():
        return
    groups = [(d.name, sorted(d.glob("*.wav")))
              for d in sorted(p for p in root.iterdir() if p.is_dir())]
    flat = sorted(root.glob("*.wav"))
    if flat:
        groups.append((root.name, flat))

    for fallback, wavs in groups:
        for wav in wavs:
            info = analyse(wav)
            if "error" in info:
                skipped.append({"path": wav.as_posix(), "reason": info["error"]})
                continue
            clips.append({"path": wav.as_posix(),
                          "speaker": speaker_of(wav, fallback),
                          "label": label, **info})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--positives", default="data/positives")
    ap.add_argument("--negatives", default="data/negatives")
    ap.add_argument("--out", default="data/validation_manifest.json")
    ap.add_argument("--phrase", default="Cee-Jap")
    ap.add_argument("--labels", default="data/clip_labels.json",
                    help="review_clips.py output; heuristics defer to it when present")
    args = ap.parse_args()

    # By-ear labels outrank every heuristic below. A warning that survives its
    # own disproof trains people to skim the warnings block.
    heard = {}
    lpath = Path(args.labels)
    if lpath.exists():
        for p, v in json.loads(lpath.read_text()).get("labels", {}).items():
            heard[Path(p).name] = v

    posdir, negdir = Path(args.positives), Path(args.negatives)
    if not posdir.is_dir():
        print(f"no positives directory at {posdir}", file=sys.stderr)
        return 1

    clips, skipped = [], []
    scan(posdir, "positive", clips, skipped)
    scan(negdir, "negative", clips, skipped)

    pos = [c for c in clips if c["label"] == "positive"]
    neg = [c for c in clips if c["label"] == "negative"]
    if not pos:
        print(f"no .wav files under {posdir}", file=sys.stderr)
        return 1

    tiers = ["easy", "moderate", "hard"]
    by_tier = {t: [c for c in pos if c["tier"] == t] for t in tiers}
    speakers = sorted({c["speaker"] for c in pos})

    # Difficulty and speaker are separate axes, but only jointly do they tell
    # you whether a miss is the voice or the acoustics.
    cross = {s: {t: sum(1 for c in pos if c["speaker"] == s and c["tier"] == t)
                 for t in tiers} for s in speakers}

    warnings = []
    if not neg:
        warnings.append(
            "No negatives found. Recall is measurable, false-accept rate is not. "
            "For an always-on wake word the false-accept rate is the metric that "
            "decides whether the robot is usable, so this set cannot yet answer "
            "the more important question.")
    else:
        neg_speakers = sorted({c["speaker"] for c in neg})
        if len(neg_speakers) == 1:
            warnings.append(
                f"All {len(neg)} negatives come from one speaker "
                f"({neg_speakers[0]}). False accepts in the field are driven by "
                "voices and sounds the model has never heard, so a single-speaker "
                "negative set measures a narrow slice of the real risk.")
        # Clipped speech is only one source of false accepts, and not the one
        # that bites an always-on device sitting in a room all day.
        if all(c["flags"] != ["NO-SPEECH"] for c in neg):
            warnings.append(
                "Every negative contains speech. Ambient audio with no speech at "
                "all -- room tone, footsteps, HVAC, distant chatter -- is what the "
                "robot hears most of the time, and none of it is represented.")
        if len(neg) < 20:
            warnings.append(
                f"Only {len(neg)} negatives. A false-accept rate below "
                f"{100 / len(neg):.0f}% is not resolvable with this many clips, "
                "and useful wake-word targets are far below that.")

        # The sharpest trap in this set. A negative filed under a speaker who
        # also recorded positives, carrying an index INSIDE that speaker's
        # positive series, came from the same recording session -- so it is most
        # likely a rejected take OF THE WAKE PHRASE, not a true negative. A model
        # that correctly detects the phrase in it gets scored as a false accept,
        # which makes the headline number not merely noisy but backwards.
        pos_speakers = {c["speaker"] for c in pos}
        interleaved = []
        for s in (x for x in neg_speakers if x in pos_speakers):
            pidx = [i for i in (index_of(c["path"]) for c in pos
                                if c["speaker"] == s) if i is not None]
            if not pidx:
                continue
            interleaved += [Path(c["path"]).name for c in neg
                            if c["speaker"] == s
                            and (index_of(c["path"]) or -1) < max(pidx)]
        # Split by what the ear pass actually found. "yes" on a negative means it
        # says the phrase and is misfiled; "no" clears it; unlabelled is unknown.
        confirmed_bad = sorted(n for n in interleaved if heard.get(n) == "yes")
        unchecked = sorted(n for n in interleaved if n not in heard)

        if confirmed_bad:
            warnings.append(
                f"{len(confirmed_bad)} negative(s) were CONFIRMED BY EAR to say the "
                f"wake phrase ({', '.join(confirmed_bad)}). The false-accept rate is "
                "inverted for these: a correct detection scores as an error. Move "
                "them into a positives/ speaker directory or delete them.")
        if unchecked:
            warnings.append(
                f"{len(unchecked)} negative(s) carry indices interleaved with a "
                f"positive series by the same speaker "
                f"({', '.join(unchecked)}) -- i.e. same recording session as the "
                "positives, so they may be discarded takes of the wake phrase "
                "rather than true negatives. Confirm by ear with "
                "review_clips.py data/negatives before trusting any false-accept "
                "number.")
    for t in tiers:
        if len(by_tier[t]) < 5:
            warnings.append(
                f"Only {len(by_tier[t])} positive(s) in the '{t}' tier -- too few "
                f"for a per-tier rate to mean much (one miss moves it by "
                f"{100 / max(len(by_tier[t]), 1):.0f} points).")
    degenerate = [s for s in speakers
                  if sum(1 for t in tiers if cross[s][t] > 0) == 1]
    if degenerate:
        warnings.append(
            f"Speaker(s) {', '.join(degenerate)} occupy a single difficulty tier, "
            "so speaker and difficulty are confounded: a miss cannot be attributed "
            "to one or the other.")

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "phrase": args.phrase,
        "purpose": (
            "Validation only. openWakeWord is trained on synthetic TTS samples "
            "with RIR and background-noise augmentation, at a scale of tens of "
            "thousands; a handful of real recordings is a test set, not a "
            "training set."),
        "tier_thresholds_db": {"easy": EASY_DB, "moderate": MODERATE_DB},
        "metric": (
            f"SNR = 20*log10(p{SPEECH_PCTL} frame RMS / p{NOISE_PCTL} frame RMS), "
            f"{FRAME_MS} ms frames. Tiers rank positives by detection difficulty; "
            "for negatives the same number only describes recording quality, not "
            "how likely the clip is to trigger a false accept."),
        "counts": {"total": len(clips), "positives": len(pos),
                   "negatives": len(neg),
                   **{t: len(by_tier[t]) for t in tiers}},
        "by_speaker": {s: sum(1 for c in pos if c["speaker"] == s)
                       for s in speakers},
        "speaker_by_tier": cross,
        "negatives_by_speaker": {s: sum(1 for c in neg if c["speaker"] == s)
                                 for s in sorted({c["speaker"] for c in neg})},
        # Whether the labels in this manifest were confirmed against the audio
        # or merely inherited from a filename. Without this, a reader cannot
        # tell an ear-verified set from an assumed one.
        "phrase_check": {
            "source": args.labels if heard else None,
            "method": ("review_clips.py -- each clip played and labelled by a "
                       "listener" if heard else "NOT VERIFIED BY EAR"),
            "positives_confirmed": sum(
                1 for c in pos if heard.get(Path(c["path"]).name) == "yes"),
            "positives_rejected": sum(
                1 for c in pos if heard.get(Path(c["path"]).name) == "no"),
            "positives_unheard": sum(
                1 for c in pos if Path(c["path"]).name not in heard),
            "negatives_saying_phrase": sum(
                1 for c in neg if heard.get(Path(c["path"]).name) == "yes"),
            "negatives_unheard": sum(
                1 for c in neg if Path(c["path"]).name not in heard),
        },
        "warnings": warnings,
        "skipped": skipped,
        "clips": sorted(clips, key=lambda c: (c["label"] != "positive",
                                              c["tier"] != "hard",
                                              c["tier"] != "moderate",
                                              c["path"])),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"positives: {len(pos)}    negatives: {len(neg)}\n")
    print(f"{'tier':<10}{'positives':>10}   SNR range")
    print("-" * 42)
    for t in tiers:
        g = by_tier[t]
        if g:
            lo = min(c["snr_db"] for c in g)
            hi = max(c["snr_db"] for c in g)
            print(f"{t:<10}{len(g):>10}   {lo:.1f} - {hi:.1f} dB")
        else:
            print(f"{t:<10}{0:>10}   --")
    print()
    print(f"{'speaker':<10}" + "".join(f"{t:>10}" for t in tiers) + f"{'neg':>8}")
    print("-" * 48)
    for s in sorted(set(speakers) | {c["speaker"] for c in neg}):
        row = "".join(f"{cross.get(s, {}).get(t, 0):>10}" for t in tiers)
        print(f"{s:<10}{row}{sum(1 for c in neg if c['speaker'] == s):>8}")
    print()
    for w in warnings:
        print(f"WARNING: {w}\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
