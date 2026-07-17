"""
DEMO-ONLY VOICE WRAPPER — audience speech -> OpenAI STT -> CURRENT v4 pipeline
(retrieval + streamed Sonnet compose, directive-ON) -> OpenAI TTS spoken aloud.

*** DEMO TOPOLOGY ONLY: cloud STT/TTS for stage polish. The ROBOT topology stays
*** local/offline (Whisper/Piper-class on-device) per the seam design.

GAPLESS PIPELINE (v2 — replaces the two-chunk fallback):
  - PRODUCER/CONSUMER synthesis: compose streams in a BACKGROUND thread; each
    sentence (voice_stream.SentenceChunker, reused) fires its OpenAI TTS request
    THE MOMENT it completes composing (ThreadPool, 3 workers, results indexed —
    chunk N+1 synthesis never waits for chunk N audio).
  - GAPLESS PLAYBACK: components/gapless_audio (custom component, raw Streamlit
    protocol, PERSISTENT iframe across reruns). Chunks arrive over the component
    data channel as base64; a Web Audio AudioContext schedules each buffer to
    start exactly when the previous ends (sample-accurate seam, target <150ms —
    typically ~0ms once buffered). One "Enable audio" click unlocks the
    AudioContext for the whole session (browser autoplay policy).
  - The UI polls via st.rerun (~0.4s) while composing: text streams on screen,
    new chunks flow to the player, per-chunk seam gaps are reported back by JS.

STT: whisper-1 (openai 2.45.0; call pattern lifted from app/voice_io.py — nothing
else from the legacy stack). TTS: tts-1, sidebar voice. ENVELOPE parsed, debug
expander only, NEVER synthesized (chunker stops at the sentinel).

Log: eval/results/voice_demo_log.csv — per-question row incl. packed per-chunk
timings "i:synth_ms/gap_ms;..." proving the seam fix.

Run (human, foreground):  streamlit run streamlit_voice_demo.py --server.headless false
"""
from __future__ import annotations

import base64
import csv
import hashlib
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import streamlit as st
import streamlit.components.v1 as components

import config                 # noqa: E402
import retrieval              # noqa: E402
import service                # noqa: E402
import embeddings             # noqa: E402
import voice_stream           # noqa: E402  (SentenceChunker — reused)

LOG = ROOT / "eval" / "results" / "voice_demo_log.csv"
LOG_COLS = ["timestamp", "mode", "transcript", "stt_seconds", "ttfa_felt_s", "status",
            "tts_chars", "est_cost_usd", "chunk_timings", "mean_gap_ms", "max_gap_ms", "notes"]
RATES = {"in": 3.00, "cw": 3.75, "cr": 0.30, "out": 15.00}
TTS_PER_MCHAR, STT_PER_MIN = 15.00, 0.006
VOICES = ["onyx", "alloy", "echo", "fable", "nova", "shimmer"]

# TTFA filler: a short, neutral, in-character phrase synthesized via OpenAI tts-1
# THE MOMENT the question is confirmed — plays first (chunk = base) so the audience
# hears CJP's voice in ~0.5s while retrieval + Sonnet compose run in the background.
# Generic on purpose (no stance) so it fits answers AND declines. Not shown on
# screen (audio only), never part of the answer text or the envelope.
FILLER_ENABLED = True
FILLERS = [
    "Let me reflect on that for a moment.",
    "A thoughtful question — allow me a moment.",
    "Let me consider that carefully.",
    "Permit me a moment to gather my thoughts.",
]


def _pick_filler(q: str) -> str:
    return FILLERS[sum(ord(c) for c in q) % len(FILLERS)]


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


@st.cache_resource
def gapless_component():
    return components.declare_component("gapless_audio",
                                        path=str(ROOT / "components" / "gapless_audio"))


@st.cache_resource
def filler_cache() -> dict:
    """Persistent {(voice, text): mp3_bytes} across reruns — pre-synthesized TTFA
    fillers so the opening phrase is INSTANT (not a live ~3.6s tts-1 call)."""
    return {}


