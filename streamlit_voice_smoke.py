"""
VOICE SMOKE-TEST — one-click kiosk flow, app.py-style (June 2026 design):

  click the mic (st.audio_input) -> speak -> STOP
    -> inline pipeline fires automatically (md5 hash guard, no confirm button):
       local Whisper STT -> v4 retrieval (deterministic router) -> streamed
       Sonnet compose (directive-ON; ENVELOPE split off, never spoken)
       -> SAPI TTS of the full answer -> browser <audio autoplay> at the end.

Design borrowed from app/app.py (the museum kiosk): inline trigger on new audio
bytes + last_audio_hash guard + mic_key bump + st.rerun + parent-DOM autoplay
(NOT components.html — the iframe loses the user-interaction autoplay grant).
Pipeline and TTS are REUSED modules (retrieval/service/voice_stream) — zero
production changes. Log: eval/results/voice_smoke_log.csv.

Run (human, foreground):  streamlit run streamlit_voice_smoke.py --server.headless false
"""
from __future__ import annotations

import base64
import csv
import hashlib
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
import voice_stream           # noqa: E402  (SapiTTS — reused, not rewritten)

LOG = ROOT / "eval" / "results" / "voice_smoke_log.csv"
LOG_COLS = ["timestamp", "transcript", "detected_lang", "stt_seconds", "compose_seconds",
            "tts_seconds", "stop_to_audio_seconds", "status", "notes"]


# ---------- resident models (once per server, not per question) ----------
@st.cache_resource(show_spinner="Loading Whisper (base, local) — first launch only...")
def get_whisper():
    from faster_whisper import WhisperModel
    return WhisperModel("base", device="cpu", compute_type="int8")


@st.cache_resource(show_spinner="Warming the v4 embedder (~30-40s, first launch only)...")
def warm_pipeline():
    embeddings.get_model()
    allow = service._allowlist("v4")
    transport = service._resolve_transport()
    client = service._client() if transport == "native_sdk" else None
    return allow, transport, client


@st.cache_resource
def get_tts():
    return voice_stream.SapiTTS()


def synth_wav_bytes(tts, text: str) -> tuple[bytes, float]:
    """Full answer -> one WAV via the reused SapiTTS. Returns (bytes, synth_s)."""
    t0 = time.perf_counter()
    path, _ms, _audio_s = tts.synth(text)
    wav = Path(path).read_bytes()
    Path(path).unlink(missing_ok=True)
    return wav, round(time.perf_counter() - t0, 2)


def autoplay_audio(wav_bytes: bytes, autoplay: bool) -> None:
    """app.py pattern: HTML5 audio in the PARENT DOM (st.markdown, not an iframe)
    so the click-interaction autoplay grant applies. Controls always shown."""
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    st.markdown(
        f"<audio {'autoplay ' if autoplay else ''}controls preload='auto' playsinline "
        f"style='width:100%; max-width:560px; display:block; margin:0.6rem auto; "
        f"outline:none; border-radius:8px;' "
        f"src='data:audio/wav;base64,{b64}'></audio>",
        unsafe_allow_html=True,
    )


