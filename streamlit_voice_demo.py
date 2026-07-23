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
import voice_job              # noqa: E402  (job machinery: filler/rotation/telemetry — $0-tested)

LOG = ROOT / "eval" / "results" / "voice_demo_log.csv"
LOG_COLS = ["timestamp", "mode", "transcript", "stt_seconds", "ttfa_felt_s", "status",
            "tts_chars", "est_cost_usd", "chunk_timings", "mean_gap_ms", "max_gap_ms",
            # [FILLER v5] two-part theme+topic telemetry. neutral_rate_running high =
            # routes landing low-confidence/late; silence_gap_ms = the no-extender cost.
            "theme_used", "route_confidence", "topic_used", "topic_margin", "cache_hit",
            "fallback_used", "silence_gap_ms",
            # [Q2-SEV] queue-state invariant: reserved == submitted + released every turn,
            # backfills > 0 means the watchdog filled a hole (no permanent strict-order stall).
            "queue_reserved", "queue_submitted", "queue_released", "watchdog_backfills",
            # [PHASE-2 FIX] gate inversion + dead-air watchdog + AUDIBLE onset. fire_mode/
            # t_filler_fire_call prove the unconditional fire; deadair_* is the safety net;
            # *_audible_s are the true felt-TTFA (browser playback-start vs confirm) — vs the
            # enqueue-based ttfa_felt_s (H-B). audible_onset_observable=False -> stopwatch.
            "fire_mode", "t_filler_fire_call_s", "deadair_watchdog_fired",
            "t_filler1_audible_s", "t_first_content_audible_s", "audible_onset_observable",
            "chain_pattern", "notes"]
            # chain_pattern e.g. T-C / T-P-C / N-C / T-silence-C
RATES = {"in": 3.00, "cw": 3.75, "cr": 0.30, "out": 15.00}
TTS_PER_MCHAR, STT_PER_MIN = 15.00, 0.006
VOICES = ["onyx", "alloy", "echo", "fable", "nova", "shimmer"]

# [B/C] TTFA filler — two-stage, answer-agnostic, shuffled-deck rotation + telemetry —
# all lives in app/voice_job.py (importable + $0-tested). This wrapper only deals an
# ack from the per-voice deck (filler_decks) and calls voice_job.start_job(...).
# Pool = local Windows-SAPI stand-ins (assets/filler_clips/, gitignored; regenerate with
# scripts/gen_filler_clips.ps1). TODO: re-synth the CJ-authentic pool (filler_pool_PROPOSAL.md)
# with tts-1 (~$0.04) on Dev0's pick, per voice.


@st.cache_resource(show_spinner="Warming the v4 embedder (~30-40s, first launch only)...")
def warm_pipeline():
    embeddings.get_model()
    # Warm a real INFERENCE too, not just the model load: get_model() loads weights but
    # the first embed/route forward pass is the ~1-30s cold hit that blew the 300ms
    # filler-selection budget on Q1 (route_confidence=0.0 -> late_route -> NEUTRAL). One
    # throwaway embed_query + route here means the first REAL question routes warm (~38ms).
    try:
        import retrieval
        retrieval.route("warm")            # embed_query("warm") + centroid route, both warmed
    except Exception:
        pass
    allow = service._allowlist("v4")
    transport = service._resolve_transport()
    client = service._client() if transport == "native_sdk" else None
    # Warm the local STT model too (small/int8/cpu is a ~1-2s CTranslate2
    # load from HF cache) so the FIRST question doesn't pay the cold hit
    # after we flipped STT_BACKEND=local from the bench.
    if (config.STT_BACKEND or "").lower() == "local":
        try:
            _local_stt_model()
        except Exception:
            pass
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
def filler_decks(voice: str) -> dict:
    """[FILLER v5] Per-voice theme+neutral shuffled-deck rotation over the pre-synth
    pool (voice_job.load_theme_pool). One Deck per theme A..E + a NEUTRAL deck; each
    reshuffles when exhausted and resets after 120s idle (new visitor = fresh deck).
    seq_state persists per-topic template decks across turns."""
    pool = voice_job.load_theme_pool(voice)
    theme_decks = {t: voice_job.Deck(pool.get(t, [])) for t in voice_job.filler_route.THEMES}
    theme_decks["NEUTRAL"] = voice_job.Deck(pool.get("NEUTRAL", []))
    return {"theme_decks": theme_decks,
            "seq_state": {"turn": 0, "topic_template_decks": {}}}