def prewarm_fillers(oai, voice: str, fcache: dict) -> None:
    """Background pre-synth of every filler for the current voice, so Q1's filler is
    already cached by the time the audience finishes recording. Non-blocking."""
    def w():
        for txt in FILLERS:
            if (voice, txt) not in fcache:
                try:
                    fcache[(voice, txt)] = oai.audio.speech.create(
                        model="tts-1", voice=voice, input=txt).content
                except Exception:
                    pass
    threading.Thread(target=w, daemon=True).start()


def stt_openai(oai, wav_bytes: bytes):
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


def log_row(row: dict) -> None:
    if LOG.exists():   # rotate pre-gapless log if the header changed
        try:
            old_header = open(LOG, encoding="utf-8").readline().strip().split(",")
            if old_header != LOG_COLS:
                LOG.rename(LOG.with_name("voice_demo_log_pre_gapless.csv"))
        except Exception:
            pass
    new = not LOG.exists()
    with open(LOG, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow(row)


def start_job(q: str, mode: str, stt_s: float, oai, allow, client, voice: str, base_idx: int,
              fcache: dict) -> dict:
    """Spawn the background compose+synth pipeline. Returns the live job dict the
    UI polls. NO st.* calls inside the thread."""
    job = {"q": q, "mode": mode, "stt_s": stt_s, "acc": "", "chunks": [], "synth_ms": {},
           "done": False, "status": None, "answer": "", "envelope": None, "stop_reason": None,
           "usage": None, "route": None, "llm_pre": None, "chunks_sent": None,
           "t_confirm": time.perf_counter(), "first_chunk_ready_s": None, "error": None,
           "base": base_idx, "n_chunks": 0}

    def synth(idx: int, sent: str):
        t0 = time.perf_counter()
        mp3 = oai.audio.speech.create(model="tts-1", voice=voice, input=sent).content
        ms = round((time.perf_counter() - t0) * 1000)
        job["synth_ms"][idx] = ms
        job["chunks"].append({"i": idx, "b64": base64.b64encode(mp3).decode("ascii"),
                              "chars": len(sent)})
        if job["first_chunk_ready_s"] is None and idx == job["base"]:
            job["first_chunk_ready_s"] = round(time.perf_counter() - job["t_confirm"], 2)

    def run():
        try:
            pool = ThreadPoolExecutor(max_workers=3)
            futures = []
            chunker = voice_stream.SentenceChunker()      # stops at ENVELOPE sentinel
            idx = {"n": job["base"]}

            def submit(sent: str):
                futures.append(pool.submit(synth, idx["n"], sent)); idx["n"] += 1

            # TTFA FILLER (chunk = base): serve from the pre-synth cache -> INSTANT first
            # audio while retrieval + compose run. Live-synth once if not yet cached.
            # Audio only — never added to acc / answer / envelope.
            if FILLER_ENABLED:
                ftxt = _pick_filler(job["q"]); job["filler"] = ftxt
                fb = fcache.get((voice, ftxt)); cached = fb is not None
                t0 = time.perf_counter()
                if not cached:
                    fb = oai.audio.speech.create(model="tts-1", voice=voice, input=ftxt).content
                    fcache[(voice, ftxt)] = fb
                fi = idx["n"]; idx["n"] += 1
                job["synth_ms"][fi] = 0 if cached else round((time.perf_counter() - t0) * 1000)
                job["chunks"].append({"i": fi, "b64": base64.b64encode(fb).decode("ascii"),
                                      "chars": len(ftxt)})
                job["first_chunk_ready_s"] = round(time.perf_counter() - job["t_confirm"], 2)

            def on_text(piece: str):
                job["acc"] += piece
                for sent in chunker.feed(piece):          # fire TTS the moment a sentence completes
                    submit(sent)

            r = retrieval.run(job["q"], allow)
            directives = service._directives(job["q"], r["route"])
            comp = service.compose_streamed(job["q"], r["retrieval"]["selected"],
                                            directives, client=client, on_text=on_text)
            for sent in chunker.flush():
                submit(sent)
            if comp["degraded"] and comp["answer"]:       # speak the in-voice fallback too
                submit(comp["answer"])
            for f in futures:
                f.result()
            pool.shutdown(wait=True)
            cited = (comp["envelope"] or {}).get("doc_ids_cited") or []
            job.update(answer=comp["answer"], envelope=comp["envelope"],
                       stop_reason=comp["stop_reason"], usage=comp["usage"],
                       route={"top_topic": r["route"]["top_topic"], "cos": r["route"]["top_cosine"]},
                       llm_pre=r["llm_calls_before_composition"],
                       chunks_sent=min(len(r["retrieval"]["selected"]), config.COMPOSER_TOP_K),
                       n_chunks=idx["n"] - job["base"],
                       status=("degraded" if comp["degraded"] else
                               "declined" if (not cited and "speak to" in (comp["answer"] or "").lower()
                                              or not cited and "outside my" in (comp["answer"] or "").lower())
                               else "answered"))
        except Exception as e:                            # surfaced by the poll loop
            job["error"] = f"{type(e).__name__}: {e}"
        finally:
            job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return job


def finalize_and_log(job: dict, gaps_by_idx: dict) -> None:
    u = job["usage"]
    compose_cost = ((getattr(u, "input_tokens", 0) * RATES["in"] +
                     getattr(u, "cache_creation_input_tokens", 0) * RATES["cw"] +
                     getattr(u, "cache_read_input_tokens", 0) * RATES["cr"] +
                     getattr(u, "output_tokens", 0) * RATES["out"]) / 1e6) if u else 0.0
    tts_chars = sum(c["chars"] for c in job["chunks"])
    est = round(compose_cost + tts_chars * TTS_PER_MCHAR / 1e6 + (job["stt_s"] / 60) * STT_PER_MIN, 4)
    idxs = sorted(job["synth_ms"])
    packed = ";".join(f"{i - job['base']}:{job['synth_ms'][i]}/{gaps_by_idx.get(i, '?')}" for i in idxs)
    gaps = [g for i, g in gaps_by_idx.items() if i > job["base"] and isinstance(g, int)]
    log_row({"timestamp": datetime.now().isoformat(timespec="seconds"), "mode": job["mode"],
             "transcript": job["q"], "stt_seconds": job["stt_s"],
             "ttfa_felt_s": job["first_chunk_ready_s"], "status": job["status"],
             "tts_chars": tts_chars, "est_cost_usd": est, "chunk_timings": packed,
             "mean_gap_ms": round(sum(gaps) / len(gaps), 1) if gaps else "",
             "max_gap_ms": max(gaps) if gaps else "", "notes": ""})
    job["logged"] = True
    job["est"] = est
    job["gaps_summary"] = (round(sum(gaps) / len(gaps), 1) if gaps else None,
                           max(gaps) if gaps else None)


# ---------- page ----------
st.set_page_config(page_title="CJP Voice Demo", page_icon="⚖️", layout="centered")
ss = st.session_state
ss.setdefault("mic_key", 0)
ss.setdefault("last_audio_hash", "")
ss.setdefault("pending", None)
ss.setdefault("job", None)
ss.setdefault("chunk_base", 0)      # global chunk index across questions (one player, one queue)

st.title("⚖️ Ask the Chief Justice — voice demo")
st.info("**Click “🔊 Enable audio” once** (browser autoplay rule), then ask by voice. "
        "**Question 1 is slow** (embedder cold-load ~30-40s) — judge from question 2.")

try:
    service._api_key()
except Exception:
    st.error("ANTHROPIC_API_KEY missing (app/.env or environment)."); st.stop()
if not os.environ.get("OPENAI_API_KEY"):
    try:
        from dotenv import load_dotenv
        for p in (ROOT / "app" / ".env", ROOT / ".env"):
            if p.exists():
                load_dotenv(p, override=False)
    except Exception:
        pass
if not os.environ.get("OPENAI_API_KEY"):
    st.error("OPENAI_API_KEY missing (app/.env or environment)."); st.stop()

mode = st.sidebar.radio("Mode", ["TEST (confirm transcript)", "DEMO (auto-submit)"], index=0)
mode = "TEST" if mode.startswith("TEST") else "DEMO"
voice = st.sidebar.selectbox("TTS voice (tts-1)", VOICES, index=0)
st.sidebar.caption("~5-6¢ per question (STT + compose + TTS).")

allow, transport, client = warm_pipeline()
if transport != "native_sdk":
    st.error(f"Transport = {transport}: native TLS broken — fix via docs/RUNBOOK_transport.md.")
oai = openai_client()
gapless = gapless_component()
fcache = filler_cache()
if FILLER_ENABLED and ss.get("fillers_warmed") != voice:
    prewarm_fillers(oai, voice, fcache)          # background pre-synth -> instant filler TTFA
    ss["fillers_warmed"] = voice

job = ss.job
busy = bool(job and not job["done"])

audio_in = st.audio_input("🎙️ Ask the Chief Justice (record, then stop)",
                          key=f"mic_{ss.mic_key}", disabled=busy)

# ---------- inline trigger ----------
if audio_in is not None and not busy:
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
                    ss.job = start_job(text, mode, stt_s, oai, allow, client, voice,
                                       ss.chunk_base, fcache)
                    ss.mic_key += 1
                    st.rerun()
                else:
                    ss.pending = {"text": text, "stt_s": stt_s}
            else:
                st.warning("Heard nothing usable — try again closer to the mic.")

if mode == "TEST" and ss.pending and not busy:
    q = st.text_area("Transcript (edit if misheard — mishears are findings)",
                     ss.pending["text"], height=80)
    if st.button("Ask", type="primary") and q.strip():
        ss.job = start_job(q.strip(), mode, ss.pending["stt_s"], oai, allow, client,
                           voice, ss.chunk_base, fcache)
        ss.pending = None
        ss.mic_key += 1
        st.rerun()

# ---------- live view + PERSISTENT gapless player (stable key -> iframe survives reruns) ----------
job = ss.job
chunks_now = list(job["chunks"]) if job else []
player_val = gapless(chunks=chunks_now, key="gapless_player", default=None)
gaps_by_idx = {p["i"]: p["gap_ms"] for p in (player_val or {}).get("played", [])}

if job:
    st.markdown("---")
    st.caption(f"**You asked:** {job['q']}")
    st.markdown(job["acc"] + (" ▌" if not job["done"] else ""))
    if not job["done"]:
        st.caption(f"composing… {len(chunks_now)} audio chunk(s) synthesized, "
                   f"{len(gaps_by_idx)} playing/played")
        time.sleep(0.4)
        st.rerun()
    else:
        if job.get("error"):
            st.error(job["error"])
        elif not job.get("logged"):
            ss.chunk_base = job["base"] + max(job["n_chunks"], len(job["chunks"]))
            finalize_and_log(job, gaps_by_idx)
        if job.get("logged"):
            mg, xg = job.get("gaps_summary", (None, None))
            st.caption(f"felt-TTFA (confirm→first audio ready): **{job['first_chunk_ready_s']}s** · "
                       f"status **{job['status']}** · chunks {job['n_chunks']} · "
                       f"seam gaps mean/max: **{mg}/{xg} ms** (target <150) · ~${job['est']}/question")
        with st.expander("debug (ENVELOPE + route — never spoken)", expanded=False):
            st.json({"envelope": job["envelope"], "stop_reason": job["stop_reason"],
                     "route": job["route"], "llm_calls_before_composition": job["llm_pre"],
                     "synth_ms_by_chunk": {k - job["base"]: v for k, v in job["synth_ms"].items()},
                     "tts_mode": "pipelined per-sentence + Web Audio gapless scheduling"})
