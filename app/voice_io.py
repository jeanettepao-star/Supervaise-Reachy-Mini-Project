"""
Cost-efficient voice I/O for the CJ Panganiban dashboard.

Replaces the prior faster-whisper + Piper TTS stack with OpenAI's
hosted STT (Whisper-1) and TTS (tts-1 / tts-1-hd) — keeping push-to-talk
recording and per-sentence chunked TTS so we never pay for an always-on
realtime audio stream.

Design constraints (per the user's spec):

  - Push-to-talk ONLY: the mic is never continuously open. The user
    presses "Start Talking", speaks, presses "Stop", and we transcribe
    the resulting blob in ONE Whisper call. No streaming STT.

  - Progressive TTS: Claude's response is sentence-chunked; each chunk
    fires an OpenAI TTS request IN PARALLEL via asyncio.gather. The
    audio chunks are concatenated (pydub if available, raw byte
    concatenation otherwise) and returned as one MP3 blob — so the
    Streamlit `st.audio(autoplay=True)` element starts playing the
    full response within ~1-2 s of the text stream finishing.

  - No always-on streaming: we don't use OpenAI's per-minute Realtime
    API; per-utterance Whisper at $0.006/min and per-sentence TTS at
    $0.015/1k chars is roughly 10-20× cheaper.

Per-turn voice-IO cost (late-2025 prices, typical 10-15 s utterance
and 200-300 char response):
  - STT (whisper-1)       : ~$0.001
  - TTS (tts-1, parallel) : ~$0.003 - $0.005
  - Total voice overhead  : ~$0.004 - $0.006

This module deliberately has NO Streamlit imports — it's plain
Python and is reusable from cj_chat.py CLI smoke tests.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import shutil
import warnings
from pathlib import Path
from typing import Optional

# ============================================================
# ffmpeg discovery — required by pydub for MP3 decoding/encoding
# ============================================================
# Order of preference for the ffmpeg binary:
#   1. system PATH (operator installed it system-wide)
#   2. imageio-ffmpeg's bundled binary (pip install imageio-ffmpeg)
# If neither is available, _concatenate_mp3_chunks() falls back to
# raw byte concatenation (works for OpenAI's constant-bitrate MP3 in
# practice, with occasional minor seam artefacts).
_FFMPEG_PATH: str | None = (
    shutil.which("ffmpeg")
    or shutil.which("avconv")
)
if not _FFMPEG_PATH:
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]
        _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        _FFMPEG_PATH = None

# Silence pydub's startup "Couldn't find ffmpeg" warning AND, when
# imageio-ffmpeg supplied a binary, point pydub at it explicitly.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", RuntimeWarning)
    try:
        import pydub  # type: ignore[import-not-found]
        if _FFMPEG_PATH:
            pydub.AudioSegment.converter = _FFMPEG_PATH
            pydub.AudioSegment.ffmpeg = _FFMPEG_PATH
            # Some pydub builds also probe ffprobe; if it lives next to
            # ffmpeg, point at it too (best-effort).
            _ffprobe_guess = Path(_FFMPEG_PATH).with_name("ffprobe")
            if _ffprobe_guess.with_suffix(".exe").exists():
                pydub.AudioSegment.ffprobe = str(_ffprobe_guess.with_suffix(".exe"))
            elif _ffprobe_guess.exists():
                pydub.AudioSegment.ffprobe = str(_ffprobe_guess)
        _PYDUB_AVAILABLE = True
    except ImportError:
        _PYDUB_AVAILABLE = False


# ============================================================
# Client factories — lazy, singleton, env-configurable
# ============================================================
_SYNC_CLIENT = None
_ASYNC_CLIENT = None


def _ensure_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to one of the .env files "
            "searched by cj_chat (cwd / repo-root / app), or set "
            "DOTENV_PATH to point at the file."
        )


def _sync_client():
    """Return a cached synchronous OpenAI client."""
    global _SYNC_CLIENT
    if _SYNC_CLIENT is None:
        _ensure_key()
        from openai import OpenAI  # imported lazily so the module
        _SYNC_CLIENT = OpenAI()    # parses even when openai is absent
    return _SYNC_CLIENT


def _async_client():
    """Return a cached asynchronous OpenAI client (used by parallel TTS)."""
    global _ASYNC_CLIENT
    if _ASYNC_CLIENT is None:
        _ensure_key()
        from openai import AsyncOpenAI
        _ASYNC_CLIENT = AsyncOpenAI()
    return _ASYNC_CLIENT


# ============================================================
# Defaults — overridable via env
# ============================================================
STT_MODEL_DEFAULT = os.environ.get("OPENAI_STT_MODEL", "whisper-1")
TTS_MODEL_DEFAULT = os.environ.get("OPENAI_TTS_MODEL", "tts-1")
# Voice — pick one of: alloy, echo, fable, onyx, nova, shimmer.
# `onyx` is a deep, calm, authoritative male voice — the best fit for
# retired Chief Justice Panganiban's measured judicial register. Other
# male options: `echo` (lighter male) or `fable` (British male).
# Female alternatives (nova, shimmer) preserved for testing.
TTS_VOICE_DEFAULT = os.environ.get("OPENAI_TTS_VOICE", "onyx")
# Speech speed — tts-1 supports 0.25 to 4.0. CJP speaks at a very
# relaxed pace; the 80-85% range captures it best without sounding
# unnaturally slow. 0.82 sits mid-range.
TTS_SPEED_DEFAULT = float(os.environ.get("OPENAI_TTS_SPEED", "0.82"))


# ============================================================
# STT — one Whisper call per recording
# ============================================================
def transcribe_openai(
    audio_path: str | Path,
    model: str | None = None,
    language: Optional[str] = None,
) -> str:
    """Transcribe an audio file via OpenAI Whisper API.

    Called once per push-to-talk recording. The file is opened in
    binary mode and POSTed to OpenAI; the response is plain text.

    Cost (whisper-1, late 2025): $0.006 per minute of audio.

    Args:
        audio_path: path to a WAV / MP3 / WEBM / OGG / M4A file.
        model: override STT_MODEL_DEFAULT (whisper-1).
        language: optional 2-letter language hint ("en", "tl");
                  None lets Whisper auto-detect.

    Returns:
        Trimmed transcript string. Empty string if Whisper returned
        nothing usable.
    """
    client = _sync_client()
    audio_path = Path(audio_path)
    with open(audio_path, "rb") as f:
        kwargs: dict = {
            "model": model or STT_MODEL_DEFAULT,
            "file": f,
            "response_format": "text",
        }
        if language:
            kwargs["language"] = language
        resp = client.audio.transcriptions.create(**kwargs)
    # response_format="text" returns a plain string; defensively
    # handle the structured-response shape too.
    if isinstance(resp, str):
        return resp.strip()
    text = getattr(resp, "text", "")
    return str(text).strip()


# ============================================================
# Cadence enhancement — inject reflective pauses for CJP's voice
# ============================================================
# CJP speaks deliberately and groups his sentences into distinct
# phrases. We pre-insert ellipses after his signature reflective
# markers so the TTS engine takes a longer, more thoughtful breath
# at those points (in addition to the slower base TTS_SPEED_DEFAULT).
#
# Rules are conservative: only well-known CJP markers, only when
# followed by a comma (so we don't trigger inside quoted text or
# at sentence boundaries that already have natural pauses).
_REFLECTIVE_MARKERS = [
    r"In my humble opinion",
    r"In my view",
    r"In my respectful view",
    r"With due respect",
    r"Au contraire",
    r"IMHO",
    r"In conclusion",
    r"More importantly",
    r"That said",
    r"Indeed",
    r"Allow me to say",
    r"Permit me to say",
    r"As I have said before",
    r"As I have written",
]
_CADENCE_RE = re.compile(
    r"\b(" + "|".join(_REFLECTIVE_MARKERS) + r"),",
    re.IGNORECASE,
)


def add_reflective_pauses(text: str) -> str:
    """Inject ellipses after CJP's signature reflective markers.

    Converts e.g. "In my humble opinion, the rule of law…" into
    "In my humble opinion... the rule of law…" — OpenAI TTS treats
    the ellipsis as a longer reflective breath than a comma.

    Conservative by design: only touches the ~14 markers in
    `_REFLECTIVE_MARKERS`. Leaves the rest of the text alone so we
    don't accidentally split mid-thought.
    """
    if not text:
        return text
    return _CADENCE_RE.sub(r"\1...", text)


# ============================================================
# Sentence chunking — pack text into TTS-ready bites
# ============================================================
# Sentence boundary regex: end punctuation followed by whitespace, OR
# a blank line. The negative lookbehind `(?<!\.\.)` keeps us from
# splitting on the LAST period of an ellipsis (`...`) — those are
# reflective pauses, not sentence terminators.
_SENTENCE_END = re.compile(r"(?<=[.!?])(?<!\.\.)\s+|\n\n+")
_MIN_CHUNK_CHARS = 30   # smaller than this wastes an API call
_MAX_CHUNK_CHARS = 240  # OpenAI TTS handles this gracefully; longer chunks
                        #   delay first-audio-out for the slowest sentence


def sentence_chunks(text: str) -> list[str]:
    """Split text into TTS-ready chunks.

    Each chunk ends at a sentence boundary and is roughly 30-240 chars.
    Very short trailing fragments are merged into their neighbour so we
    don't fire one TTS call per stray exclamation.
    """
    text = (text or "").strip()
    if not text:
        return []

    raw_pieces = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for piece in raw_pieces:
        candidate = f"{buf} {piece}".strip() if buf else piece
        if len(candidate) <= _MAX_CHUNK_CHARS:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            buf = piece
    if buf:
        chunks.append(buf)

    # Merge any chunk shorter than _MIN_CHUNK_CHARS into the previous.
    merged: list[str] = []
    for c in chunks:
        if merged and len(c) < _MIN_CHUNK_CHARS:
            merged[-1] = f"{merged[-1]} {c}".strip()
        else:
            merged.append(c)
    return merged


# ============================================================
# Async parallel TTS — fan-out per sentence, gather, concatenate
# ============================================================
async def _tts_one_async(client, text: str, voice: str, model: str, speed: float) -> bytes:
    """One TTS call. Uses with_streaming_response so OpenAI flushes
    bytes as they're generated — but we still consume the whole stream
    here because Streamlit's `st.audio` needs a complete blob."""
    async with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=text,
        speed=speed,
        response_format="mp3",
    ) as response:
        out = bytearray()
        async for chunk in response.iter_bytes():
            out.extend(chunk)
        return bytes(out)