@st.cache_resource
def filler_stats() -> dict:
    """[FILLER v5] Aggregate filler telemetry across the session/day: theme-clip usage,
    neutral-fallback rate, topic fire-rate, topic-cache hit-rate."""
    return {"turns": 0, "theme_usage": {}, "neutral_turns": 0,
            "topic_turns": 0, "topic_cache_hits": 0}


def stt_openai(oai, wav_bytes: bytes):
    """Backend-switching STT for the demo wrapper.

    Reads config.STT_BACKEND to pick "openai" (whisper-1 cloud, this fn's
    original behavior) vs "local" (faster-whisper CPU). Return contract is
    unchanged: (text, language_str, seconds). The transcript-confirm
    handshake and downstream filler-firing path are untouched.
    """
    backend = (config.STT_BACKEND or "openai").lower()
    t0 = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes); path = f.name
    try:
        if backend == "local":
            from faster_whisper import WhisperModel  # lazy — first call warms cache
            model = _local_stt_model()
            segments, info = model.transcribe(
                path, beam_size=1, vad_filter=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            lang = f"{info.language} (p={info.language_probability:.2f})"
        else:
            with open(path, "rb") as fh:
                resp = oai.audio.transcriptions.create(model="whisper-1", file=fh,
                                                       response_format="verbose_json")
            text = (getattr(resp, "text", "") or "").strip()
            lang = getattr(resp, "language", "?")
    finally:
        Path(path).unlink(missing_ok=True)
    return text, lang, round(time.perf_counter() - t0, 2)


# Cache the local faster-whisper model at process level; keyed on the demo
# config so a config-driven reload (small->medium during a bench) picks up.
_LOCAL_STT: dict = {"key": None, "model": None}


def _local_stt_model():
    key = (config.LOCAL_STT_MODEL, config.LOCAL_STT_COMPUTE, config.LOCAL_STT_DEVICE)
    if _LOCAL_STT["key"] != key:
        from faster_whisper import WhisperModel
        _LOCAL_STT["model"] = WhisperModel(config.LOCAL_STT_MODEL,
                                           device=config.LOCAL_STT_DEVICE,
                                           compute_type=config.LOCAL_STT_COMPUTE)
        _LOCAL_STT["key"] = key
    return _LOCAL_STT["model"]


def log_row(row: dict) -> None:
    if LOG.exists():   # rotate to a UNIQUE archive if the header changed (the old code
        try:           # renamed to a FIXED name that already existed -> silently no-op'd,
            old_header = open(LOG, encoding="utf-8").readline().strip().split(",")
            if old_header != LOG_COLS:                 # leaving v5 rows under a stale header
                arch = LOG.with_name("voice_demo_log_archived.csv")
                n = 1
                while arch.exists():                   # never clobber; always find a free name
                    arch = LOG.with_name(f"voice_demo_log_archived{n}.csv"); n += 1
                LOG.rename(arch)
        except Exception:
            pass
    new = not LOG.exists()
    with open(LOG, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow(row)


# start_job / synth / two-stage filler machinery now live in app/voice_job.py
# (importable + $0-tested via the stubbed-compose harness). The page below deals
# an ack from the per-voice deck and calls voice_job.start_job(...).

def _audible_onsets(job: dict, aud_by_idx: dict) -> dict:
    """[Task 3] Map the gapless player's browser-reported playback-start (Date.now epoch
    ms) to felt-TTFA seconds from transcript-confirm. Single-machine localhost demo: the
    browser and this host share the system clock, so no cross-clock offset is needed (a
    two-machine setup would need one — not implemented, see the report). Fully guarded:
    any failure -> observable False, never breaks the turn."""
    out = {"t_filler1_audible_s": "", "t_first_content_audible_s": "", "audible_onset_observable": False}
    try:
        if not aud_by_idx or not job.get("wall_epoch"):
            return out
        confirm_ms = datetime.fromisoformat(job["wall_epoch"]).timestamp() * 1000.0
        base = job["base"]
        content_idxs = [c["i"] for c in job["chunks"] if not c.get("clip_id")]
        first_content = min(content_idxs) if content_idxs else None
        if base in aud_by_idx:
            out["t_filler1_audible_s"] = round((aud_by_idx[base] - confirm_ms) / 1000.0, 3)
            out["audible_onset_observable"] = True
        if first_content is not None and first_content in aud_by_idx:
            out["t_first_content_audible_s"] = round((aud_by_idx[first_content] - confirm_ms) / 1000.0, 3)
            out["audible_onset_observable"] = True
    except Exception:
        pass
    return out


def finalize_and_log(job: dict, gaps_by_idx: dict, stats: dict, aud_by_idx: dict | None = None) -> None:
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
    # [FILLER v5] telemetry: theme usage, neutral-fallback + topic fire + cache rates
    stats["turns"] += 1
    if job.get("theme_used"):
        stats["theme_usage"][job["theme_used"]] = stats["theme_usage"].get(job["theme_used"], 0) + 1
    if job.get("fallback_used"):
        stats["neutral_turns"] += 1
    if job.get("topic_used"):
        stats["topic_turns"] += 1
        if job.get("cache_hit"):
            stats["topic_cache_hits"] += 1
    log_row({"timestamp": datetime.now().isoformat(timespec="seconds"), "mode": job["mode"],
             "transcript": job["q"], "stt_seconds": job["stt_s"],
             "ttfa_felt_s": job["first_chunk_ready_s"], "status": job["status"],
             "tts_chars": tts_chars, "est_cost_usd": est, "chunk_timings": packed,
             "mean_gap_ms": round(sum(gaps) / len(gaps), 1) if gaps else "",
             "max_gap_ms": max(gaps) if gaps else "",
             "theme_used": job.get("theme_used") or "", "route_confidence": job.get("route_confidence"),
             "topic_used": job.get("topic_used") or "", "topic_margin": job.get("topic_margin"),
             "cache_hit": job.get("cache_hit"), "fallback_used": job.get("fallback_used"),
             "silence_gap_ms": job.get("silence_gap_ms"),
             "queue_reserved": job.get("queue_reserved"), "queue_submitted": job.get("queue_submitted"),
             "queue_released": job.get("queue_released"),
             "watchdog_backfills": len(job.get("watchdog_backfills") or []),
             "fire_mode": job.get("fire_mode") or "",
             "t_filler_fire_call_s": job.get("t_filler_fire_call"),
             "deadair_watchdog_fired": bool(job.get("deadair_watchdog_fired")),
             **_audible_onsets(job, aud_by_idx or {}),
             "chain_pattern": "-".join(job.get("chain", [])), "notes": ""})
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
        "The embedder warms on boot (one-time ~30–40s at launch), so **question 1 is "
        "ready right away** — a brief spoken opener fires as soon as your question is heard.")

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

# [C] WARM ON BOOT: warm_pipeline() runs unconditionally here (config.WARM_ON_BOOT)
# so the resident embedder + transport are hot before Q1 — no visitor pays the cold load.
if config.WARM_ON_BOOT:
    allow, transport, client = warm_pipeline()
else:
    allow, transport, client = warm_pipeline()   # (flag reserved; demo always warms)
if transport != "native_sdk":
    st.error(f"Transport = {transport}: native TLS broken — fix via docs/RUNBOOK_transport.md.")
oai = openai_client()
gapless = gapless_component()
decks = filler_decks(voice)                      # [B/C] per-voice shuffled-deck rotation
fstats = filler_stats()                          # [C.7] aggregate filler telemetry

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
                    ss.job = voice_job.start_job(text, mode, stt_s, oai, allow, client, voice,
                                                 ss.chunk_base, decks["theme_decks"], decks["seq_state"])
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
        ss.job = voice_job.start_job(q.strip(), mode, ss.pending["stt_s"], oai, allow, client,
                                     voice, ss.chunk_base, decks["theme_decks"], decks["seq_state"])
        ss.pending = None
        ss.mic_key += 1
        st.rerun()

# ---------- live view + PERSISTENT gapless player (stable key -> iframe survives reruns) ----------
job = ss.job
chunks_now = list(job["chunks"]) if job else []
# [Phase 2c] pass the current turn's base index so the player can recover from a mid-session
# remount (expected resets to 0, but the host's indices have climbed) — see index.html.
player_val = gapless(chunks=chunks_now, base=(job["base"] if job else 0),
                     key="gapless_player", default=None)
gaps_by_idx = {p["i"]: p["gap_ms"] for p in (player_val or {}).get("played", [])}
# [Task 3] browser-reported playback-start (Date.now epoch ms) per played chunk
aud_by_idx = {p["i"]: p["t_audible_epoch_ms"] for p in (player_val or {}).get("played", [])
              if isinstance(p, dict) and "t_audible_epoch_ms" in p}

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
            finalize_and_log(job, gaps_by_idx, fstats, aud_by_idx)
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
