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
def load_pool(voice: str) -> dict:
    """Per-voice clip pool. Looks in config.FILLER_CLIP_DIR/<voice>/ first, then the
    flat dir (voice-agnostic SAPI stand-ins). Returns {'ack': [(id, bytes)],
    'bridge': [(id, bytes)]}. Empty -> the caller shows a text spinner, never a
    mismatched voice."""
    def collect(d: Path) -> dict:
        acks, bridges = [], []
        if not d.is_dir():
            return {}
        for p in sorted(list(d.glob("*.mp3")) + list(d.glob("*.wav"))):  # tts-1 mp3 or SAPI wav
            clip = (p.stem, p.read_bytes(), p.suffix[1:].lower())         # (id, bytes, fmt)
            (bridges if "bridge" in p.stem else acks).append(clip)
        return {"ack": acks, "bridge": bridges} if (acks or bridges) else {}
    per_voice = collect(config.FILLER_CLIP_DIR / voice)
    if per_voice:
        return per_voice
    return collect(config.FILLER_CLIP_DIR) or {"ack": [], "bridge": []}


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
              ack, bridge_deck, *, _compose_fn=None, _retrieve_fn=None):
    """Spawn the background compose+synth pipeline; return the live job dict.
    `ack` = (clip_id, wav_bytes) or None; `bridge_deck` = a Deck of bridge clips.
    `_compose_fn`/`_retrieve_fn` override service.compose_streamed / retrieval.run
    (for the $0 stubbed-compose harness). NO UI calls here."""
    compose_fn = _compose_fn or service.compose_streamed
    retrieve_fn = _retrieve_fn or retrieval.run
    job = {"q": q, "mode": mode, "stt_s": stt_s, "acc": "", "chunks": [], "synth_ms": {},
           "done": False, "status": None, "answer": "", "envelope": None, "stop_reason": None,
           "usage": None, "route": None, "llm_pre": None, "chunks_sent": None,
           "t_confirm": time.perf_counter(), "first_chunk_ready_s": None, "error": None,
           "base": base_idx, "n_chunks": 0,
           # telemetry
           "filler_clip_id": None, "filler_fired_ms": None, "stage2_fired": False,
           "stage2_clip_ids": [], "n_fillers": 0}

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

    def synth_mp3(i: int, sent: str):
        t0 = time.perf_counter()
        mp3 = oai.audio.speech.create(model="tts-1", voice=voice, input=sent).content
        job["synth_ms"][i] = round((time.perf_counter() - t0) * 1000)
        job["chunks"].append({"i": i, "b64": base64.b64encode(mp3).decode("ascii"),
                              "chars": len(sent), "fmt": "mp3"})

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

    def run():
        try:
            streaming = config.STREAM_TTS_ENABLED
            pool = ThreadPoolExecutor(max_workers=1 if streaming else 3)
            futures = []
            chunker = voice_stream.SentenceChunker()
            first_content = threading.Event()

            def submit(sent: str):
                first_content.set()
                if streaming:
                    futures.append(pool.submit(synth_stream, sent))
                else:
                    futures.append(pool.submit(synth_mp3, next_idx(), sent))

            # STAGE-1 ACK — fires HERE, at transcript-confirm (before retrieval/compose).
            if ack:
                push_clip(ack[0], ack[1], fmt=ack[2] if len(ack) > 2 else "wav")
                job["filler_clip_id"] = ack[0]
                job["filler_fired_ms"] = round((time.perf_counter() - job["t_confirm"]) * 1000)

                def bridge_monitor():
                    # STAGE-2 (and beyond): while content isn't ready and we're under
                    # the long-transient cap, keep filling at clip boundaries; then
                    # accept silence (the GAP-baron 17s/10s class — see risk register).
                    while job["n_fillers"] < MAX_FILLERS_PER_TURN and not job["done"]:
                        if first_content.wait(timeout=FILLER_ACK_SECONDS):
                            return                                # content arrived at a clip boundary
                        b = bridge_deck.deal() if bridge_deck else None
                        if not b or job["done"]:
                            return
                        push_clip(b[0], b[1], fmt=b[2] if len(b) > 2 else "wav")
                        job["stage2_fired"] = True
                        job["stage2_clip_ids"].append(b[0])
                threading.Thread(target=bridge_monitor, daemon=True).start()

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
