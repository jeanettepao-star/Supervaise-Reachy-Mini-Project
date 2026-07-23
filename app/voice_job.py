"""Voice-demo job machinery — EXTRACTED from streamlit_voice_demo.py so it is
importable and $0-testable (no Streamlit imports here).

FILLER v5 — TWO-PART THEME+TOPIC FILLER (extender-free). The sequencer produces:

    THEME clip (or NEUTRAL)  ->  [TOPIC sentence if gated]  ->  content  ->  silence

  * Filler 1 (THEME) is a PRE-SYNTHESIZED clip chosen by the route's theme_anchor
    (assets/filler_clips/<voice>/themes/<A..E>/), or a NEUTRAL clip when the route
    is low-confidence / META / GAP-leaning / late (> FILLER_ROUTE_WAIT_MS).
  * Filler 2 (TOPIC) is RUNTIME-synthesized during theme playback (disk-cached),
    inserted only when all four gates pass (theme gate + clean margin + speakable +
    content-not-yet-buffered). Fast composes skip straight to content.
  * NO extenders, NO lead-in, NO bridges — those v3 layers are RETIRED (clip files
    kept on disk, untouched). Max 2 filler clips per turn by construction.

Content audio always enters at a CLIP BOUNDARY (never mid-clip): the theme clip
takes the base index, the optional topic clip the next, and the first content chunk
is index-gated behind the topic decision so ordering is strict with no holes (R-28).

The v3 role-grammar path (opener/extender/leadin) is preserved in git history; this
module is the v5 replacement. Set config.FILLER_V5_ENABLED=False to degrade to a
NEUTRAL-only opener (safe kill-switch; still extender-free).
"""
from __future__ import annotations

import base64
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config
import filler_route
import retrieval
import service
import voice_stream

# ===================== [PHASE-1 DIAGNOSIS TELEMETRY 2026-07-24 — ADDITIVE, BEHAVIOR-PRESERVING] =====================
# One JSON record per turn, appended to eval/results/filler_v5_trace_2026-07-24.jsonl.
# Every value is read from the job dict (already populated by the sequencer) plus a
# handful of ADDITIVE perf_counter anchors captured in run()/fillers()/_maybe_topic.
# All timestamps share ONE monotonic clock (job["t_confirm"] via time.perf_counter())
# anchored to a single wall-clock epoch (job["wall_epoch"]) recorded once per turn.
# Emission is FULLY wrapped in try/except so a telemetry failure can NEVER alter a
# turn's control flow (boundary rule 5): the try/except is around the EMISSION only,
# never around the code being observed. Disable with CJ_FILLER_TRACE=0.
import datetime as _dt   # noqa: E402
import os as _os         # noqa: E402

_TRACE_ENABLED = _os.environ.get("CJ_FILLER_TRACE", "1") not in ("0", "false", "False", "no")
_TRACE_PATH = _os.environ.get(
    "CJ_FILLER_TRACE_PATH",
    str(config.REPO_ROOT / "eval" / "results" / "filler_v5_trace_2026-07-24.jsonl"))


def _rel(job, t):
    """A perf_counter timestamp -> seconds since transcript-confirm (or None). Guarded."""
    try:
        return None if t is None else round(t - job["t_confirm"], 4)
    except Exception:
        return None


