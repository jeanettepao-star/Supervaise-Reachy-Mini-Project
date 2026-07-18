"""Voice-demo job machinery — EXTRACTED from streamlit_voice_demo.py so it is
importable and $0-testable (no Streamlit imports here). Owns:
  - the two-stage TTFA filler (stage-1 ack at transcript-confirm, stage-2 bridge(s)
    only if content isn't ready), with SHUFFLED-DECK rotation + session reset;
  - per-sentence TTS (mp3 default / streamed-PCM held behind config.STREAM_TTS_ENABLED);
  - telemetry (filler_clip_id, filler_fired_ms, stage2_fired, ...).
The stage-1 ack is injected at the TOP of run() — i.e. the instant start_job() is
called (transcript-confirm), BEFORE retrieval/compose — never at stream-start.
"""
from __future__ import annotations

import base64
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config
import retrieval
import service
import voice_stream

FILLER_ACK_SECONDS = 1.4          # measured onyx ack median 1.45s (was 2.6 SAPI estimate)
SESSION_IDLE_RESET_S = 120        # new visitor after 120s idle -> fresh deck
MAX_FILLERS_PER_TURN = 3          # long-transient rule: ack + up to 2 bridges, then accept silence


# --------------------------------------------------------------------------- pool
ROLES = ("opener", "extender", "leadin", "resumption")


def _role_of(stem: str) -> str:
    """Discourse role from the clip's filename prefix. opener = pre-speech only;
    extender = extends the THINKING state (no implied speech); leadin = seasons the
    hand-off to content (only when content is buffered); resumption = implies prior
    speech (retired from stage-2; reserved for future barge-in resume)."""
    for r in ("extender", "leadin", "resumption"):
        if stem.startswith(r):
            return r
    if "bridge" in stem:            # legacy SAPI/onyx bridge -> treat as extender
        return "extender"
    return "opener"                 # ack_* / opener_*


def load_pool(voice: str) -> dict:
    """Per-voice ROLE-TYPED clip pool. Looks in config.FILLER_CLIP_DIR/<voice>/ first,
    then the flat dir. Returns {opener:[(id,bytes,fmt)], extender:[...], leadin:[...],
    resumption:[...]}. Empty -> caller shows a text spinner, never a mismatched voice."""
    def collect(d: Path):
        pool = {r: [] for r in ROLES}
        if not d.is_dir():
            return None
        for p in sorted(list(d.glob("*.mp3")) + list(d.glob("*.wav"))):
            pool[_role_of(p.stem)].append((p.stem, p.read_bytes(), p.suffix[1:].lower()))
        return pool if any(pool.values()) else None
    return (collect(config.FILLER_CLIP_DIR / voice) or collect(config.FILLER_CLIP_DIR)
            or {r: [] for r in ROLES})


# --------------------------------------------------------------------------- deck
class Deck:
    """Shuffled-deck rotation: deal without repeat until the deck exhausts, then
    reshuffle with a no-immediate-repeat guard. Resets on idle (new visitor)."""

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
        if len(self._deck) > 1 and self._deck[0] == self._last:   # no immediate repeat across shuffles
            self._deck[0], self._deck[1] = self._deck[1], self._deck[0]

    def deal(self):
        with self._lock:
            if not self.items:
                return None
            now = time.perf_counter()
            if self._last_deal and (now - self._last_deal) > SESSION_IDLE_RESET_S:
                self._last = None
                self._reshuffle()                                 # fresh deck for a new visitor
            self._last_deal = now
            if not self._deck:
                self._reshuffle()
            item = self._deck.pop(0)
            self._last = item
            return item                                           # (id, bytes)


