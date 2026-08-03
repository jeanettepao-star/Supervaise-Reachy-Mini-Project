"""Always-on wake listening for host-mic surfaces (the Streamlit kiosk demo).

A background thread streams the HOST microphone through the trained openwakeword
model frame by frame (the always-on usage the model was built for — ~1% CPU).
When the score clears the threshold it captures the visitor's question with
simple energy endpointing (record until ~1 s of silence, capped), wraps it as
WAV bytes, and puts it on a thread-safe queue for the UI thread to consume.
After a fire the listener SUSPENDS itself; the UI resumes it when the answer
turn is done — that is the debounce AND keeps the robot's own spoken answer
from being scored (speakers feed the mic on a kiosk).

No streamlit imports here: the page polls `state`/`last_score` and drains
`captured`. The audio source is injectable (`frame_source`) so the fire/capture
logic is testable offline with real clips and no mic.
"""
from __future__ import annotations

import io
import queue
import threading
import wave
from collections import deque
from pathlib import Path
from typing import Iterator, Optional

import sys

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402

SAMPLE_RATE = 16_000
FRAME = 1280                     # openwakeword's fixed streaming chunk (80 ms)


def _cfg(name, default):
    return getattr(config, name, default)


class HandsFreeListener:
    """Own the mic; fire on the wake phrase; hand captured questions to the UI.

    States: starting -> listening -> capturing -> suspended (after a fire, or
    when the UI calls suspend() while an answer plays) -> listening ... or
    "error: ..." (thread ended; the UI shows the reason and falls back to
    push-to-talk). stop() ends the thread for good.
    """

    def __init__(self, detector, device: Optional[int] = None,
                 frame_source: Optional[Iterator] = None,
                 query_max_s: Optional[float] = None,
                 silence_stop_s: float = 1.0,
                 min_speech_s: float = 0.4,
                 speech_peak: float = 0.015):
        self.det = detector
        self.device = device
        self.query_max_s = float(query_max_s if query_max_s is not None
                                 else _cfg("WAKE_QUERY_MAX_S", 6.0))
        self.silence_stop_s = float(silence_stop_s)
        self.min_speech_s = float(min_speech_s)
        self.speech_peak = float(speech_peak)   # peak fraction of full scale = "speech"

        self.captured: queue.Queue = queue.Queue()
        self.state = "starting"
        self.last_score = 0.0
        self._recent = deque(maxlen=20)   # ~1.6 s of frame scores; UIs poll slower
        self.device_name = ""
        self._suspended = threading.Event()
        self._stopped = threading.Event()
        self._source = frame_source
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="wake-listener")
        self._thread.start()

    # ---- UI-thread controls -------------------------------------------------
    def suspend(self):
        self._suspended.set()

    def resume(self):
        self._suspended.clear()

    def stop(self):
        self._stopped.set()

    def alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def recent_peak(self) -> float:
        """Max score over the last ~1.6 s — what a slow-polling UI meter should show
        (frames score every 80 ms; the phrase's spike would fall between polls)."""
        return max(self._recent, default=0.0)

    # ---- audio source (default: host mic via sounddevice) -------------------
    def _mic_frames(self):  # pragma: no cover - needs a real mic
        import sounddevice as sd
        if self.device is not None:
            sd.default.device = (self.device, None)
        self.device_name = sd.query_devices(sd.default.device[0])["name"]
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            blocksize=FRAME, device=self.device) as stream:
            while not self._stopped.is_set():
                frame, _overflowed = stream.read(FRAME)
                yield frame.reshape(-1)

    # ---- the loop ------------------------------------------------------------
    def _run(self):
        try:
            import numpy as np
            model = self.det._load()
            frames = self._source if self._source is not None else self._mic_frames()
            for mono in frames:
                if self._stopped.is_set():
                    break
                if self._suspended.is_set():
                    # Keep draining the mic (stay realtime) but score nothing —
                    # the answer playing through the speakers must not retrigger.
                    self.state = "suspended"
                    continue
                self.state = "listening"
                score = max(model.predict(mono).values())
                self.last_score = float(score)
                self._recent.append(self.last_score)
                if score >= self.det.threshold:
                    self.state = "capturing"
                    wav = self._capture_question(frames, np)
                    if hasattr(model, "reset"):
                        model.reset()          # forget the wake audio before rearming
                    self._recent.clear()       # stale spike must not linger on the meter
                    self.captured.put({"wav": wav, "score": float(score)})
                    self._suspended.set()      # UI resumes us after the turn
            self.state = "stopped"
        except Exception as e:                 # surface the reason; UI degrades
            self.state = f"error: {type(e).__name__}: {e}"

    def _capture_question(self, frames, np) -> bytes:
        """Record until `silence_stop_s` of quiet follows >= `min_speech_s` of
        speech, capped at `query_max_s`. Returns 16 kHz mono PCM16 WAV bytes."""
        chunks, t, speech_s, silence_s = [], 0.0, 0.0, 0.0
        step = FRAME / SAMPLE_RATE
        for mono in frames:
            if self._stopped.is_set():
                break
            chunks.append(mono.copy())
            t += step
            peak = float(np.max(np.abs(mono))) / 32768.0
            if peak >= self.speech_peak:
                speech_s += step
                silence_s = 0.0
            else:
                silence_s += step
            if speech_s >= self.min_speech_s and silence_s >= self.silence_stop_s:
                break
            if t >= self.query_max_s:
                break
        pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.astype("<i2").tobytes())
        return buf.getvalue()