async def tts_chunks_parallel_async(
    text: str,
    voice: str = TTS_VOICE_DEFAULT,
    model: str = TTS_MODEL_DEFAULT,
    speed: float = TTS_SPEED_DEFAULT,
    apply_cadence: bool = True,
) -> list[bytes]:
    """Fire TTS for every sentence chunk concurrently. Returns a list
    of MP3 byte blobs in source order.

    When `apply_cadence` is True (default), the text is passed through
    `add_reflective_pauses()` so CJP's signature markers get a longer
    reflective breath. Set to False for a raw passthrough during
    debugging or when testing alternative voices.
    """
    client = _async_client()
    if apply_cadence:
        text = add_reflective_pauses(text)
    chunks = sentence_chunks(text)
    if not chunks:
        return []
    return list(await asyncio.gather(
        *[_tts_one_async(client, c, voice, model, speed) for c in chunks]
    ))


# ============================================================
# Audio concatenation — pydub if available, raw fallback otherwise
# ============================================================
def _concatenate_mp3_chunks(chunks: list[bytes]) -> bytes:
    """Concatenate per-sentence MP3 blobs into one playable MP3.

    Three-tier fallback:
      1. pydub + ffmpeg present  → clean re-encoded concatenation
         (no frame-boundary artefacts).
      2. pydub installed, ffmpeg missing  → skip pydub entirely and
         fall back to raw byte concatenation. We catch every
         exception in case pydub's import succeeded but a runtime
         decode still fails on systems where the ffmpeg binary is
         malformed or unreadable.
      3. pydub not installed     → raw byte concatenation.

    OpenAI's `tts-1` returns constant-bitrate MP3, which concatenates
    reasonably well at the byte level. Strict players may produce a
    soft click at chunk seams; the audio player in browsers (Streamlit
    uses HTML5 <audio>) handles this gracefully.
    """
    if not chunks:
        return b""
    if len(chunks) == 1:
        return chunks[0]
    if not (_PYDUB_AVAILABLE and _FFMPEG_PATH):
        return b"".join(chunks)
    try:
        from pydub import AudioSegment  # type: ignore[import-not-found]
        segments = [
            AudioSegment.from_file(io.BytesIO(c), format="mp3") for c in chunks
        ]
        combined = segments[0]
        for s in segments[1:]:
            combined = combined + s
        out = io.BytesIO()
        combined.export(out, format="mp3")
        return out.getvalue()
    except Exception:
        # Decoder errors, ffmpeg subprocess failures, file-handle issues —
        # never let a TTS-concat error block the response from reaching
        # the user. Fall back to raw concat.
        return b"".join(chunks)