# --------------------------------------------------------------------------- job
def start_job(q, mode, stt_s, oai, allow, client, voice, base_idx,
              opener, extender_deck, leadin_clip, seq_state, *, _compose_fn=None, _retrieve_fn=None):
    """Spawn the background compose+synth pipeline; return the live job dict.
    Discourse-role SEQUENCER (Filler v3):
      pos 1     = `opener` (id,bytes,fmt) — pre-speech acknowledgment, fires at confirm;
      pos 2..N  = `extender_deck` (Deck of extenders) — extend the THINKING state while
                  content isn't buffered; per-turn no-repeat; cap MAX_FILLERS_PER_TURN then silence;
      leadin    = `leadin_clip` — plays ONLY when the first content AUDIO is already buffered
                  (~30% of eligible turns, never consecutive turns, never unbuffered).
    Only these chains are possible: O-C, O-E-C, O-E-E-C, O-[E]-L-C.
    `seq_state` = session dict {turn, last_leadin_turn} for the no-consecutive-leadin rule.
    `_compose_fn`/`_retrieve_fn` override service.* for the $0 stubbed-compose harness."""
    compose_fn = _compose_fn or service.compose_streamed
    retrieve_fn = _retrieve_fn or retrieval.run
    seq_state["turn"] = seq_state.get("turn", 0) + 1
    job = {"q": q, "mode": mode, "stt_s": stt_s, "acc": "", "chunks": [], "synth_ms": {},
           "done": False, "status": None, "answer": "", "envelope": None, "stop_reason": None,
           "usage": None, "route": None, "llm_pre": None, "chunks_sent": None,
           "t_confirm": time.perf_counter(), "first_chunk_ready_s": None, "error": None,
           "base": base_idx, "n_chunks": 0,
           # telemetry
           "filler_clip_id": None, "filler_fired_ms": None, "stage2_fired": False,
           "stage2_clip_ids": [], "n_fillers": 0, "chain": [], "leadin_fired": False}

    ilock = threading.Lock()
    idx = {"n": base_idx}
    def next_idx() -> int:
        with ilock:
            i = idx["n"]; idx["n"] += 1; return i

    def push_clip(clip_id: str, raw: bytes, fmt: str = "wav") -> int:
        i = next_idx()
        job["chunks"].append({"i": i, "b64": base64.b64encode(raw).decode("ascii"),
                              "chars": 0, "fmt": fmt, "clip_id": clip_id})
        job["n_fillers"] += 1
        if job["first_chunk_ready_s"] is None:
            job["first_chunk_ready_s"] = round(time.perf_counter() - job["t_confirm"], 2)
        return i

    def _mark_content():
        if "C" not in job["chain"]:
            job["chain"].append("C")

    def _content_buffered() -> bool:
        return any(not c.get("clip_id") for c in job["chunks"])   # a content chunk's AUDIO is present

    def synth_mp3(i: int, sent: str):
        t0 = time.perf_counter()
        mp3 = oai.audio.speech.create(model="tts-1", voice=voice, input=sent).content
        job["synth_ms"][i] = round((time.perf_counter() - t0) * 1000)
        job["chunks"].append({"i": i, "b64": base64.b64encode(mp3).decode("ascii"),
                              "chars": len(sent), "fmt": "mp3"})
        _mark_content()

    def synth_stream(sent: str):
        """[HELD ~$0.02] tts-1 streamed PCM (24kHz/16-bit); sub-chunks take consecutive
        global indices, single-worker -> strict order (R-28 guard)."""
        t0 = time.perf_counter(); first_i = None
        with oai.audio.speech.with_streaming_response.create(
                model="tts-1", voice=voice, response_format="pcm", input=sent) as resp:
            for pcm in resp.iter_bytes(chunk_size=4800):
                if not pcm:
                    continue
                i = next_idx()
                first_i = first_i if first_i is not None else i
                job["chunks"].append({"i": i, "b64": base64.b64encode(pcm).decode("ascii"),
                                      "chars": 0, "fmt": "pcm", "sr": 24000})
        if first_i is not None:
            job["synth_ms"][first_i] = round((time.perf_counter() - t0) * 1000)
            _mark_content()

    def run():
        try:
            streaming = config.STREAM_TTS_ENABLED
            pool = ThreadPoolExecutor(max_workers=1 if streaming else 3)
            futures = []
            chunker = voice_stream.SentenceChunker()
            first_content = threading.Event()

            def _maybe_leadin():
                # LEADIN plays BEFORE content: pushed at first-content submit, so its index
                # precedes content's. Only when STREAMING (first audio ~sub-second, so content
                # is buffered before the ~1.2s leadin ends -> the no-gap promise is kept). With
                # non-streaming tts-1 (~3s synth) a leadin would gap, so it stays dormant.
                if (leadin_clip and config.STREAM_TTS_ENABLED
                        and job["n_fillers"] < MAX_FILLERS_PER_TURN
                        and random.random() < 0.30
                        and seq_state.get("last_leadin_turn") != seq_state["turn"] - 1):  # not consecutive
                    push_clip(leadin_clip[0], leadin_clip[1],
                              fmt=leadin_clip[2] if len(leadin_clip) > 2 else "wav")
                    job["leadin_fired"] = True
                    job["chain"].append("L")
                    seq_state["last_leadin_turn"] = seq_state["turn"]

            def submit(sent: str):
                if not first_content.is_set():
                    first_content.set()
                    _maybe_leadin()                       # optional leadin, BEFORE content is queued
                if streaming:
                    futures.append(pool.submit(synth_stream, sent))
                else:
                    futures.append(pool.submit(synth_mp3, next_idx(), sent))

            # POSITION 1 — OPENER, at transcript-confirm (before retrieval/compose).
            if opener:
                push_clip(opener[0], opener[1], fmt=opener[2] if len(opener) > 2 else "wav")
                job["filler_clip_id"] = opener[0]
                job["filler_fired_ms"] = round((time.perf_counter() - job["t_confirm"]) * 1000)
                job["chain"].append("O")

                def sequencer():
                    """POS 2..N: play EXTENDERS while the first content sentence isn't yet in
                    flight; stop the instant it submits (any leadin fires there, before content).
                    Per-turn no-repeat; cap MAX_FILLERS_PER_TURN then accept silence. Only chains:
                    O-C / O-E-C / O-E-E-C / O-[E]-L-C (no resumption pre-speech, no post-content clip)."""
                    used = set()
                    while job["n_fillers"] < MAX_FILLERS_PER_TURN and not job["done"]:
                        if first_content.wait(timeout=FILLER_ACK_SECONDS):
                            return                                # content in flight -> stop extending
                        e = extender_deck.deal() if extender_deck else None
                        if not e or e[0] in used or job["n_fillers"] >= MAX_FILLERS_PER_TURN:
                            return                                # no fresh extender / cap -> accept silence
                        used.add(e[0])
                        push_clip(e[0], e[1], fmt=e[2] if len(e) > 2 else "wav")
                        job["stage2_fired"] = True
                        job["stage2_clip_ids"].append(e[0])
                        job["chain"].append("E")
                threading.Thread(target=sequencer, daemon=True).start()

            def on_text(piece: str):
                job["acc"] += piece
                for sent in chunker.feed(piece):
                    submit(sent)

            r = retrieve_fn(job["q"], allow)
            directives = service._directives(job["q"], r["route"])
            comp = compose_fn(job["q"], r["retrieval"]["selected"], directives,
                              client=client, on_text=on_text)
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
                       route={"top_topic": r["route"]["top_topic"], "cos": r["route"]["top_cosine"]},
                       llm_pre=r["llm_calls_before_composition"],
                       chunks_sent=min(len(r["retrieval"]["selected"]), config.COMPOSER_TOP_K),
                       n_chunks=idx["n"] - job["base"],
                       status=("degraded" if comp["degraded"] else
                               "declined" if (not cited and (
                                   "speak to" in (comp["answer"] or "").lower()
                                   or "outside my" in (comp["answer"] or "").lower()))
                               else "answered"))
        except Exception as e:
            job["error"] = f"{type(e).__name__}: {e}"
        finally:
            job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return job
