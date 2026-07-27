"""Hands-free CJ demo — WAKE WORD -> develop pipeline, end to end.

Say the wake phrase (config.WAKE_PHRASE, default "Cee-Jap" / "Hey Cee-Jap"); the app
records your question, runs the develop retrieval->compose pipeline, and speaks the
answer back. Wake detection is upstream of the pipeline (seam §f): the pipeline sees
only query_text.

This is the hands-free surface (cf. the deferred origin/integration/hands-free-wake).
It is OPT-IN and does NOT change the push-to-talk Streamlit demo. Requires a mic
(`pip install sounddevice`), ffmpeg for MP3 playback (imageio-ffmpeg or system), and
OPENAI_API_KEY + ANTHROPIC_API_KEY. Enable with CJ_WAKE_WORD_ENABLED=1.

Run:  CJ_WAKE_WORD_ENABLED=1 python wake_demo.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import config
import wake_word


# ---------------------------------------------------------------- mic capture / playback
def _record_window(seconds: float, samplerate: int = 16000) -> str:
    """Record `seconds` of mono 16-bit audio to a temp WAV; return the path."""
    import numpy as np           # noqa: F401
    import sounddevice as sd
    rec = sd.rec(int(seconds * samplerate), samplerate=samplerate, channels=1, dtype="int16")
    sd.wait()
    fd, path = tempfile.mkstemp(suffix=".wav"); os.close(fd)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(samplerate)
        w.writeframes(rec.tobytes())
    return path


def _play_mp3(mp3_bytes: bytes) -> None:
    """Decode the answer MP3 (pydub+ffmpeg, discovered by voice_io) and play it."""
    if not mp3_bytes:
        return
    import io
    import numpy as np
    import sounddevice as sd
    from pydub import AudioSegment
    seg = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3").set_channels(1)
    samples = np.array(seg.get_array_of_samples()).astype("int16")
    sd.play(samples, seg.frame_rate); sd.wait()


# ---------------------------------------------------------------- the pipeline turn
def build_pipeline_handler():
    """Return handle_query(query_text) that runs the develop turn and speaks the answer."""
    import retrieval
    import service
    import voice_io

    allow = service._allowlist("v4")
    transport = service._resolve_transport()
    client = service._client() if transport == "native_sdk" else None

    def handle_query(query_text: str) -> None:
        print(f"[query] {query_text!r}")
        r = retrieval.run(query_text, allow)
        directives = service._directives(query_text, r["route"])
        comp = service.compose_streamed(query_text, r["retrieval"]["selected"],
                                        directives, client=client)
        answer = comp.get("answer") or ""
        print(f"[answer] {answer[:160]}{'…' if len(answer) > 160 else ''}")
        _play_mp3(voice_io.tts_concatenate_parallel(answer))

    return handle_query


def main() -> int:
    if not getattr(config, "WAKE_WORD_ENABLED", False):
        print("Wake word is OFF. Enable it: set CJ_WAKE_WORD_ENABLED=1 (or config.WAKE_WORD_ENABLED=True).")
        return 2
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not os.environ.get(key):
            try:
                from dotenv import load_dotenv
                for p in (ROOT / "app" / ".env", ROOT / ".env"):
                    if p.exists():
                        load_dotenv(p, override=False)
            except Exception:
                pass
    detector = wake_word.make_detector()
    handle_query = build_pipeline_handler()
    query_secs = float(getattr(config, "WAKE_QUERY_MAX_S", 6.0))

    def capture_query() -> str:
        import voice_io
        print(f"[wake] listening for your question ({query_secs:.0f}s)…")
        path = _record_window(query_secs)
        try:
            return voice_io.transcribe(path, language="en")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def greet():
        print("  …yes?")

    wake_word.run_hands_free_loop(handle_query, detector=detector,
                                  capture_query=capture_query, greet=greet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
