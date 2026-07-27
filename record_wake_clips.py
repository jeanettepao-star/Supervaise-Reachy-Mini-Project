"""WAKE-REC-1 Phase 1 — operator-driven wake-clip recorder.

Walks a scripted pronunciation session: for each clip in the inventory it prints the
exact line to speak, waits for Enter, records until ~1 s of trailing silence, and saves
a 16 kHz mono WAV (with ~1 s lead/trail padding) into evidence/wake_clips/ under the
canonical filename. Every speaker who sits down gets the SAME script.

Recording needs a mic (`pip install sounddevice`); `--list` is a pure dry-run (no audio,
no deps) that prints the full session script — that is the headless self-check.

  Record: python record_wake_clips.py --speaker sheena
  Dry-run: python record_wake_clips.py --list --speaker sheena

The record_until_silence here is written fresh (energy VAD + noise-floor calibration,
stdlib `wave`); the PLAN-0008 version was read but not ported (it pulls scipy + module
constants and is not trivially portable). No branch merged.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
OUTDIR_DEFAULT = ROOT / "evidence" / "wake_clips"
SAMPLE_RATE = 16000


@dataclass
class Clip:
    filename: str
    prompt: str
    expected: str          # FIRE | SILENT
    style: str


# (key, spoken prompt, style, takes) — POSITIVE clips expected to FIRE
_POS = [
    ("ceejap_normal",    'Cee Jap',      "normal voice",         3),
    ("heyceejap_normal", 'Hey Cee Jap',  "normal voice",         3),
    ("ceejap_soft",      'Cee Jap',      "soft-spoken",          1),
    ("heyceejap_soft",   'Hey Cee Jap',  "soft-spoken",          1),
    ("ceejap_fast",      'Cee Jap',      "quick / casual",       1),
    ("ceejap_far",       'Cee Jap',      "~2-3 m from the mic",  1),
    ("heyceejap_far",    'Hey Cee Jap',  "~2-3 m from the mic",  1),
]
# NEGATIVE clips expected to stay SILENT
_NEG = [
    ("legacy_heycj",   'Hey CJ',    "the RETIRED phrase — MUST stay silent"),
    ("legacy_seejay",  'See Jay',   "the RETIRED phrase — MUST stay silent"),
    ("seejapan",       'a natural phrase containing "see Japan" — e.g. "I would love to see Japan someday."', "near-miss"),
    ("conversation",   '~2 sentences of normal conversation (do NOT say the wake word)', "normal talk"),
]


def session_script(speaker: str) -> list[Clip]:
    clips: list[Clip] = []
    for key, prompt, style, takes in _POS:
        if takes == 1:
            clips.append(Clip(f"wake_pos_{key}_{speaker}.wav", prompt, "FIRE", style))
        else:
            for t in range(1, takes + 1):
                clips.append(Clip(f"wake_pos_{key}_{speaker}_t{t}.wav", prompt, "FIRE", f"{style}, take {t}"))
    for key, prompt, style in _NEG:
        clips.append(Clip(f"wake_neg_{key}_{speaker}.wav", prompt, "SILENT", style))
    return clips


# --------------------------------------------------------------- recording (needs a mic)
def record_until_silence(max_seconds: float = 6.0, trailing_silence_ms: int = 1000,
                         pad_ms: int = 1000, samplerate: int = SAMPLE_RATE):
    """Energy-VAD recorder: calibrate the noise floor, capture until ~trailing_silence_ms
    after speech (or max_seconds), pad lead/trail with silence. Returns an int16 ndarray."""
    import numpy as np
    import sounddevice as sd
    frame_ms = 30
    frame = int(samplerate * frame_ms / 1000)
    trail_frames = max(1, trailing_silence_ms // frame_ms)
    max_frames = int(max_seconds * 1000 / frame_ms)

    probe = sd.rec(int(0.24 * samplerate), samplerate=samplerate, channels=1, dtype="int16")
    sd.wait()
    floor = float(np.sqrt(np.mean(probe.astype(np.float64) ** 2))) or 1.0
    thr = max(floor * 4.0, 300.0)          # speech threshold above the room noise floor

    collected, speech, silence_run, spoke = [], False, 0, 0
    with sd.InputStream(samplerate=samplerate, channels=1, dtype="int16", blocksize=frame) as stream:
        for _ in range(max_frames):
            block, _ = stream.read(frame)
            collected.append(block.copy())
            rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)))
            if rms >= thr:
                spoke += 1
                speech = speech or spoke >= 3     # ~90 ms of speech before we trust it
                silence_run = 0
            elif speech:
                silence_run += 1
                if silence_run >= trail_frames:
                    break
    audio = np.concatenate(collected).flatten() if collected else np.zeros(0, dtype="int16")
    pad = np.zeros(int(pad_ms / 1000 * samplerate), dtype="int16")
    return np.concatenate([pad, audio, pad])


def save_wav(path: Path, samples, samplerate: int = SAMPLE_RATE) -> None:
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(samplerate)
        w.writeframes(samples.tobytes())


# --------------------------------------------------------------- CLI
def print_script(speaker: str, clips: list[Clip]) -> None:
    print(f"=== WAKE-REC session script — speaker '{speaker}' — {len(clips)} clips "
          f"({sum(c.expected=='FIRE' for c in clips)} FIRE / {sum(c.expected=='SILENT' for c in clips)} SILENT) ===")
    print(f"Spec: 16 kHz mono WAV · ~1 s lead/trail silence · saved to evidence/wake_clips/\n")
    for i, c in enumerate(clips, 1):
        print(f"[{i:2}/{len(clips)}] {c.filename}   (expect: {c.expected})")
        print(f"        SAY ({c.style}):  {c.prompt}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Operator-driven wake-clip recorder (WAKE-REC-1).")
    ap.add_argument("--speaker", help="speaker id, stamped into every filename (required to record)")
    ap.add_argument("--list", action="store_true", help="print the session script and exit (no mic, no recording)")
    ap.add_argument("--outdir", default=str(OUTDIR_DEFAULT), help="output dir (default: evidence/wake_clips/)")
    ap.add_argument("--max-seconds", type=float, default=6.0)
    args = ap.parse_args(argv)

    if not args.speaker:
        ap.error("--speaker is required (e.g. --speaker sheena)")
    clips = session_script(args.speaker)

    if args.list:
        print_script(args.speaker, clips)
        return 0

    outdir = Path(args.outdir)
    print(f"Recording {len(clips)} clips for '{args.speaker}' -> {outdir}\n")
    for i, c in enumerate(clips, 1):
        print(f"[{i:2}/{len(clips)}] {c.filename}   (expect: {c.expected})")
        print(f"        SAY ({c.style}):  {c.prompt}")
        cmd = input("        Press Enter to record (s=skip, q=quit): ").strip().lower()
        if cmd == "q":
            break
        if cmd == "s":
            print("        …skipped\n")
            continue
        samples = record_until_silence(max_seconds=args.max_seconds)
        save_wav(outdir / c.filename, samples)
        print(f"        saved {c.filename} ({len(samples)/SAMPLE_RATE:.1f}s)\n")
    print("Done. Verify with: python verify_wake_clips.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