def _emit_trace(job):
    """Append ONE turn's telemetry record. Fully guarded — never raises into run()."""
    if not _TRACE_ENABLED:
        return
    try:
        dec = job.get("filler_decision") or {}
        place = job.get("_place") or {}
        rt = job.get("route") or {}                     # {full ri} on error, {top_topic,cos} on success
        route_topic = rt.get("top_topic") if isinstance(rt, dict) else None
        filler1_fired = bool(job.get("filler_clip_id"))
        filler2_attempted = bool(dec.get("topic_gated"))
        if job.get("topic_used"):                       # filler-2 absent-reason (never silently missing)
            filler2_absent = None
        elif job.get("topic_skipped"):
            filler2_absent = job["topic_skipped"]
        elif dec.get("use_neutral"):
            filler2_absent = f"theme_gate_failed:{dec.get('reason')}"
        elif dec and not filler2_attempted:
            filler2_absent = f"topic_not_gated:{dec.get('reason')}"
        else:
            filler2_absent = "no_decision"
        rec = {
            "turn_id": job.get("turn_id"),
            "wall_clock_epoch": job.get("wall_epoch"),
            "question_index": job.get("question_index"),
            "route_topic": route_topic,
            "route_latency_ms": job.get("route_latency_ms"),
            "router_margin": dec.get("topic_margin"),
            "warm_pipeline_ran": job.get("warm_pipeline_ran"),
            "gate_inputs": {"margin": dec.get("topic_margin"),
                            "content_ready_at_decision": job.get("content_ready_at_decision")},
            "gate_decision": ("bypassed" if job.get("fire_mode") == "unconditional"
                              else None if not dec else "neutral" if dec.get("use_neutral") else "theme"),
            "gate_reason": dec.get("reason"),
            "fire_mode": job.get("fire_mode"),
            "t_filler_fire_call": job.get("t_filler_fire_call"),
            "filler_fire_exception": job.get("filler_fire_exception"),
            "deadair_watchdog_armed": bool(job.get("deadair_watchdog_armed")),
            "deadair_watchdog_fired": bool(job.get("deadair_watchdog_fired")),
            "t_filler1_audible": job.get("t_filler1_audible"),
            "t_first_content_audible": job.get("t_first_content_audible"),
            "audible_onset_observable": bool(job.get("audible_onset_observable")),
            "filler1_fired": filler1_fired,
            "filler1_clip_id": job.get("filler_clip_id"),
            "t_filler1_play_start": _rel(job, place.get("t_first_filler")),   # ENQUEUE ts, NOT audible
            "filler2_attempted": filler2_attempted,
            "filler2_cache_hit": job.get("cache_hit"),
            "filler2_cache_key": job.get("_topic_cache_key"),
            "filler2_synth_ms": job.get("_topic_synth_ms"),
            "t_filler2_play_start": _rel(job, place.get("t_topic")),          # ENQUEUE ts, NOT audible
            "filler2_absent_reason": filler2_absent,
            "t_transcript_confirm": 0.0,                 # the monotonic anchor (all t_* are relative to it)
            "t_compose_request": job.get("_t_compose_request"),
            "t_first_token": job.get("_t_first_token"),
            "t_first_content_chunk_enqueued": _rel(job, place.get("t_first_content")),
            "t_first_content_play_start": None,          # see play_start_observable
            "play_start_observable": bool(job.get("_play_start_observable", False)),
            "compose_path": job.get("_compose_path"),
            "retry_count": job.get("_retry_count"),
            "stt_model_used": job.get("_stt_model_used"),
            "tts_engine_used": job.get("_tts_engine_used"),
            "tts_voice_used": job.get("_tts_voice_used"),
            "tts_model_used": job.get("_tts_model_used"),
            "q2_watchdog_fill_fired": bool(job.get("watchdog_backfills")),
            "ttft_ms": job.get("_t_first_token"),
            "cost_usd_if_available": job.get("_cost_usd"),
            # ---- additive diagnostic context (beyond the mandated field list) ----
            "_chain": "-".join(job.get("chain", [])),
            "_route_confidence": job.get("route_confidence"),
            "_fallback_used": job.get("fallback_used"),
            "_route_got_in_window": job.get("_route_got"),
            "_first_chunk_ready_s": job.get("first_chunk_ready_s"),
            "_silence_gap_ms": job.get("silence_gap_ms"),
            "_status": job.get("status"),
            "_error": job.get("error"),
            "_queue": {"reserved": job.get("queue_reserved"),
                       "submitted": job.get("queue_submitted"),
                       "released": job.get("queue_released"),
                       "backfills": len(job.get("watchdog_backfills") or [])},
            "_stt_reason": job.get("_stt_reason"),
            "_compose_reason": job.get("_compose_reason"),
            "_cost_reason": job.get("_cost_reason"),
            "_embed_device": getattr(config, "EMBED_DEVICE", None),
            "_filler_route_wait_ms": getattr(config, "FILLER_ROUTE_WAIT_MS", None),
        }
        with open(_TRACE_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


# Optional flag a driver (Streamlit wrapper / harness) may set to record whether the
# boot warm-inference actually ran before this turn. None = unknown from inside start_job.
_WARM_RAN = None
# ===================================================================================================================

SESSION_IDLE_RESET_S = 120        # new visitor after 120s idle -> fresh deck
MAX_FILLERS_PER_TURN = 2          # v5: THEME (+ optional TOPIC). No extenders.
FILLER_TTS_SPEED = 1.25           # match the pre-synth theme-clip pace (gen_v5_theme_clips.py)
WATCHDOG_S = 8.0                  # a reserved index MUST resolve within this — hole delays, never stalls
# ~0.08s of 24kHz/16-bit silence — the backfill for a reserved index that never gets
# real audio, so the strict-index-order player advances past a hole instead of stalling
# forever (the Q2 total-silence SEV: a missing `expected` index halts gapless drain).
_SILENT_PCM_B64 = base64.b64encode(b"\x00" * 3840).decode("ascii")

# legacy roles kept only so retired v3 tooling can still import _role_of/load_pool
ROLES = ("opener", "extender", "leadin", "resumption")


def _role_of(stem: str) -> str:
    """[RETIRED v3] Discourse role from a clip filename prefix. Unused by the v5
    sequencer; kept so old scripts importing it don't break."""
    for r in ("extender", "leadin", "resumption"):
        if stem.startswith(r):
            return r
    if "bridge" in stem:
        return "extender"
    return "opener"


def load_pool(voice: str) -> dict:
    """[RETIRED v3] Role-typed flat pool loader. Superseded by load_theme_pool()."""
    def collect(d: Path):
        pool = {r: [] for r in ROLES}
        if not d.is_dir():
            return None
        for p in sorted(list(d.glob("*.mp3")) + list(d.glob("*.wav"))):
            pool[_role_of(p.stem)].append((p.stem, p.read_bytes(), p.suffix[1:].lower()))
        return pool if any(pool.values()) else None
    return (collect(config.FILLER_CLIP_DIR / voice) or collect(config.FILLER_CLIP_DIR)
            or {r: [] for r in ROLES})


# --------------------------------------------------------------------- v5 clip pool
_DURMAP: dict | None = None


def _durmap() -> dict:
    """relative-path -> seconds, from the committed clip-durations manifest."""
    global _DURMAP
    if _DURMAP is None:
        _DURMAP = {}
        p = config.REPO_ROOT / "eval" / "results" / "filler_v5_clip_durations.json"
        if p.exists():
            for c in json.loads(p.read_text(encoding="utf-8")).get("clips", []):
                _DURMAP[c["file"].replace("\\", "/")] = c["seconds"]
    return _DURMAP


def _dur_of(path: Path, default: float = 4.5) -> float:
    rel = str(path.relative_to(config.REPO_ROOT)).replace("\\", "/")
    if rel in _durmap():
        return _durmap()[rel]
    try:                                      # fall back to reading the header
        from mutagen.mp3 import MP3
        return round(MP3(path).info.length, 3)
    except Exception:
        return default


def load_theme_pool(voice: str) -> dict:
    """Per-voice v5 clip pool: {A:[(id,bytes,'mp3',secs)], ..., E:[...], NEUTRAL:[...]}.
    Reads assets/filler_clips/<voice>/themes/<A..E>/*.mp3 + neutral/*.mp3. Empty pool
    for the selected voice -> caller shows a text spinner (never a mismatched voice)."""
    base = config.FILLER_CLIP_DIR / voice
    pool = {t: [] for t in filler_route.THEMES}
    pool["NEUTRAL"] = []
    for theme in filler_route.THEMES:
        d = base / "themes" / theme
        if d.is_dir():
            for p in sorted(d.glob("*.mp3")):
                pool[theme].append((f"theme_{theme}_{p.stem}", p.read_bytes(), "mp3", _dur_of(p)))
    nd = base / "neutral"
    if nd.is_dir():
        for p in sorted(nd.glob("*.mp3")):
            pool["NEUTRAL"].append((f"neutral_{p.stem}", p.read_bytes(), "mp3", _dur_of(p)))
    return pool


# --------------------------------------------------------------------------- deck
class Deck:
    """Shuffled-deck rotation: deal without repeat until exhausted, then reshuffle
    with a no-immediate-repeat guard. Resets on idle (new visitor)."""

    def __init__(self, items: list):
        self.items = list(items)
        self._deck: list = []
        self._last = None
        self._last_deal = 0.0
        self._lock = threading.Lock()
        self._reshuffle()

    def _reshuffle(self):
        self._deck = list(self.items)
        random.shuffle(self._deck)
        if len(self._deck) > 1 and self._deck[0] == self._last:
            self._deck[0], self._deck[1] = self._deck[1], self._deck[0]

    def deal(self):
        with self._lock:
            if not self.items:
                return None
            now = time.perf_counter()
            if self._last_deal and (now - self._last_deal) > SESSION_IDLE_RESET_S:
                self._last = None
                self._reshuffle()
            self._last_deal = now
            if not self._deck:
                self._reshuffle()
            item = self._deck.pop(0)
            self._last = item
            return item


# ------------------------------------------------------------------- topic synth + cache
def _topic_cache_path(voice: str, topic_id: str, template_idx: int) -> Path:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", topic_id).strip("_")
    return config.FILLER_CLIP_DIR / voice / "topics" / f"{safe}__t{template_idx + 1:02d}.mp3"


def synth_topic(oai, voice: str, topic_id: str, template_idx: int, spoken: str):
    """Runtime-synthesize (or disk-cache-hit) the TOPIC sentence. Cache keyed
    (voice, topic_id, template_id). Returns (mp3_bytes, 'mp3', cache_hit, seconds)."""
    path = _topic_cache_path(voice, topic_id, template_idx)
    if path.exists():
        return path.read_bytes(), "mp3", True, _dur_of(path)
    text = filler_route.render_topic(template_idx, spoken)
    mp3 = oai.audio.speech.create(model="tts-1", voice=voice, input=text,
                                  speed=FILLER_TTS_SPEED).content
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(mp3)
    return mp3, "mp3", False, _dur_of(path)


def _topic_template_deck(seq_state: dict, topic_id: str, spoken: str) -> Deck:
    """Per-topic template Deck over the GRAMMAR-ALLOWED template indices (clashing
    template x name pairings dropped per filler_route.grammar_ok). Lazily created,
    persists in seq_state across turns (shuffled, no-repeat, 120s idle reset)."""
    decks = seq_state.setdefault("topic_template_decks", {})
    if topic_id not in decks:
        decks[topic_id] = Deck(filler_route.allowed_templates(spoken))
    return decks[topic_id]


# --------------------------------------------------------------------------- job
def start_job(q, mode, stt_s, oai, allow, client, voice, base_idx,
              theme_decks, seq_state, *, _route_fn=None, _gate_fn=None,
              _retrieve_fn=None, _compose_fn=None):
    """Spawn the background compose+synth pipeline; return the live job dict.

    FILLER v5 SEQUENCER:
      1. At transcript-confirm, wait <= FILLER_ROUTE_WAIT_MS for the route (embed +
         centroid). If it resolves, pick a THEME clip (theme_decks[theme]) via
         filler_route.decide(); else / low-confidence / META / GAP -> a NEUTRAL clip.
      2. If the TOPIC gates pass, synth the topic sentence CONCURRENT with theme
         playback (disk-cached); insert it after the theme clip UNLESS content is
         already ready (gate d) or synth is too slow -> then skip (SILENT).
      3. Content enters at the clip boundary after the fillers; if not ready ->
         SILENCE (no extenders). silence_gap_ms measures that no-extender cost.

    theme_decks: {"A":Deck, "B":Deck, "C":Deck, "D":Deck, "E":Deck, "NEUTRAL":Deck}
      of (clip_id, bytes, fmt, seconds) tuples. seq_state: per-session dict {turn, ...}.
    The _*_fn params override retrieval/service for the $0 stubbed harness."""
    route_fn = _route_fn or retrieval.route
    gate_fn = _gate_fn or retrieval.input_gate
    retrieve_fn = _retrieve_fn or (lambda query, allowl, ri: retrieval.retrieve(query, allowl, route_info=ri))
    compose_fn = _compose_fn or service.compose_streamed
    seq_state["turn"] = seq_state.get("turn", 0) + 1

    job = {"q": q, "mode": mode, "stt_s": stt_s, "acc": "", "chunks": [], "synth_ms": {},
           "done": False, "status": None, "answer": "", "envelope": None, "stop_reason": None,
           "usage": None, "route": None, "llm_pre": None, "chunks_sent": None,
           "t_confirm": time.perf_counter(), "first_chunk_ready_s": None, "error": None,
           "base": base_idx, "n_chunks": 0, "n_fillers": 0, "chain": [],
           # v5 telemetry
           "theme_used": None, "route_confidence": None, "topic_used": None,
           "topic_margin": None, "cache_hit": None, "fallback_used": None,
           "filler_decision": None, "filler_clip_id": None, "filler_fired_ms": None,
           "topic_clip_id": None, "topic_skipped": None, "silence_gap_ms": None,
           "filler_missing_pool": False,
           # Q2-SEV queue state (reserved/submitted/released per turn) + backfills
           "queue_reserved": 0, "queue_submitted": 0, "queue_released": 0,
           "watchdog_backfills": [], "synth_errors": []}

    # ---- [PHASE-1 TELEMETRY] additive anchors (do NOT feed the sequencer; read-only labels) ----
    try:
        _now = _dt.datetime.now()
        job["wall_epoch"] = _now.isoformat(timespec="milliseconds")
        job["turn_id"] = f"{_now.strftime('%Y%m%dT%H%M%S')}-t{seq_state.get('turn')}"
        job["question_index"] = seq_state.get("turn")
        job["warm_pipeline_ran"] = _WARM_RAN
        # tts_*_used: the LITERAL call-site args in synth_mp3/synth_stream (model="tts-1",
        # voice=<voice>); logged whether or not a real TTS call is made this turn.
        job["_tts_engine_used"] = "openai"
        job["_tts_model_used"] = "tts-1"
        job["_tts_voice_used"] = voice
        # stt: runs UPSTREAM in the demo wrapper (whisper-1 | local faster-whisper), never
        # inside start_job. Log the configured call-site model, reason-coded.
        _sttb = (getattr(config, "STT_BACKEND", "openai") or "openai").lower()
        job["_stt_model_used"] = "whisper-1" if _sttb == "openai" else getattr(config, "LOCAL_STT_MODEL", None)
        job["_stt_reason"] = "configured call-site value; STT executes upstream in the demo wrapper, not in start_job"
        # placeholders resolved during run() (null + reason if the path never sets them)
        job["_t_compose_request"] = None
        job["_t_first_token"] = None
        job["_compose_path"] = None
        job["_compose_reason"] = None
        job["_retry_count"] = None
        job["_cost_usd"] = None
        job["_cost_reason"] = None
        job["content_ready_at_decision"] = None
        job["_route_got"] = None
        job["route_latency_ms"] = None
        job["_topic_cache_key"] = None
        job["_topic_synth_ms"] = None
        job["_play_start_observable"] = False   # no audible-play event server-side (enqueue-only)
        # [PHASE-2 FIX] gate-inversion + dead-air watchdog + audible-onset fields
        job["fire_mode"] = None
        job["t_filler_fire_call"] = None
        job["filler_fire_exception"] = None
        job["deadair_watchdog_armed"] = False
        job["deadair_watchdog_fired"] = False
        job["t_filler1_audible"] = None
        job["t_first_content_audible"] = None
        job["audible_onset_observable"] = False
    except Exception:
        pass

    # ---- reservation-tracked index queue (Q2-SEV INVARIANT) ----
    # Every reserved index MUST be resolved: filled with real audio, or released with a
    # silent backfill. A hole can DELAY audio (until the watchdog/error-path backfills)
    # but can NEVER permanently stall the strict-index-order player. reserve() hands out
    # the next index and registers it as unfilled; fill() resolves it idempotently (so a
    # slow synth that lands AFTER a watchdog backfill is dropped, never double-filled).
    res_lock = threading.Lock()
    idx = {"n": base_idx}
    reserved: dict = {}                        # i -> t_reserved (still unfilled)

    def reserve() -> int:
        with res_lock:
            i = idx["n"]; idx["n"] += 1
            reserved[i] = time.perf_counter()
            job["queue_reserved"] += 1
            return i

    def fill(i: int, chunk: dict, released: bool = False) -> bool:
        with res_lock:
            if i not in reserved:              # already resolved (e.g. watchdog backfill)
                return False
            del reserved[i]
            if released:
                job["queue_released"] += 1
            else:
                job["queue_submitted"] += 1
        job["chunks"].append(chunk)
        if job["first_chunk_ready_s"] is None:
            job["first_chunk_ready_s"] = round(time.perf_counter() - job["t_confirm"], 2)
        return True

    def _silence(i: int) -> dict:
        return {"i": i, "b64": _SILENT_PCM_B64, "chars": 0, "fmt": "pcm", "sr": 24000,
                "clip_id": "_backfill"}

    def _push(clip_id, raw: bytes, fmt: str, chars: int = 0) -> int:
        i = reserve()
        fill(i, {"i": i, "b64": base64.b64encode(raw).decode("ascii"),
                 "chars": chars, "fmt": fmt, "clip_id": clip_id})
        return i

    def run():
        try:
            v5 = config.FILLER_V5_ENABLED
            streaming = config.STREAM_TTS_ENABLED
            pool = ThreadPoolExecutor(max_workers=1 if streaming else 3)
            futures = []
            chunker = voice_stream.SentenceChunker()

            route_evt = threading.Event()          # set when route resolves
            theme_placed = threading.Event()        # set after THEME/NEUTRAL clip is placed
            topic_resolved = threading.Event()      # set after TOPIC is placed OR skipped
            first_content = threading.Event()       # set when the 1st content sentence submits
            place = {"filler_secs": 0.0, "t_first_filler": None, "t_first_content": None,
                     "t_topic": None}   # t_topic: [telemetry] topic-clip ENQUEUE ts
            job["_place"] = place       # [telemetry] expose the timing dict to _emit_trace

            job["gate"] = gate_fn(q)

            # ---------- FILLER THREAD: theme (+ maybe topic), racing the route ----------
            def fillers():
                # [TASK 1 — GATE INVERSION] FILLER_FIRE_MODE=unconditional (default): deal a
                # subject-free clip at transcript-confirm with ZERO dependency on route result,
                # router margin, topic cache, or content-readiness. Silence is no longer a
                # reachable gate outcome; the dead-air watchdog is the independent backstop.
                # The legacy gated path (below) is preserved and reachable via FILLER_FIRE_MODE=gated
                # (the demo-week rollback lever). The fire is wrapped so an exception in clip-dealing
                # degrades to the watchdog, never to a crashed turn.
                if getattr(config, "FILLER_FIRE_MODE", "unconditional") == "unconditional":
                    job["fire_mode"] = "unconditional"
                    try:
                        job["t_filler_fire_call"] = round(time.perf_counter() - job["t_confirm"], 4)
                        if job["first_chunk_ready_s"] is None:   # only correct pre-check: audio not already out
                            nd = theme_decks.get("NEUTRAL")
                            clip = nd.deal() if nd else None      # shuffled-deck (no immediate repeat) preserved
                            job["theme_used"] = "NEUTRAL"; job["fallback_used"] = True
                            if clip:
                                _push(clip[0], clip[1], clip[2] if len(clip) > 2 else "mp3")
                                place["t_first_filler"] = time.perf_counter()
                                place["filler_secs"] += clip[3] if len(clip) > 3 else 4.5
                                job["chain"].append("N")
                                job["n_fillers"] += 1
                                job["filler_clip_id"] = clip[0]
                                job["filler_fired_ms"] = round((time.perf_counter() - job["t_confirm"]) * 1000)
                            else:
                                job["filler_missing_pool"] = True   # -> dead-air watchdog backstops
                    except Exception as e:                          # -> dead-air watchdog backstops
                        job["filler_fire_exception"] = type(e).__name__
                        job["synth_errors"].append(f"filler_fire: {type(e).__name__}: {e}")
                    finally:
                        theme_placed.set()
                        topic_resolved.set()                        # unconditional fire is subject-free: no topic
                        job["fillers_done_ts"] = time.perf_counter()
                    return
                # ---------- FILLER_FIRE_MODE=gated: legacy path (preserved, reachable) ----------
                got = route_evt.wait(timeout=config.FILLER_ROUTE_WAIT_MS / 1000.0)
                ri = job.get("route")
                if not v5:
                    dec = {"use_neutral": True, "theme": None, "topic_gated": False,
                           "reason": "v5_disabled", "theme_conf": None, "topic_margin": None}
                elif ri is None:                    # route truly not ready in the window
                    dec = filler_route.decide({"top_topic": None, "top_cosine": 0.0},
                                              job["gate"], late_route=True)
                else:
                    dec = filler_route.decide(ri, job["gate"], late_route=not got)
                job["filler_decision"] = dec
                job["route_confidence"] = dec.get("theme_conf")
                job["topic_margin"] = dec.get("topic_margin")
                try:                                     # [telemetry] additive, guarded
                    job["_route_got"] = got
                    job["content_ready_at_decision"] = first_content.is_set()
                except Exception:
                    pass

                # THEME (or NEUTRAL) clip
                if dec["use_neutral"]:
                    clip = theme_decks.get("NEUTRAL").deal() if theme_decks.get("NEUTRAL") else None
                    job["theme_used"] = "NEUTRAL"; job["fallback_used"] = True
                    tag = "N"
                else:
                    d = theme_decks.get(dec["theme"])
                    clip = d.deal() if d else None
                    job["theme_used"] = dec["theme"]; job["fallback_used"] = False
                    tag = "T"
                if clip:
                    _push(clip[0], clip[1], clip[2] if len(clip) > 2 else "mp3")
                    place["t_first_filler"] = time.perf_counter()
                    place["filler_secs"] += clip[3] if len(clip) > 3 else 4.5
                    job["chain"].append(tag)
                    job["n_fillers"] += 1
                    job["filler_clip_id"] = clip[0]
                    job["filler_fired_ms"] = round((time.perf_counter() - job["t_confirm"]) * 1000)
                else:
                    job["filler_missing_pool"] = True   # -> text spinner, never mismatched voice
                theme_placed.set()

                # TOPIC sentence (Filler 2) — gates a,b,c already in dec.topic_gated
                if dec.get("topic_gated"):
                    _maybe_topic(dec)
                else:
                    topic_resolved.set()
                job["fillers_done_ts"] = time.perf_counter()

            def _maybe_topic(dec):
                # topic_resolved is ALWAYS set (finally) so a topic-synth failure never
                # kills the fillers thread nor blocks content ordering. The topic path
                # reserves no index until _push (reserve+fill atomic) -> no dangling hole.
                try:
                    tdeck = _topic_template_deck(seq_state, dec["topic_id"], dec["topic_spoken"])
                    tidx = tdeck.deal()
                    if tidx is None:
                        return
                    try:                                 # [telemetry] exact filler-2 cache key (guarded)
                        job["_topic_cache_key"] = str(_topic_cache_path(voice, dec["topic_id"], tidx))
                    except Exception:
                        pass
                    _t_topic_synth = time.perf_counter()
                    fut = pool.submit(synth_topic, oai, voice, dec["topic_id"], tidx, dec["topic_spoken"])
                    theme_dur = place["filler_secs"] or 4.5
                    deadline = time.perf_counter() + theme_dur
                    while time.perf_counter() < deadline:
                        if fut.done():
                            break
                        if first_content.is_set():  # gate d: answer already streaming -> don't delay it
                            job["topic_skipped"] = "content_ready_gate_d"; return
                        time.sleep(0.02)
                    if not fut.done():
                        job["topic_skipped"] = "synth_slow"; return
                    audio, fmt, hit, secs = fut.result()    # may raise on synth error
                    if first_content.is_set():      # content beat us to it during synth
                        job["topic_skipped"] = "content_ready_gate_d"; return
                    cid = f"topic_{re.sub(r'[^A-Za-z0-9]+','_',dec['topic_id']).strip('_')}_t{tidx + 1}"
                    _push(cid, audio, fmt)
                    try:                                 # [telemetry] additive, guarded
                        place["t_topic"] = time.perf_counter()
                        job["_topic_synth_ms"] = round((time.perf_counter() - _t_topic_synth) * 1000)
                    except Exception:
                        pass
                    place["filler_secs"] += secs
                    job["chain"].append("P")
                    job["n_fillers"] += 1
                    job["topic_used"] = dec["topic_id"]
                    job["topic_clip_id"] = cid
                    job["cache_hit"] = hit
                except Exception as e:
                    job["topic_skipped"] = f"synth_error:{type(e).__name__}"
                    job["synth_errors"].append(f"topic: {type(e).__name__}: {e}")
                finally:
                    topic_resolved.set()

            threading.Thread(target=fillers, daemon=True).start()

            # ---------- WATCHDOG: enforce the reservation invariant ----------
            def watchdog():
                # Any reserved index still unfilled after WATCHDOG_S is backfilled with
                # silence so the strict-order player advances past it (a hole DELAYS,
                # never PERMANENTLY stalls). On job-done, sweep every leftover at once —
                # no more real chunks are coming, so nothing may stay reserved.
                while not job["done"]:
                    time.sleep(0.5)
                    now = time.perf_counter()
                    with res_lock:
                        stale = [i for i, t in reserved.items() if now - t > WATCHDOG_S]
                    for i in stale:
                        if fill(i, _silence(i), released=True):
                            job["watchdog_backfills"].append(i)
                with res_lock:
                    leftover = list(reserved.keys())
                for i in leftover:
                    if fill(i, _silence(i), released=True):
                        job["watchdog_backfills"].append(i)
            threading.Thread(target=watchdog, daemon=True).start()

            # ---------- DEAD-AIR WATCHDOG (Task 2): silence is never a turn outcome ----------
            def deadair_watchdog():
                # Independent safety net, armed at transcript-confirm, disarmed by the first
                # enqueue of ANY audio (filler or content) or by turn end. If NOTHING is
                # enqueued by t_confirm + DEADAIR_WATCHDOG_MS, force a neutral clip. It lives
                # OUTSIDE the fillers() try-scope, so it fires even if the fire path threw.
                # A FIRED DEAD-AIR WATCHDOG IN PRODUCTION IS A DEFECT SIGNAL TO INVESTIGATE,
                # NOT NORMAL OPERATION — the unconditional fire should always win the race.
                job["deadair_watchdog_armed"] = True
                deadline = job["t_confirm"] + getattr(config, "DEADAIR_WATCHDOG_MS", 800) / 1000.0
                while not job["done"] and time.perf_counter() < deadline:
                    time.sleep(0.02)
                if job["done"]:
                    return                                  # T2.4: disarmed on turn end / cancellation
                # Deal the clip BEFORE taking res_lock: deal() acquires the Deck lock, and the
                # fire path takes Deck-then-res_lock — acquiring them in that same order here
                # avoids an AB/BA deadlock.
                nd = theme_decks.get("NEUTRAL")
                try:
                    clip = nd.deal() if nd else None
                except Exception:
                    clip = None
                with res_lock:                              # T2.3: check-and-fill is ATOMIC -> idempotent
                    if job["first_chunk_ready_s"] is not None or job["done"]:
                        return                              # audio already enqueued -> no-op
                    i = idx["n"]; idx["n"] += 1
                    job["queue_reserved"] += 1; job["queue_submitted"] += 1   # filled atomically; never enters `reserved`
                    if clip:
                        chunk = {"i": i, "b64": base64.b64encode(clip[1]).decode("ascii"),
                                 "chars": 0, "fmt": clip[2] if len(clip) > 2 else "mp3", "clip_id": clip[0]}
                        if job["filler_clip_id"] is None:
                            job["filler_clip_id"] = clip[0]
                    else:                                   # last resort: no clip available -> advance the player
                        chunk = dict(_silence(i)); chunk["clip_id"] = "_deadair_silence"
                    job["chunks"].append(chunk)
                    job["first_chunk_ready_s"] = round(time.perf_counter() - job["t_confirm"], 2)
                    if place["t_first_filler"] is None:
                        place["t_first_filler"] = time.perf_counter()
                    job["deadair_watchdog_fired"] = True
                    job["chain"].append("W")
            threading.Thread(target=deadair_watchdog, daemon=True).start()

            # ---------- content submission (index-gated behind the topic decision) ----------
            def _mark_content():
                if "C" not in job["chain"]:
                    job["chain"].append("C")

            def synth_mp3(i: int, sent: str):
                try:
                    t0 = time.perf_counter()
                    mp3 = oai.audio.speech.create(model="tts-1", voice=voice, input=sent).content
                    job["synth_ms"][i] = round((time.perf_counter() - t0) * 1000)
                    if fill(i, {"i": i, "b64": base64.b64encode(mp3).decode("ascii"),
                                "chars": len(sent), "fmt": "mp3"}):
                        if place["t_first_content"] is None:
                            place["t_first_content"] = time.perf_counter()
                            _record_silence_gap()
                        _mark_content()
                except Exception as e:                    # INVARIANT: never leave a hole
                    job["synth_errors"].append(f"content[{i}]: {type(e).__name__}: {e}")
                    fill(i, _silence(i), released=True)    # backfill so drain advances

            def synth_stream(sent: str):
                t0 = time.perf_counter(); first_i = None
                try:
                    with oai.audio.speech.with_streaming_response.create(
                            model="tts-1", voice=voice, response_format="pcm", input=sent) as resp:
                        for pcm in resp.iter_bytes(chunk_size=4800):
                            if not pcm:
                                continue
                            i = reserve()                 # reserve+fill are paired per chunk
                            first_i = first_i if first_i is not None else i
                            fill(i, {"i": i, "b64": base64.b64encode(pcm).decode("ascii"),
                                     "chars": 0, "fmt": "pcm", "sr": 24000})
                    if first_i is not None:
                        job["synth_ms"][first_i] = round((time.perf_counter() - t0) * 1000)
                        if place["t_first_content"] is None:
                            place["t_first_content"] = time.perf_counter()
                            _record_silence_gap()
                        _mark_content()
                except Exception as e:
                    job["synth_errors"].append(f"stream: {type(e).__name__}: {e}")

            def _record_silence_gap():
                if place["t_first_filler"] is None:
                    return
                content_ready_s = place["t_first_content"] - place["t_first_filler"]
                gap = content_ready_s - place["filler_secs"]
                job["silence_gap_ms"] = round(max(0.0, gap) * 1000)

            def submit(sent: str):
                if not first_content.is_set():
                    first_content.set()
                    # ordering: first content index comes AFTER the topic decision so the
                    # chain is theme -> [topic] -> content with no index hole (R-28).
                    theme_placed.wait(timeout=1.0)
                    topic_resolved.wait(timeout=(place["filler_secs"] or 4.5) + 1.0)
                if streaming:
                    futures.append(pool.submit(synth_stream, sent))
                else:
                    futures.append(pool.submit(synth_mp3, reserve(), sent))

            def on_text(piece: str):
                job["acc"] += piece
                for sent in chunker.feed(piece):
                    submit(sent)

            # ---------- retrieval (route first, signalled early) + compose ----------
            _t_route = time.perf_counter()               # [telemetry] route-latency bracket (call unchanged)
            ri = route_fn(q)
            try:
                job["route_latency_ms"] = round((time.perf_counter() - _t_route) * 1000, 2)
            except Exception:
                pass
            job["route"] = ri
            route_evt.set()
            rr = retrieve_fn(q, allow, ri)
            directives = service._directives(q, ri)
            try:                                         # [telemetry] compose-request anchor
                job["_t_compose_request"] = round(time.perf_counter() - job["t_confirm"], 4)
            except Exception:
                pass
            comp = compose_fn(q, rr["selected"], directives, client=client, on_text=on_text)
            try:                                         # [telemetry] compose result (guarded)
                job["_t_first_token"] = comp.get("ttft_ms")
                job["_compose_path"] = ("degraded" if comp.get("degraded")
                                        else "retried" if comp.get("expanded") else "normal")
                if comp.get("degraded"):
                    job["_compose_reason"] = comp.get("error") or "degraded_fallback"
                if comp.get("usage") is None:
                    job["_cost_reason"] = "no usage object (stubbed compose or curl transport)"
            except Exception:
                pass
            for sent in chunker.flush():
                submit(sent)
            if comp["degraded"] and comp["answer"]:
                submit(comp["answer"])
            for f in futures:
                f.result()
            pool.shutdown(wait=True)
            cited = (comp["envelope"] or {}).get("doc_ids_cited") or []
            job.update(answer=comp["answer"], envelope=comp["envelope"],
                       stop_reason=comp["stop_reason"], usage=comp["usage"],
                       llm_pre=0,
                       chunks_sent=min(len(rr["selected"]), config.COMPOSER_TOP_K),
                       n_chunks=idx["n"] - job["base"],
                       status=("degraded" if comp["degraded"] else
                               "declined" if (not cited and (
                                   "speak to" in (comp["answer"] or "").lower()
                                   or "outside my" in (comp["answer"] or "").lower()))
                               else "answered"))
            job["route"] = {"top_topic": ri["top_topic"], "cos": ri["top_cosine"]}
        except Exception as e:
            job["error"] = f"{type(e).__name__}: {e}"
        finally:
            job["done"] = True
            _emit_trace(job)                             # [telemetry] one record per turn (fully guarded)

    threading.Thread(target=run, daemon=True).start()
    return job