# ============================================================
# Top-level synchronous API for Streamlit
# ============================================================
def tts_concatenate_parallel(
    text: str,
    voice: str | None = None,
    model: str | None = None,
    speed: float | None = None,
) -> bytes:
    """The single function the dashboard calls.

    Returns one MP3 byte blob synthesised by parallel per-sentence
    OpenAI TTS calls and concatenated end-to-end. Total wall-clock
    time ≈ the slowest single sentence (because the calls run
    concurrently), not the sum of all of them.
    """
    audio_chunks = asyncio.run(
        tts_chunks_parallel_async(
            text,
            voice=voice or TTS_VOICE_DEFAULT,
            model=model or TTS_MODEL_DEFAULT,
            speed=speed if speed is not None else TTS_SPEED_DEFAULT,
        )
    )
    return _concatenate_mp3_chunks(audio_chunks)


# ============================================================
# Cost estimator (advisory — printed in operator dashboard)
# ============================================================
# Late-2025 OpenAI list prices ($/1K of the relevant unit)
PRICE_PER_KCHAR_TTS_1 = 0.015
PRICE_PER_KCHAR_TTS_1_HD = 0.030
PRICE_PER_MIN_WHISPER = 0.006


def estimate_voice_cost(text: str, tts_model: str = TTS_MODEL_DEFAULT) -> dict:
    """Return a dict {tts_usd, …} estimating the cost of one turn's TTS.
    STT cost is estimated separately by the caller because it depends
    on audio duration, which the module doesn't see."""
    n_chars = len(text or "")
    rate = PRICE_PER_KCHAR_TTS_1_HD if "hd" in tts_model else PRICE_PER_KCHAR_TTS_1
    return {
        "tts_chars": n_chars,
        "tts_model": tts_model,
        "tts_usd": round(rate * n_chars / 1000, 5),
    }


def voice_io_summary() -> dict[str, object]:
    """Sidebar-friendly summary of the active OpenAI voice config."""
    return {
        "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "stt_model": STT_MODEL_DEFAULT,
        "tts_model": TTS_MODEL_DEFAULT,
        "tts_voice": TTS_VOICE_DEFAULT,
        "tts_speed": TTS_SPEED_DEFAULT,
        "pydub_available": _PYDUB_AVAILABLE,
        "ffmpeg_path": _FFMPEG_PATH or "(missing — using raw byte concat)",
    }


__all__ = [
    "transcribe_openai",
    "add_reflective_pauses",
    "sentence_chunks",
    "tts_chunks_parallel_async",
    "tts_concatenate_parallel",
    "estimate_voice_cost",
    "voice_io_summary",
    "STT_MODEL_DEFAULT",
    "TTS_MODEL_DEFAULT",
    "TTS_VOICE_DEFAULT",
    "TTS_SPEED_DEFAULT",
]
