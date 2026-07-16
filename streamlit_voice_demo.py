"""
DEMO-ONLY VOICE WRAPPER — audience speech -> OpenAI STT -> CURRENT v4 pipeline
(retrieval + streamed Sonnet compose, directive-ON) -> OpenAI TTS spoken aloud.

*** DEMO TOPOLOGY ONLY: cloud STT/TTS for stage polish. The ROBOT topology stays
*** local/offline (Whisper/Piper-class on-device) per the seam design — this file
*** must never be mistaken for the deployment path.

Salvage note: the OpenAI STT call pattern is lifted from app/voice_io.py
(whisper-1, transcriptions.create) — NOTHING else from the legacy stack is
imported (no Haiku router, no old index). SDK: openai 2.45.0; STT model
whisper-1 (verbose_json for language logging); TTS tts-1.

TTS MODE SHIPPED: TWO-CHUNK. Sentence 1 is synthesized the moment it completes
mid-stream and autoplays immediately; the remainder is synthesized after compose
finishes and is rendered with a server-side delay so it can't start before
clip 1 ends. (Per-sentence multi-clip playback was rejected: Streamlit strips
<script>, so N autoplay clips cannot be reliably sequenced without JS.)

Run (human, foreground):  streamlit run streamlit_voice_demo.py --server.headless false
Log: eval/results/voice_demo_log.csv
"""
from __future__ import annotations

import base64
import csv
import hashlib
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import streamlit as st

import config                 # noqa: E402
import retrieval              # noqa: E402
import service                # noqa: E402
import embeddings             # noqa: E402
import voice_stream           # noqa: E402  (SentenceChunker — reused)

LOG = ROOT / "eval" / "results" / "voice_demo_log.csv"
LOG_COLS = ["timestamp", "mode", "transcript", "stt_seconds", "ttfa_felt_s",
            "status", "tts_chars", "est_cost_usd", "notes"]
RATES = {"in": 3.00, "cw": 3.75, "cr": 0.30, "out": 15.00}   # $/MTok (Sonnet)
TTS_PER_MCHAR, STT_PER_MIN = 15.00, 0.006
VOICES = ["onyx", "alloy", "echo", "fable", "nova", "shimmer"]
SPEECH_CHARS_PER_S = 15.0     # rough spoken-rate estimate for the clip-2 delay


# ---------- residents ----------
@st.cache_resource(show_spinner="Warming the v4 embedder (~30-40s, first launch only)...")
def warm_pipeline():
    embeddings.get_model()
    allow = service._allowlist("v4")
    transport = service._resolve_transport()
    client = service._client() if transport == "native_sdk" else None
    return allow, transport, client


@st.cache_resource
def openai_client():
    from openai import OpenAI
    return OpenAI()


def stt_openai(oai, wav_bytes: bytes) -> tuple[str, str, float]:
    """whisper-1 (lifted call pattern from voice_io.transcribe_openai; verbose_json
    so the detected language is loggable). Returns (text, lang, seconds)."""
    t0 = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes); path = f.name
    try:
        with open(path, "rb") as fh:
            resp = oai.audio.transcriptions.create(model="whisper-1", file=fh,
                                                   response_format="verbose_json")
    finally:
        Path(path).unlink(missing_ok=True)
    return (getattr(resp, "text", "") or "").strip(), getattr(resp, "language", "?"), \
        round(time.perf_counter() - t0, 2)


def tts_openai(oai, text: str, voice: str) -> bytes:
    resp = oai.audio.speech.create(model="tts-1", voice=voice, input=text)
    return resp.content


def audio_tag(mp3: bytes, autoplay: bool) -> str:
    b64 = base64.b64encode(mp3).decode("ascii")
    return (f"<audio {'autoplay ' if autoplay else ''}controls preload='auto' playsinline "
            f"style='width:100%; max-width:560px; display:block; margin:0.4rem auto; "
            f"border-radius:8px;' src='data:audio/mp3;base64,{b64}'></audio>")


