"""
W2.7 SEAM — INTERFACE STUB SIGNATURES ONLY (design artifact, NOT runtime code).

This file defines the *contract surface* for the Pipeline ⇄ Reachy seam and the
swappable TTS plug-in. It is intentionally implementation-free (`...`). It is a
review deliverable under design/ — it is NOT imported by app/, adds no deps, and
is not wired into anything. See design/w2_7_reachy_seam.md for the rationale and
the MUST-CONFIRM list. Every Reachy-side shape here is an ASSUMPTION pending SDK
confirmation.

Real symbols this contract adapts (already in the repo):
  service.compose_streamed(query, selected, directives, client=None, on_text=None)
      -> {answer, envelope, raw, ttft_ms, stop_reason, degraded, usage}
  service.answer(query_text, allowlist_version="v4", on_text=None) -> {answer, envelope}
  service._resolve_transport() -> "native_sdk" | "schannel_curl"
  voice_stream.SentenceChunker.feed(text)->list[str] / .flush()->list[str]   (stops at sentinel)
  config.COMPOSER_ENVELOPE_SENTINEL, COMPOSER_FALLBACK_MESSAGE, COMPOSER_TIMEOUT_S
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator, Optional, Protocol, runtime_checkable


# ── b. STREAMING CONTRACT — seam events ─────────────────────────────────────────
@dataclass
class ProseDelta:
    """A fragment of SPOKEN prose. The ONLY event type routed to TTS."""
    text: str


@dataclass
class Envelope:
    """Trailing composer metadata — NEVER spoken. Delivered on the side channel."""
    doc_ids_cited: list[str]
    register_used: str
    anecdotes_deployed: list[str]
    signature_phrases_used: list[str]


@dataclass
class Done:
    stop_reason: str            # "end_turn" | "max_tokens" | "error_fallback"


@dataclass
class TurnError:
    kind: str                   # "compose_timeout" | "degraded" | "transport" | "tts"
    spoken_fallback: str        # in-voice line the robot should speak (e.g. COMPOSER_FALLBACK_MESSAGE)


SeamEvent = "ProseDelta | Envelope | Done | TurnError"   # discriminated-union contract


# ── a/b. THE SEAM — pipeline exposes; Reachy runtime consumes ────────────────────
@runtime_checkable
class PipelineSeam(Protocol):
    """Text-in / streamed-prose-out LLM slot. Owns retrieval+compose+prose/ENVELOPE
    split. Never touches audio or motors. `stream_turn` yields ProseDelta events as
    they stream, then exactly one Envelope (metadata), then Done — so the ENVELOPE
    is structurally on a different event than any spoken text."""

    def stream_turn(self, query_text: str, *, allowlist_version: str = "v4",
                    session_id: Optional[str] = None) -> Iterator["SeamEvent"]:
        ...

    def cancel(self, session_id: str) -> None:
        """Barge-in: stop compose + prose mid-turn (MUST-CONFIRM #7)."""
        ...

    def transport(self) -> str:
        """'native_sdk' (streaming) | 'schannel_curl' (no streaming → TTFA=full compose).
        Surfaced so the robot can pick a filler/degraded UX. Wraps service._resolve_transport()."""
        ...


# ── OpenAI-compatible adapter (if the s2s runtime points its LLM base_url at us) ──
@runtime_checkable
class OpenAICompatLLMSlot(Protocol):
    """ASSUMPTION (MUST-CONFIRM #1/#2/#4): the s2s runtime speaks an OpenAI-compatible
    streaming API. Prose streams as text deltas; the ENVELOPE rides a terminal
    non-text field (tool_call/metadata) or a separate GET — never in the delta text."""

    def stream_chat_completions(self, messages: list[dict], *, stream: bool = True
                                ) -> Iterator[dict]:               # yields chat.completion.chunk-like frames
        ...

    def get_turn_envelope(self, turn_id: str) -> Envelope:        # side-channel fallback for metadata
        ...


# ── c. TTS PLUG-IN — SAPI now, Piper/Kokoro drop-in ─────────────────────────────
@dataclass
class AudioChunk:
    pcm: bytes                  # 16-bit PCM (format negotiated at open(); MUST-CONFIRM #5)
    sample_rate: int
    duration_s: float


@runtime_checkable
class TTSBackend(Protocol):
    """Swappable synthesis engine. SAPI (dev stand-in), Piper, Kokoro implement THIS
    same surface — swapping an engine touches no pipeline/seam code. Mirrors the
    current voice_stream synth shape and generalizes it for streaming engines."""

    name: str
    incremental: bool           # True = per-sentence (or finer) synthesis → stream-overlap holds.
    sample_rate: int

    def open(self, *, voice: Optional[str] = None, sample_rate: Optional[int] = None) -> None:
        ...

    def warmup(self) -> float:  # returns first-utterance cold-load ms (excluded from steady-state)
        ...

    def synthesize(self, text_chunk: str) -> AudioChunk:
        """Blocking, one sentence/clause chunk -> audio. (SAPI/Piper path.)"""
        ...

    def synthesize_stream(self, text_chunk: str) -> Iterator[AudioChunk]:
        """OPTIONAL: sub-sentence streaming audio for engines that support it
        (emit first sample before the sentence finishes). Falls back to synthesize()
        when unavailable. Engines with incremental=False MUST NOT be used (lose overlap)."""
        ...

    def close(self) -> None:
        ...


# ── The robot-side glue the seam ASSUMES exists (Reachy owns; shown for the contract) ──
@runtime_checkable
class RobotAudioOut(Protocol):
    """Robot-owned sink. Subscribes to ProseDelta only. Chunking may be robot-side
    (MUST-CONFIRM #3): if so, the pipeline emits raw prose deltas and this consumer
    chunks; our voice_stream.SentenceChunker is then a dev-only reference."""

    def on_prose_delta(self, delta: ProseDelta) -> None: ...
    def play(self, chunk: AudioChunk) -> None: ...
    def barge_in(self) -> None: ...          # triggers PipelineSeam.cancel(session_id)
