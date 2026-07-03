"""
W2.7 — sentence-streaming TTS front-end (Approach 3 backbone).

Takes a token/text STREAM (the composer's streamed prose, UNWRAPPED — the W2.1
ENVELOPE trails after the sentinel and is never spoken) and emits SENTENCE/
CLAUSE-boundary chunks (never mid-word), feeding a LOCAL, incremental TTS so
sentence 1 is synthesized while sentence 2 is still arriving. This is what turns
~12s "wait-for-full-answer" into ~2-3s Time-To-First-Audio (TTFA).

TTS backends are pluggable via the TTS protocol (synth(text) -> (wav_path,
synth_ms, audio_s)). SAPI (Windows, offline, $0) is used for local measurement;
the robot's Piper/Kokoro drops into the SAME interface (PiperTTS below), so the
Reachy Mini audio loop is a swap, not a rewrite.
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

import config

# Sentence + CLAUSE boundary: punctuation .!?;: (optionally a closing quote/paren)
# followed by whitespace, OR end-of-buffer sentence-enders. Boundaries always sit
# AFTER whitespace-following punctuation -> a split can never fall mid-word.
_BOUNDARY = re.compile(r'[.!?;:]["\'\)\]]?(\s+|$)')
_SENTINEL = config.COMPOSER_ENVELOPE_SENTINEL


class SentenceChunker:
    """Accumulate a text stream; emit complete sentence/clause chunks at
    boundaries. A partial tail is held until the next boundary or flush().
    Stops emitting once the ENVELOPE sentinel appears (metadata is not spoken)."""

    def __init__(self):
        self.buf = ""
        self._done = False

    def feed(self, chunk: str) -> list[str]:
        if self._done:
            return []
        self.buf += chunk
        cut = self.buf.find(_SENTINEL)          # never speak the trailing envelope
        if cut >= 0:
            self.buf = self.buf[:cut]
            self._done = True
        out = []
        while True:
            m = _BOUNDARY.search(self.buf)
            if not m:
                break
            end = m.end()
            sent = self.buf[:end].strip()
            self.buf = self.buf[end:]
            if sent:
                out.append(sent)
        return out

    def flush(self) -> list[str]:
        s = self.buf.strip()
        self.buf = ""
        return [s] if s else []


class SapiTTS:
    """Windows SAPI5 (offline, $0). Synthesizes one chunk to a WAV file and
    reports synth wall-time + resulting audio duration."""

    def __init__(self, voice_substr: str | None = None):
        import win32com.client as w
        self._w = w
        self.sp = w.Dispatch("SAPI.SpVoice")
        if voice_substr:
            vs = self.sp.GetVoices()
            for i in range(vs.Count):
                if voice_substr.lower() in vs.Item(i).GetDescription().lower():
                    self.sp.Voice = vs.Item(i); break
        self.name = "sapi5"

    def synth(self, text: str):
        fs = self._w.Dispatch("SAPI.SpFileStream")
        fd, path = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        fs.Open(path, 3)                        # SSFMCreateForWrite
        self.sp.AudioOutputStream = fs
        t0 = time.perf_counter()
        self.sp.Speak(text)
        synth_ms = (time.perf_counter() - t0) * 1000
        fs.Close()
        with wave.open(path, "rb") as wf:
            audio_s = wf.getnframes() / float(wf.getframerate())
        return path, round(synth_ms, 1), round(audio_s, 3)


class PiperTTS:
    """Robot/production drop-in (rhasspy Piper). Same interface as SapiTTS. Used
    when PIPER_BIN + PIPER_VOICE are present; otherwise unavailable here."""

    def __init__(self, piper_bin=None, voice=None):
        self.bin = piper_bin or os.environ.get("PIPER_BIN", "piper")
        self.voice = voice or os.environ.get("PIPER_VOICE", "")
        self.name = "piper"

    def available(self) -> bool:
        from shutil import which
        return bool(which(self.bin)) and bool(self.voice) and Path(self.voice).exists()

    def synth(self, text: str):
        fd, path = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        t0 = time.perf_counter()
        subprocess.run([self.bin, "-m", self.voice, "-f", path],
                       input=text.encode("utf-8"), capture_output=True)
        synth_ms = (time.perf_counter() - t0) * 1000
        with wave.open(path, "rb") as wf:
            audio_s = wf.getnframes() / float(wf.getframerate())
        return path, round(synth_ms, 1), round(audio_s, 3)


def speak_stream(token_iter, tts, keep_wavs: bool = False) -> dict:
    """Drive the incremental path: consume a token/text stream, synthesize
    sentence chunks in a WORKER thread as they complete (synth N while N+1 still
    arrives). Returns TTFA + per-sentence timing + total spoken duration.

    token_iter yields text pieces WITH their own real inter-arrival timing (a
    replay iterator sleeps to emulate the composer's stream), so TTFA reflects
    stream-accumulation + synthesis, exactly as a live kiosk would experience it.
    """
    chunker = SentenceChunker()
    q: queue.Queue = queue.Queue()
    sentences, wavs = [], []
    t0 = time.perf_counter()
    ttfa = {"ms": None}

    def worker():
        while True:
            item = q.get()
            if item is None:
                q.task_done(); break
            idx, sent, emit_ms = item
            path, synth_ms, audio_s = tts.synth(sent)
            ready_ms = (time.perf_counter() - t0) * 1000
            if ttfa["ms"] is None:
                ttfa["ms"] = ready_ms                 # first spoken audio sample OUT
            sentences.append({"idx": idx, "text": sent, "emit_ms": round(emit_ms, 1),
                              "synth_ms": synth_ms, "audio_s": audio_s,
                              "audio_ready_ms": round(ready_ms, 1)})
            (wavs.append(path) if keep_wavs else os.unlink(path))
            q.task_done()

    th = threading.Thread(target=worker, daemon=True); th.start()
    idx = 0
    for piece in token_iter:
        for sent in chunker.feed(piece):
            q.put((idx, sent, (time.perf_counter() - t0) * 1000)); idx += 1
    for sent in chunker.flush():
        q.put((idx, sent, (time.perf_counter() - t0) * 1000)); idx += 1
    q.join(); q.put(None); th.join()
    stream_done_ms = (time.perf_counter() - t0) * 1000
    sentences.sort(key=lambda s: s["idx"])
    return {"ttfa_ms": round(ttfa["ms"], 1) if ttfa["ms"] else None,
            "n_sentences": len(sentences), "sentences": sentences,
            "total_spoken_s": round(sum(s["audio_s"] for s in sentences), 2),
            "stream_done_ms": round(stream_done_ms, 1),
            "wavs": wavs}
