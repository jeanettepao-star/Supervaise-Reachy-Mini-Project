"""FILLER v5 Part B — pre-synthesize the 50 THEME clips (10 variants x 5 themes) +
3 NEUTRAL clips with OpenAI tts-1 voice=onyx. FULL sentences (no splicing).

Layout (per-voice, task B.6):
  assets/filler_clips/onyx/themes/<A..E>/<NN>.mp3     (NN = 01..10, the variant)
  assets/filler_clips/onyx/neutral/<NN>.mp3           (NN = 01..03)

The .mp3 clips are gitignored (repo policy); this script makes the pool reproducible.
Writes a committed durations manifest (assets .. is gitignored, manifest is evidence):
  eval/results/filler_v5_clip_durations.json  — every clip's seconds, ELEVATES over 5.0s.

Usage (repo root, OPENAI_API_KEY in app/.env):
  .venv/Scripts/python.exe scripts/gen_v5_theme_clips.py
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from mutagen.mp3 import MP3

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "app" / ".env", override=False)
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import filler_route as fr  # noqa: E402
import os
from openai import OpenAI

VOICE = "onyx"
HARD_CAP_S = 5.0
# The Sheena-final variants run 3.8-6.2s at speed 1.0 for the longer theme names —
# 28/50 would breach the 5.0s hard cap. Text is LOCKED, so the only compliant lever
# is a brisker filler pace: 1.25x brings the 6.19s worst-case to ~4.95s. This is
# faster than the 0.98 answer pace (a filler-register choice) — see report FLAG.
SPEED = float(os.environ.get("CJ_FILLER_V5_SPEED", "1.25"))
OUT = ROOT / "assets" / "filler_clips" / VOICE
oai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def synth(text: str, dest: Path) -> float:
    dest.parent.mkdir(parents=True, exist_ok=True)
    mp3 = oai.audio.speech.create(model="tts-1", voice=VOICE, input=text, speed=SPEED).content
    dest.write_bytes(mp3)
    return round(MP3(dest).info.length, 3)


rows, total_chars, over = [], 0, []
# THEME clips
for theme in fr.THEMES:
    for vi in range(len(fr.THEME_VARIANTS)):
        text = fr.render_theme(theme, vi)
        dest = OUT / "themes" / theme / f"{vi + 1:02d}.mp3"
        dur = synth(text, dest)
        total_chars += len(text)
        rows.append({"kind": "theme", "theme": theme, "variant": vi + 1,
                     "file": str(dest.relative_to(ROOT)), "chars": len(text),
                     "seconds": dur, "text": text})
        if dur > HARD_CAP_S:
            over.append((dest.name, theme, vi + 1, dur, text))
        print(f"  {theme}/{vi+1:02d}  {dur:4.2f}s  \"{text[:58]}\"")
# NEUTRAL clips
for i, text in enumerate(fr.NEUTRAL_TEXTS):
    dest = OUT / "neutral" / f"{i + 1:02d}.mp3"
    dur = synth(text, dest)
    total_chars += len(text)
    rows.append({"kind": "neutral", "theme": None, "variant": i + 1,
                 "file": str(dest.relative_to(ROOT)), "chars": len(text),
                 "seconds": dur, "text": text})
    if dur > HARD_CAP_S:
        over.append((dest.name, "NEUTRAL", i + 1, dur, text))
    print(f"  neutral/{i+1:02d}  {dur:4.2f}s  \"{text}\"")

durs = [r["seconds"] for r in rows]
manifest = {
    "voice": VOICE, "model": "tts-1", "speed": SPEED, "n_clips": len(rows),
    "n_theme": 50, "n_neutral": 3, "hard_cap_s": HARD_CAP_S,
    "over_cap": [{"file": o[0], "theme": o[1], "variant": o[2], "seconds": o[3], "text": o[4]} for o in over],
    "duration_stats": {"min": min(durs), "max": max(durs),
                       "mean": round(sum(durs) / len(durs), 3)},
    "synthesis_cost_usd": round(total_chars * 15 / 1e6, 4),
    "total_chars": total_chars,
    "clips": rows,
}
mp = ROOT / "eval" / "results" / "filler_v5_clip_durations.json"
mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"\n{len(rows)} clips  min={min(durs)}s max={max(durs)}s  over-cap={len(over)}  "
      f"cost=${manifest['synthesis_cost_usd']}")
print("wrote", mp.relative_to(ROOT))
if over:
    print("!! OVER 5.0s CAP:", over)
