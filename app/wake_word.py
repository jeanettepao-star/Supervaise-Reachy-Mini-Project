"""
Python wrapper around the `wake_word_continuous` Streamlit component.

The component itself (HTML + bundled JS + ONNX models) lives in
`app/components/wake_word_continuous/`. This module is the thin
Python boundary that lets `app.py` call:

    payload = wake_word_continuous(
        enabled=True,
        silence_ms=5000,
        max_question_ms=20000,
        is_busy=False,
        tts_duration_ms=0,
        key="hey_cjp_continuous",
    )

and receive either `None` (no capture yet / status-only render) or
a dict with the captured audio. See the component's README for the
full payload schema and state machine.

The wake-word backend is **openWakeWord** (Apache-2.0) running in
the browser via ONNX Runtime Web. No access key, no licensing.
The trained "Hey CJP" classifier is a single `wake_word.onnx` file
the operator drops into `components/wake_word_continuous/models/`;
see TRAINING.md inside that directory for the offline training
pipeline.

Why a separate module: keeping the `declare_component` call out of
`app.py` lets the kiosk import the symbol lazily and surface a clear
remediation message if the component directory is missing — without
the import failure blocking the rest of the app.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components


# Resolve the component's static directory at import time. Registered
# via `path=` (not `url=`) so the bundled JS, the AudioWorklet, the
# four ONNX models, and the ONNX Runtime Web WASM artefacts all ship
# alongside the Python app — no runtime CDN dependency.
_COMPONENT_DIR = Path(__file__).resolve().parent / "components" / "wake_word_continuous"

_wake_word_component = components.declare_component(
    "wake_word_continuous",
    path=str(_COMPONENT_DIR),
)


def wake_word_continuous(
    enabled: bool = True,
    silence_ms: int = 5000,
    max_question_ms: int = 20000,
    is_busy: bool = False,
    tts_duration_ms: int = 0,
    key: str = "wake_word_continuous",
) -> dict[str, Any] | None:
    """Render the wake-word component and return its latest payload.

    The component runs entirely client-side; this call is cheap — it
    just sends props down and reads the last value the component
    posted up. None is returned until either a status update or a
    completed capture has been sent.

    Parameters mirror the component contract documented in
    `app/components/wake_word_continuous/README.md`:

    - `enabled` : Pass False to render an inert placeholder (mic
      permission is never requested). The kiosk's Activate-Kiosk
      gate is the user-gesture boundary; once the visitor has
      pressed Activate, `enabled=True` mounts the component and
      mic permission is requested by the browser.
    - `silence_ms` : continuous-silence threshold ending the capture.
    - `max_question_ms` : safety cap on total capture length.
    - `is_busy` : True while the Python pipeline is running. The
      wake-word inference keeps running (so rolling buffers stay
      warm) but threshold-cross events are dropped, so the kiosk
      cannot re-trigger inside CJ's TTS reply.
    - `tts_duration_ms` : set just before `st.audio(autoplay=True)`.
      When > 0 and `is_busy` is False, the component enters
      SUSPENDED_FOR_PLAYBACK and arms the resume timer.

    Return shape (one of):

    - `None` — no payload yet (component still initialising, or just
      a status tick the caller already absorbed via session_state).
    - `{"__status": <state>, ...}` — status update only.
      Common states:
        INITIALIZING            (loading 4 ONNX models)
        LISTENING_FOR_WAKE      (waiting for "Hey CJP" or "CJP")
        CAPTURING_QUESTION
        SENDING
        SUSPENDED_FOR_PROCESSING
        SUSPENDED_FOR_PLAYBACK
        WAKE_WORD_MODEL_MISSING (no models/wake_word.onnx — operator
                                 hasn't dropped the trained classifier
                                 in yet; see TRAINING.md)
        ERROR
    - `{"audio_b64", "audio_sha256", "wake_fired_at",
       "capture_ended_reason", "vad_voice_ratio", "__status",
       "ts"}` — completed capture; `audio_b64` is the only field
      `app.py` actually decodes.
    """
    return _wake_word_component(
        enabled=bool(enabled),
        silence_ms=int(silence_ms),
        max_question_ms=int(max_question_ms),
        is_busy=bool(is_busy),
        tts_duration_ms=int(tts_duration_ms),
        key=key,
        default=None,
    )
