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
CLIPS = {  # id -> text. Role from prefix (voice_job._role_of): opener/extender/leadin/resumption.
    # OPENERS (position 1, pre-speech acknowledgment) — ack_* is treated as opener.
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
    # EXTENDERS (position 2..N, extend the THINKING state — never imply speech happened).
    "extender_01": "A moment more, please.",
    "extender_02": "Bear with me, I want to answer this properly.",
    "extender_03": "Let me be sure I have this right.",
    # LEADIN (hand-off to content; only when content is buffered/streaming — see voice_job).
    "leadin_01": "Let me put it this way.",
    # RESUMPTION (imply prior speech — retired from stage-2; reserved for future barge-in resume).
    "resumption_01": "If I may add...",
    "resumption_02": "Yes... let me continue.",
}

oai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
for cid, txt in CLIPS.items():
    mp3 = oai.audio.speech.create(model="tts-1", voice="onyx", input=txt).content
    (OUT / f"{cid}.mp3").write_bytes(mp3)
    print(f"  {cid}: {len(mp3)} bytes  \"{txt}\"")
print(f"wrote {len(CLIPS)} onyx clips to {OUT}  (~${round(sum(len(t) for t in CLIPS.values())*15/1e6,4)})")
