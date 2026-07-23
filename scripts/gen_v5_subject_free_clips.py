"""Regenerate the SUBJECT-FREE filler pool (Option D) with OpenAI tts-1.

Synthesizes every line in filler_route.NEUTRAL_TEXTS to
  assets/filler_clips/<voice>/neutral/NN.mp3   (NN = 01, 02, ...)
at voice_job.FILLER_TTS_SPEED (1.25x, matching the theme clips), clears any stale
neutral clips first, and syncs the per-file durations in
eval/results/filler_v5_clip_durations.json so voice_job._dur_of stays accurate.

These are the ONLY clips spoken when filler_route.SUBJECT_FREE_MODE is ON (the demo
default): characterful, in-voice hedges that name no theme/topic. The .mp3s are
gitignored (repo policy); this script makes the pool reproducible.

Usage (repo root, OPENAI_API_KEY in app/.env):
  python scripts/gen_v5_subject_free_clips.py            # onyx (demo default)
  python scripts/gen_v5_subject_free_clips.py --voice nova
  python scripts/gen_v5_subject_free_clips.py --all      # every VOICES entry
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
load_dotenv(ROOT / "app" / ".env", override=False)

import filler_route            # noqa: E402  (the LOCKED subject-free text lives here)
import voice_job               # noqa: E402  (FILLER_TTS_SPEED)
from openai import OpenAI      # noqa: E402

VOICES = ["onyx", "alloy", "echo", "fable", "nova", "shimmer"]
HARD_CAP_S = 5.0
MANIFEST = ROOT / "eval" / "results" / "filler_v5_clip_durations.json"


def _dur(path: Path) -> float:
    try:
        from mutagen.mp3 import MP3
        return round(MP3(str(path)).info.length, 3)
    except Exception:
        return 4.5


def gen_voice(oai, voice: str) -> list:
    out = ROOT / "assets" / "filler_clips" / voice / "neutral"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.mp3"):            # clear stale clips (pool may shrink/grow)
        old.unlink()
    written = []
    for i, text in enumerate(filler_route.NEUTRAL_TEXTS, start=1):
        mp3 = oai.audio.speech.create(model="tts-1", voice=voice, input=text,
                                      speed=voice_job.FILLER_TTS_SPEED).content
        p = out / f"{i:02d}.mp3"
        p.write_bytes(mp3)
        secs = _dur(p)
        flag = "  !! OVER CAP" if secs > HARD_CAP_S else ""
        print(f"  {voice}/{p.name}: {len(mp3):5d}B  {secs:.3f}s{flag}  \"{text}\"")
        written.append((p, secs))
    return written


def sync_manifest(all_written: dict):
    if not MANIFEST.exists():
        return
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    clips = [c for c in m.get("clips", [])
             if "/neutral/" not in c["file"].replace("\\", "/")]   # drop old neutral entries
    for voice, written in all_written.items():
        for p, secs in written:
            rel = str(p.relative_to(ROOT))
            clips.append({"file": rel, "seconds": secs})
    m["clips"] = clips
    m["n_neutral"] = sum(1 for c in clips if "/neutral/" in c["file"].replace("\\", "/"))
    m["n_clips"] = len(clips)
    m.setdefault("notes", [])
    MANIFEST.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"synced {MANIFEST.name}: n_neutral={m['n_neutral']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="onyx")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    voices = VOICES if args.all else [args.voice]
    oai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    chars = len(filler_route.NEUTRAL_TEXTS) * len(voices)
    total_chars = sum(len(t) for t in filler_route.NEUTRAL_TEXTS) * len(voices)
    print(f"subject-free pool: {len(filler_route.NEUTRAL_TEXTS)} clips x {len(voices)} voice(s) "
          f"@ {voice_job.FILLER_TTS_SPEED}x  (~${round(total_chars * 15 / 1e6, 4)})")
    all_written = {v: gen_voice(oai, v) for v in voices}
    sync_manifest(all_written)
    over = [(v, p.name, s) for v, w in all_written.items() for p, s in w if s > HARD_CAP_S]
    if over:
        print(f"WARNING: {len(over)} clip(s) over the {HARD_CAP_S}s cap — shorten the text: {over}")
    print(f"done: {chars} clips written.")


if __name__ == "__main__":
    main()
