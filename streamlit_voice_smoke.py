"""
VOICE SMOKE-TEST WRAPPER — mic -> local STT -> CURRENT v4 pipeline -> streamed
Sonnet compose -> sentence-chunked SAPI TTS. A thin, SEPARATE Streamlit app for
a manual feel-test session; the production pipeline/config/apps are untouched.

Chain (all reused, zero pipeline changes):
  st.audio_input -> faster-whisper "base" (local, resident) -> transcript shown +
  EDITABLE + Ask confirm -> retrieval.run (v4 index, deterministic router) ->
  service.compose_streamed (directive-ON, ENVELOPE parsed, never spoken/streamed)
  -> voice_stream.SentenceChunker -> voice_stream.SapiTTS (the proven overlap
  module) -> winsound playback (stdlib; the only added piece — the module synths
  to WAV, playback is what a live session adds).

Run (human, foreground):  streamlit run streamlit_voice_smoke.py --server.headless false
Log: eval/results/voice_smoke_log.csv (one row per question; notes column for the human).
"""
from __future__ import annotations

import csv
import queue
import sys
import tempfile
import threading
import time
import winsound
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
import voice_stream           # noqa: E402  (SentenceChunker + SapiTTS — reused, not rewritten)

LOG = ROOT / "eval" / "results" / "voice_smoke_log.csv"
LOG_COLS = ["timestamp", "transcript", "detected_lang", "stt_seconds", "felt_ttfa_s",
            "status", "notes"]


# ---------- resident models (loaded once per server, not per query) ----------
@st.cache_resource(show_spinner="Loading Whisper (base, local)...")
def get_whisper():
    from faster_whisper import WhisperModel
    return WhisperModel("base", device="cpu", compute_type="int8")


@st.cache_resource(show_spinner="Warming the v4 embedder (~30-40s once)...")
def warm_pipeline():
    embeddings.get_model()                     # resident bge-base on cuda
    allow = service._allowlist("v4")
    transport = service._resolve_transport()
    client = service._client() if transport == "native_sdk" else None
    return allow, transport, client


@st.cache_resource
def get_tts():
    return voice_stream.SapiTTS()


def log_row(row: dict):
    new = not LOG.exists()
    with open(LOG, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow(row)


# ---------- UI ----------
st.set_page_config(page_title="CJP Voice Smoke Test", page_icon="⚖️")
st.title("⚖️ CJP Voice Smoke Test — v4 pipeline")
st.info("**Question 1 is slow by design** — Whisper + the embedder cold-load on first use "
        "(~40-60s combined) and the first API call opens a TLS connection. That is startup, "
        "NOT pipeline latency. Judge feel from question 2 onward.")

allow, transport, client = warm_pipeline()
if transport != "native_sdk":
    st.error(f"Transport = {transport}: native TLS is broken (Avast profile regressed?). "
             "Streaming/TTFA will NOT be representative — fix via docs/RUNBOOK_transport.md "
             "before judging feel.")
tts = get_tts()
whisper = get_whisper()

audio = st.audio_input("Ask the Chief Justice (record, then stop)")

if audio is not None:
    wav_bytes = audio.getvalue()
    key = hash(wav_bytes)
    if st.session_state.get("_last_audio_key") != key:      # transcribe each NEW recording once
        with st.spinner("Transcribing locally (Whisper base)..."):
            t0 = time.perf_counter()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes); wav_path = f.name
            segments, info = whisper.transcribe(wav_path, task="transcribe")
            text = " ".join(s.text.strip() for s in segments).strip()
            st.session_state["_last_audio_key"] = key
            st.session_state["_stt_seconds"] = round(time.perf_counter() - t0, 2)
            st.session_state["_detected_lang"] = f"{info.language} (p={info.language_probability:.2f})"
            st.session_state["_transcript"] = text

if "_transcript" in st.session_state:
    st.caption(f"STT heard (edit if it misheard — mishears are FINDINGS, note them): "
               f"lang={st.session_state['_detected_lang']}, {st.session_state['_stt_seconds']}s")
    q = st.text_area("Transcript (editable)", st.session_state["_transcript"], height=80)
    if st.button("Ask", type="primary") and q.strip():
        t_click = time.perf_counter()
        first_audio = {"t": None}

        # ---- speaker worker: sentences -> SapiTTS.synth (reused) -> winsound play ----
        speak_q: queue.Queue = queue.Queue()

        def speaker():
            while True:
                sent = speak_q.get()
                if sent is None:
                    break
                path, _ms, _s = tts.synth(sent)             # the proven module path
                if first_audio["t"] is None:
                    first_audio["t"] = time.perf_counter()
                winsound.PlaySound(path, winsound.SND_FILENAME)  # blocking = natural sequencing
        th = threading.Thread(target=speaker, daemon=True)
        th.start()

        chunker = voice_stream.SentenceChunker()             # stops at the ENVELOPE sentinel
        box = st.empty()
        acc = []

        def on_text(piece: str):
            acc.append(piece)
            box.markdown("".join(acc) + " ▌")
            for sent in chunker.feed(piece):
                speak_q.put(sent)

        with st.spinner("Retrieving + composing (streamed)..."):
            r = retrieval.run(q, allow)
            directives = service._directives(q, r["route"])
            comp = service.compose_streamed(q, r["retrieval"]["selected"], directives,
                                            client=client, on_text=on_text)
        for sent in chunker.flush():
            speak_q.put(sent)
        speak_q.put(None)
        box.markdown(comp["answer"])                          # final prose (envelope already split off)

        th.join(timeout=180)
        felt = round((first_audio["t"] - t_click), 2) if first_audio["t"] else None
        cited = (comp["envelope"] or {}).get("doc_ids_cited") or []
        status = ("degraded" if comp["degraded"] else
                  "declined" if (not cited and "outside my" in (comp["answer"] or "").lower()) else
                  "answered")
        st.caption(f"felt-TTFA (confirm→first audio): **{felt}s** · status: **{status}** · "
                   f"chunks sent: {min(len(r['retrieval']['selected']), config.COMPOSER_TOP_K)}")
        with st.expander("debug (ENVELOPE + route — never spoken)", expanded=False):
            st.json({"envelope": comp["envelope"], "stop_reason": comp["stop_reason"],
                     "route": {"top_topic": r["route"]["top_topic"],
                               "cos": r["route"]["top_cosine"]},
                     "llm_calls_before_composition": r["llm_calls_before_composition"]})
        log_row({"timestamp": datetime.now().isoformat(timespec="seconds"),
                 "transcript": q, "detected_lang": st.session_state["_detected_lang"],
                 "stt_seconds": st.session_state["_stt_seconds"], "felt_ttfa_s": felt,
                 "status": status, "notes": ""})
        st.caption(f"logged to {LOG.relative_to(ROOT)} — add your 'huh' notes there.")