def log_row(row: dict) -> None:
    new = not LOG.exists()
    with open(LOG, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow(row)


def run_question(q: str, mode: str, stt_s: float, oai, allow, client, voice: str):
    """Confirmed/auto transcript -> v4 retrieval -> streamed compose -> two-chunk TTS."""
    t_confirm = time.perf_counter()
    r = retrieval.run(q, allow)
    directives = service._directives(q, r["route"])
    chunker = voice_stream.SentenceChunker()          # reused; stops at ENVELOPE sentinel
    text_box, clip1_box, clip2_box = st.empty(), st.empty(), st.empty()
    acc, state = [], {"s1": None, "ttfa": None, "clip1_started": None}

    def on_text(piece: str):
        acc.append(piece)
        text_box.markdown("".join(acc) + " ▌")
        if state["s1"] is None:
            for sent in chunker.feed(piece):          # first COMPLETE sentence -> speak now
                if state["s1"] is None:
                    state["s1"] = sent
                    mp3 = tts_openai(oai, sent, voice)
                    clip1_box.markdown(audio_tag(mp3, autoplay=True), unsafe_allow_html=True)
                    state["ttfa"] = round(time.perf_counter() - t_confirm, 2)
                    state["clip1_started"] = time.perf_counter()

    with st.spinner("Composing (streamed)..."):
        comp = service.compose_streamed(q, r["retrieval"]["selected"], directives,
                                        client=client, on_text=on_text)
    answer = comp["answer"]
    text_box.markdown(answer)

    tts_chars = 0
    if not comp["degraded"] and answer:
        s1 = state["s1"] or answer
        idx = answer.find(s1)
        remainder = answer[idx + len(s1):].strip() if idx >= 0 else ""
        if state["s1"] is None:                       # stream never completed a sentence
            mp3 = tts_openai(oai, answer, voice)
            clip1_box.markdown(audio_tag(mp3, autoplay=True), unsafe_allow_html=True)
            state["ttfa"] = round(time.perf_counter() - t_confirm, 2)
            tts_chars = len(answer)
        elif remainder:
            mp3_2 = tts_openai(oai, remainder, voice)  # synthesized while clip 1 plays
            # don't start clip 2 before clip 1 finishes (no JS allowed -> server-side delay)
            s1_dur = len(s1) / SPEECH_CHARS_PER_S
            elapsed = time.perf_counter() - state["clip1_started"]
            if elapsed < s1_dur:
                time.sleep(s1_dur - elapsed)
            clip2_box.markdown(audio_tag(mp3_2, autoplay=True), unsafe_allow_html=True)
            tts_chars = len(s1) + len(remainder)
        else:
            tts_chars = len(s1)

    cited = (comp["envelope"] or {}).get("doc_ids_cited") or []
    status = ("degraded" if comp["degraded"] else
              "declined" if (not cited and "outside my" in (answer or "").lower()) else "answered")
    u = comp["usage"]
    compose_cost = ((getattr(u, "input_tokens", 0) * RATES["in"] +
                     getattr(u, "cache_creation_input_tokens", 0) * RATES["cw"] +
                     getattr(u, "cache_read_input_tokens", 0) * RATES["cr"] +
                     getattr(u, "output_tokens", 0) * RATES["out"]) / 1e6) if u else 0.0
    est = round(compose_cost + tts_chars * TTS_PER_MCHAR / 1e6 + (stt_s / 60) * STT_PER_MIN, 4)

    st.caption(f"felt-TTFA (confirm→first audio): **{state['ttfa']}s** · status **{status}** · "
               f"~${est}/question · chunks sent "
               f"{min(len(r['retrieval']['selected']), config.COMPOSER_TOP_K)}")
    with st.expander("debug (ENVELOPE + route — never spoken)", expanded=False):
        st.json({"envelope": comp["envelope"], "stop_reason": comp["stop_reason"],
                 "route": {"top_topic": r["route"]["top_topic"], "cos": r["route"]["top_cosine"]},
                 "llm_calls_before_composition": r["llm_calls_before_composition"],
                 "tts_mode": "two-chunk (per-sentence rejected: no JS sequencing in Streamlit)"})
    log_row({"timestamp": datetime.now().isoformat(timespec="seconds"), "mode": mode,
             "transcript": q, "stt_seconds": stt_s, "ttfa_felt_s": state["ttfa"],
             "status": status, "tts_chars": tts_chars, "est_cost_usd": est, "notes": ""})


# ---------- page ----------
st.set_page_config(page_title="CJP Voice Demo", page_icon="⚖️", layout="centered")
ss = st.session_state
ss.setdefault("mic_key", 0)
ss.setdefault("last_audio_hash", "")
ss.setdefault("pending", None)          # TEST mode: transcript awaiting confirm

st.title("⚖️ Ask the Chief Justice — voice demo")
st.info("**Question 1 is slow** (embedder cold-load ~30-40s + first TLS handshake) — judge from "
        "question 2 onward.")

# keys asserted up front, loud on-screen errors
try:
    service._api_key()
except Exception:
    st.error("ANTHROPIC_API_KEY missing (app/.env or environment). The composer cannot run."); st.stop()
if not os.environ.get("OPENAI_API_KEY"):
    try:
        from dotenv import load_dotenv
        for p in (ROOT / "app" / ".env", ROOT / ".env"):
            if p.exists():
                load_dotenv(p, override=False)
    except Exception:
        pass
if not os.environ.get("OPENAI_API_KEY"):
    st.error("OPENAI_API_KEY missing (app/.env or environment). STT/TTS cannot run."); st.stop()

mode = st.sidebar.radio("Mode", ["TEST (confirm transcript)", "DEMO (auto-submit)"], index=0)
mode = "TEST" if mode.startswith("TEST") else "DEMO"
voice = st.sidebar.selectbox("TTS voice (tts-1)", VOICES, index=0)
st.sidebar.caption("~5-6¢ per question (STT + compose + TTS).")

allow, transport, client = warm_pipeline()
if transport != "native_sdk":
    st.error(f"Transport = {transport}: native TLS broken — fix via docs/RUNBOOK_transport.md "
             "before the demo.")
oai = openai_client()

audio_in = st.audio_input("🎙️ Ask the Chief Justice (record, then stop)", key=f"mic_{ss.mic_key}")

if audio_in is not None:
    wav = audio_in.getvalue()
    if wav and len(wav) > 1024:
        h = hashlib.md5(wav).hexdigest()
        if h != ss.last_audio_hash:
            ss.last_audio_hash = h
            with st.spinner("Transcribing (OpenAI whisper-1)..."):
                text, lang, stt_s = stt_openai(oai, wav)
            st.caption(f"STT heard (lang={lang}, {stt_s}s): **{text or '(nothing)'}**")
            if text:
                if mode == "DEMO":
                    run_question(text, mode, stt_s, oai, allow, client, voice)
                    ss.mic_key += 1               # fresh recorder; answer stays on screen
                else:
                    ss.pending = {"text": text, "stt_s": stt_s, "lang": lang}
            else:
                st.warning("Heard nothing usable — try again closer to the mic.")

if mode == "TEST" and ss.pending:
    q = st.text_area("Transcript (edit if misheard — mishears are findings)",
                     ss.pending["text"], height=80)
    if st.button("Ask", type="primary") and q.strip():
        run_question(q.strip(), mode, ss.pending["stt_s"], oai, allow, client, voice)
        ss.pending = None
        ss.mic_key += 1