def log_row(row: dict) -> None:
    new = not LOG.exists()
    with open(LOG, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow(row)


# ---------- page ----------
st.set_page_config(page_title="CJP Voice Smoke Test", page_icon="⚖️", layout="centered")
ss = st.session_state
ss.setdefault("mic_key", 0)            # bump -> fresh recorder next question (app.py pattern)
ss.setdefault("last_audio_hash", "")   # guard: don't re-fire on reruns of the same blob
ss.setdefault("result", None)          # last question's outputs for the READY view
ss.setdefault("autoplay_pending", False)

st.title("⚖️ Ask the Chief Justice — voice smoke test (v4)")
st.caption("Click the mic, speak your question, press **stop** — everything else is automatic: "
           "transcribe → retrieve → compose → the answer is **spoken back** when ready.")
st.info("**Question 1 is slow by design** (Whisper + embedder cold-load, ~40-60s once, plus the "
        "first TLS handshake). Judge feel from question 2 onward.")

allow, transport, client = warm_pipeline()
if transport != "native_sdk":
    st.error(f"Transport = {transport}: native TLS is broken (Avast profile regressed?). "
             "Fix via docs/RUNBOOK_transport.md before judging feel.")
tts = get_tts()
whisper = get_whisper()

audio_in = st.audio_input("🎙️ Press to record, press again to stop",
                          key=f"mic_{ss.mic_key}")

# ---------- inline pipeline trigger (app.py pattern: fire on NEW bytes) ----------
if audio_in is not None:
    wav = audio_in.getvalue()
    if wav and len(wav) > 1024:
        h = hashlib.md5(wav).hexdigest()
        if h != ss.last_audio_hash:
            ss.last_audio_hash = h
            t_stop = time.perf_counter()          # stopwatch: stop-click -> audio ready

            with st.status("🎧 Transcribing (local Whisper)...", expanded=True) as status:
                t0 = time.perf_counter()
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(wav); wav_path = f.name
                segments, info = whisper.transcribe(wav_path, task="transcribe")
                transcript = " ".join(s.text.strip() for s in segments).strip()
                Path(wav_path).unlink(missing_ok=True)
                stt_s = round(time.perf_counter() - t0, 2)
                lang = f"{info.language} (p={info.language_probability:.2f})"
                st.write(f"**Heard:** {transcript}  \n*lang={lang}, {stt_s}s*")

                if not transcript:
                    status.update(label="Heard nothing — try again closer to the mic.",
                                  state="error")
                    st.stop()

                status.update(label="🔎 Retrieving (v4 index, deterministic router)...")
                r = retrieval.run(transcript, allow)
                directives = service._directives(transcript, r["route"])

                status.update(label="✍️ Composing (streamed Sonnet)...")
                t0 = time.perf_counter()
                box = st.empty(); acc = []

                def on_text(piece: str):
                    acc.append(piece)
                    box.markdown("".join(acc) + " ▌")

                comp = service.compose_streamed(transcript, r["retrieval"]["selected"],
                                                directives, client=client, on_text=on_text)
                compose_s = round(time.perf_counter() - t0, 2)
                box.markdown(comp["answer"])

                status.update(label="🔊 Generating the voice (SAPI)...")
                answer_wav, tts_s = synth_wav_bytes(tts, comp["answer"])   # prose only — envelope
                stop_to_audio = round(time.perf_counter() - t_stop, 2)     # never reaches TTS

                cited = (comp["envelope"] or {}).get("doc_ids_cited") or []
                res_status = ("degraded" if comp["degraded"] else
                              "declined" if (not cited and "outside my" in (comp["answer"] or "").lower())
                              else "answered")
                status.update(label=f"✅ Ready ({res_status}) — speaking now", state="complete")

            ss.result = {"transcript": transcript, "lang": lang, "stt_s": stt_s,
                         "answer": comp["answer"], "answer_wav": answer_wav,
                         "compose_s": compose_s, "tts_s": tts_s,
                         "stop_to_audio": stop_to_audio, "status": res_status,
                         "envelope": comp["envelope"], "stop_reason": comp["stop_reason"],
                         "route": {"top_topic": r["route"]["top_topic"],
                                   "cos": r["route"]["top_cosine"]},
                         "llm_pre": r["llm_calls_before_composition"],
                         "chunks_sent": min(len(r["retrieval"]["selected"]), config.COMPOSER_TOP_K)}
            log_row({"timestamp": datetime.now().isoformat(timespec="seconds"),
                     "transcript": transcript, "detected_lang": lang, "stt_seconds": stt_s,
                     "compose_seconds": compose_s, "tts_seconds": tts_s,
                     "stop_to_audio_seconds": stop_to_audio, "status": res_status, "notes": ""})
            ss.autoplay_pending = True
            ss.mic_key += 1                       # fresh recorder for the next question
            st.rerun()

# ---------- READY view (post-pipeline rerun; app.py pattern) ----------
if ss.result:
    res = ss.result
    st.markdown("---")
    st.caption(f"**You asked** ({res['lang']}, STT {res['stt_s']}s — mishears are findings, "
               f"note them in the log): {res['transcript']}")
    st.markdown(res["answer"])
    autoplay_audio(res["answer_wav"], autoplay=ss.autoplay_pending)
    ss.autoplay_pending = False                    # replays only via the button below
    if st.button("🔁 Hear it again"):
        ss.autoplay_pending = True
        st.rerun()
    st.caption(f"stop→audio **{res['stop_to_audio']}s** "
               f"(stt {res['stt_s']} + compose {res['compose_s']} + tts {res['tts_s']}) · "
               f"status **{res['status']}** · chunks sent {res['chunks_sent']} · "
               f"logged to {LOG.relative_to(ROOT)}")
    with st.expander("debug (ENVELOPE + route — never spoken)", expanded=False):
        st.json({"envelope": res["envelope"], "stop_reason": res["stop_reason"],
                 "route": res["route"], "llm_calls_before_composition": res["llm_pre"]})
