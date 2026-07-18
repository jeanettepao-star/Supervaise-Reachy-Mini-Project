"""Regenerate the CJ-voiced TTFA filler pool (13 approved clips) with OpenAI tts-1 voice=onyx.
The .mp3 clips are gitignored (repo policy); this script makes the pool reproducible (~$0.005).
Approved set = filler_pool_PROPOSAL.md, Dev0's pick (acks #1-10 + the 3 bridges).

Usage (repo root, OPENAI_API_KEY in app/.env):  python scripts/gen_onyx_filler_pool.py
"""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "app" / ".env", override=False)
from openai import OpenAI

OUT = ROOT / "assets" / "filler_clips" / "onyx"
OUT.mkdir(parents=True, exist_ok=True)
CLIPS = {  # id -> text  ("bridge" in the id => stage-2 bridge; else stage-1 ack)
    "ack_01": "Permit me a moment.",
    "ack_02": "Allow me a moment to reflect.",
    "ack_03": "Let me say this.",
    "ack_04": "Let me tell you candidly.",
    "ack_05": "If I may be allowed a moment.",
    "ack_06": "Well, let me consider that.",
    "ack_07": "Ah, a moment, please.",
    "ack_08": "Let me gather my thoughts.",
    "ack_09": "Hmm, let me reflect on that.",
    "ack_10": "One moment, if you please.",
    "bridge_01": "If I may add...",
    "bridge_02": "Let me put it this way.",
    "bridge_03": "Yes... let me continue.",
}

oai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
for cid, txt in CLIPS.items():
    mp3 = oai.audio.speech.create(model="tts-1", voice="onyx", input=txt).content
    (OUT / f"{cid}.mp3").write_bytes(mp3)
    print(f"  {cid}: {len(mp3)} bytes  \"{txt}\"")
print(f"wrote {len(CLIPS)} onyx clips to {OUT}  (~${round(sum(len(t) for t in CLIPS.values())*15/1e6,4)})")
