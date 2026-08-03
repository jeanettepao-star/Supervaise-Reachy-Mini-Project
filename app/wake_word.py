"""Hands-free WAKE-WORD front door for the CJ Panganiban pipeline.

Per the Reachy seam design (design/w2_7_reachy_seam.md §f), wake capture sits
UPSTREAM of the pipeline: `WAKE detect -> record -> STT -> query_text`, and the
pipeline receives only the final `query_text` — it has no wake logic. The wake
phrase is a NAMED PARAMETER (config.WAKE_PHRASE, default "Cee-Jap" — the resolution
of the long-flagged "Seejop"/"CJ"), never hardcoded.

Why STT keyword-spotting (not openWakeWord)?
  A custom phrase like "Cee-Jap" needs a *trained* model for openWakeWord/Porcupine
  (the reverted PLAN-0008 shipped a hand-trained hey_cj.onnx). Keyword-spotting over
  the STT we already run (voice_io.transcribe, faster-whisper local) needs NO trained
  model and is trivially re-parameterizable — change the phrase, done. openWakeWord
  stays a pluggable backend for the robot (WakeDetector protocol) when a model exists.

Layers (each independently testable / swappable):
  * WakePhraseMatcher — pure text logic: does a transcript contain the wake phrase?
    Tolerant of Cee-Jap mishears (see jap / cee jap / seejap / seejop); strict against
    near-misses (see the map / japan / cheese) AND the legacy CJ/see-jay family, retired
    per WW-5 (2026-07-27). Zero deps, offline.
  * WakeDetector (protocol) — SttKeywordDetector (default) | OpenWakeWordDetector
    (audio-level, wired to the trained wakeword/CJAP hey_cee_jap.onnx).
  * AudioSource (protocol) — MicAudioSource (sounddevice, lazy/optional) | inject frames.
  * wait_for_wake() / run_hands_free_loop() — arm, detect, capture the query, hand
    query_text to a pipeline callback. The pipeline stays decoupled (robot-portable).

$0 / offline: importing this module and the matcher never touch the network, a model,
or a mic. Live capture (sounddevice) and STT/pipeline are lazy and opt-in.
"""
from __future__ import annotations

import difflib
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402


# ---------------------------------------------------------------- config (named params)
def _cfg(name, default):
    return getattr(config, name, default)


# Leading filler/carrier words stripped before matching ("hey see-jap" -> "see jap").
_CARRIERS = {"hey", "ok", "okay", "hi", "hello", "yo", "um", "uh", "er", "so", "a", "the"}

# Default accepted spoken forms of the wake phrase (config.WAKE_PHRASE_VARIANTS overrides).
# Cee-Jap "-jap" mishears only — a custom phrase needs no model retrain (edit the list).
# Multi-word forms match ADJACENT tokens (per-token fuzzy); single-word forms match a
# whole TOKEN (never a substring — so a short token won't fire inside a longer word).
_DEFAULT_VARIANTS = [
    # Cee-Jap "-jap" mishears ONLY. The legacy "CJ"/"see jay"/"Jay" family is RETIRED
    # per the WW-5 decision (2026-07-27): spoken "CJ" ("see jay") must stay silent.
    # two-token (onset + coda)
    "see jap", "cee jap", "see jab", "cee jab", "sea jap", "see jip", "see jop", "c jap",
    # single-token (Whisper writes the OOV word glued together)
    "seejap", "ceejap", "cjap", "seajap", "seejop", "ceejop", "seejip",
]


@dataclass
class MatchResult:
    fired: bool
    variant: Optional[str] = None
    score: float = 0.0
    heard: str = ""


class WakePhraseMatcher:
    """Decide whether an STT transcript contains the wake phrase. Pure, offline.

    Robust to Whisper mishears of the OOV word "Cee-Jap" while rejecting common
    near-misses. Two rules, both boundary-safe (token-level, never raw substring):
      - multi-word variant ("see jap"): matches a run of ADJACENT tokens, each within
        a fuzzy ratio of the target word (so "see jab", "see jip" fire; "see the map",
        "see japan" do not — 'japan'!='jap' and ratio 0.75 < 0.80). The retired legacy
        "see jay" family (WW-5) also stays silent — 'jay' vs 'jap' is below threshold.
      - single-word variant ("seejap", "cjap"): matches a whole TOKEN by equality, or by
        fuzzy ratio for longer forms with a tight length guard ("seejapan" won't match
        "seejap").
    """

    def __init__(self, variants: Optional[Iterable[str]] = None,
                 word_ratio: float = 0.80, token_ratio: float = 0.86):
        raw = list(variants) if variants is not None else list(
            _cfg("WAKE_PHRASE_VARIANTS", None) or _DEFAULT_VARIANTS)
        self.word_ratio = float(_cfg("WAKE_WORD_RATIO", word_ratio))
        self.token_ratio = float(_cfg("WAKE_TOKEN_RATIO", token_ratio))
        norm = [self._norm(v) for v in raw if self._norm(v)]
        self._multi = [v.split() for v in norm if " " in v]
        self._single = sorted({v for v in norm if " " not in v})

    @staticmethod
    def _norm(text: str) -> str:
        text = (text or "").lower().replace("-", " ").replace("_", " ")
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _tokens(self, transcript: str) -> list[str]:
        toks = self._norm(transcript).split()
        while toks and toks[0] in _CARRIERS:   # drop leading "hey"/"ok"/...
            toks.pop(0)
        return toks

    @staticmethod
    def _ratio(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio()

    def match(self, transcript: str) -> MatchResult:
        toks = self._tokens(transcript)
        if not toks:
            return MatchResult(False, heard=transcript or "")
        best = MatchResult(False, heard=transcript or "")

        # single-token forms: whole-token equality, or fuzzy for len>=5 with length guard
        for i, tok in enumerate(toks):
            for v in self._single:
                if tok == v:
                    return MatchResult(True, v, 1.0, transcript)
                if len(v) >= 5 and abs(len(tok) - len(v)) <= 1:
                    r = self._ratio(tok, v)
                    if r >= self.token_ratio and r > best.score:
                        best = MatchResult(True, v, round(r, 3), transcript)

        # multi-token forms: adjacent run, each token within word_ratio of its target
        for words in self._multi:
            n = len(words)
            for i in range(len(toks) - n + 1):
                scores = [self._ratio(toks[i + j], words[j]) for j in range(n)]
                if all(s >= self.word_ratio for s in scores):
                    sc = round(sum(scores) / n, 3)
                    if sc > best.score:
                        best = MatchResult(True, " ".join(words), sc, transcript)

        return best if best.fired else MatchResult(False, heard=transcript or "")

    def __repr__(self):
        return f"WakePhraseMatcher(single={len(self._single)}, multi={len(self._multi)})"


def strip_wake_prefix(text: str, matcher: Optional[WakePhraseMatcher] = None) -> tuple[str, bool]:
    """Remove a leading wake phrase (plus carrier words) from a transcript.

    "Hey Cee-Jap, what is the rule of law?" -> ("what is the rule of law?", True).
    Pure text, config-driven via the matcher's variants. The original casing and
    punctuation of the remainder are preserved; the text is returned unchanged when
    the phrase is absent or only appears mid-sentence (that is the query's business).
    Used by surfaces that capture wake + question in ONE utterance (Streamlit demo),
    so the pipeline receives only query_text per the seam.
    """
    m = matcher or WakePhraseMatcher()
    raw_toks = (text or "").split()
    # Flatten normalized words with a map back to raw token indices ("Cee-Jap," is one
    # raw token but two normalized words).
    flat: list[tuple[str, int]] = []
    for ri, tok in enumerate(raw_toks):
        for word in m._norm(tok).split():
            flat.append((word, ri))
    i = 0
    while i < len(flat) and flat[i][0] in _CARRIERS:
        i += 1
    end_raw = None                      # raw index of the token that ends the phrase
    for words in m._multi:              # multi-word variants: adjacent normalized run
        n = len(words)
        if i + n <= len(flat) and all(m._ratio(flat[i + j][0], words[j]) >= m.word_ratio
                                      for j in range(n)):
            end_raw = flat[i + n - 1][1]
            break
    if end_raw is None and i < len(flat):
        tok = flat[i][0]                # single-token variants ("seejap", "cjap")
        for v in m._single:
            if tok == v or (len(v) >= 5 and abs(len(tok) - len(v)) <= 1
                            and m._ratio(tok, v) >= m.token_ratio):
                end_raw = flat[i][1]
                break
    if end_raw is None:
        return text or "", False
    rest = " ".join(raw_toks[end_raw + 1:]).lstrip(",.!?;:-— ").strip()
    return rest, True


# ---------------------------------------------------------------- detectors (pluggable)
class WakeDetector:
    """Protocol: given a short audio window (path or PCM), did the wake phrase occur?"""
    def detect(self, wav_path: str | Path) -> MatchResult:  # pragma: no cover - interface
        raise NotImplementedError


class SttKeywordDetector(WakeDetector):
    """Default backend: transcribe a short window (voice_io.transcribe — faster-whisper
    local by default) and match the phrase. No trained model; re-parameterizable."""

    def __init__(self, matcher: Optional[WakePhraseMatcher] = None, backend: Optional[str] = None):
        self.matcher = matcher or WakePhraseMatcher()
        self.backend = backend or _cfg("WAKE_STT_BACKEND", None) or _cfg("STT_BACKEND", "local")

    def detect(self, wav_path: str | Path) -> MatchResult:
        import voice_io  # lazy: keeps import of this module network/model-free
        try:
            text = voice_io.transcribe(wav_path, backend=self.backend, language="en")
        except Exception:
            return MatchResult(False, heard="<stt-error>")
        return self.matcher.match(text)


class OpenWakeWordDetector(WakeDetector):
    """Audio-level backend: score a WAV window with the trained openWakeWord model
    (wakeword/CJAP/colab/train_hey_cee_jap.ipynb -> hey_cee_jap.onnx) and fire when
    the peak score clears config.WAKE_OWW_THRESHOLD.

    Unlike SttKeywordDetector this never runs STT: the audio is embedded by
    openwakeword's frozen feature models and scored by the ~200 KB trained head —
    the always-on robot path. Lazy everywhere: importing this module stays
    $0/offline; the model loads on first detect() (plus a one-time ~6 MB download
    of openwakeword's melspectrogram/embedding models into the package if absent).
    """

    def __init__(self, model_path: Optional[str] = None, threshold: Optional[float] = None):
        raw = model_path or _cfg("WAKE_OWW_MODEL_PATH", "")
        p = Path(raw) if raw else None
        if p is not None and not p.is_absolute():
            p = _REPO_ROOT / p
        self.model_path = p
        self.threshold = float(threshold if threshold is not None
                               else _cfg("WAKE_OWW_THRESHOLD", 0.40))
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        if not self.model_path or not self.model_path.exists():
            raise FileNotFoundError(
                f"openWakeWord model not found at {str(self.model_path)!r}. Train it with "
                "wakeword/CJAP/colab/train_hey_cee_jap.ipynb and unzip the bundle into "
                "wakeword/CJAP/models/ (keep the .onnx.data sidecar beside the .onnx), "
                "or point CJ_WAKE_OWW_MODEL_PATH elsewhere.")
        try:
            import openwakeword
            from openwakeword.model import Model
        except ImportError as e:
            raise ImportError("openwakeword backend needs `pip install openwakeword==0.6.0` "
                              "(pulls onnxruntime) in this environment") from e
        res = Path(openwakeword.__file__).parent / "resources" / "models"
        if not (res / "melspectrogram.onnx").exists():
            # Feature models are not bundled in the pip package; one-time ~6 MB fetch.
            openwakeword.utils.download_models(model_names=["hey_jarvis_v0.1"])
        self._model = Model(wakeword_models=[str(self.model_path)],
                            inference_framework="onnx")
        return self._model

    def detect(self, wav_path: str | Path) -> MatchResult:
        import numpy as np
        model = self._load()
        audio = self._read_16k_mono(wav_path)
        # Pad 2 s lead / 0.5 s tail: the model scores a STREAM through a 2 s feature
        # window, so audio shorter than the window ends before the phrase is seen in
        # full context and scores ~0 regardless of content (measured on the validation
        # clips: 0.002 raw vs 0.742 padded, same verified utterance). Mirrors
        # wakeword/CJAP/validate.py.
        audio = np.concatenate([np.zeros(2 * 16000, np.int16), audio,
                                np.zeros(16000 // 2, np.int16)])
        if hasattr(model, "reset"):
            model.reset()
        peak = 0.0
        for i in range(0, len(audio) - 1280 + 1, 1280):
            peak = max(peak, max(model.predict(audio[i:i + 1280]).values()))
        return MatchResult(peak >= self.threshold, variant=self.model_path.stem,
                           score=round(float(peak), 3),
                           heard=f"<audio:{Path(wav_path).name}>")

    @staticmethod
    def _read_16k_mono(wav_path: str | Path):
        """int16 mono 16 kHz from any PCM WAV (browser mics record 44.1/48 kHz)."""
        import wave
        import numpy as np
        with wave.open(str(wav_path), "rb") as w:
            sr, nch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sw == 2:
            a = np.frombuffer(raw, dtype="<i2").astype(np.float32)
        elif sw == 4:
            a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 65536.0
        elif sw == 1:
            a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
        else:
            raise ValueError(f"unsupported WAV sample width: {sw} bytes")
        if nch > 1:
            a = a.reshape(-1, nch).mean(axis=1)
        if sr != 16000:
            try:
                from math import gcd
                from scipy.signal import resample_poly
                g = gcd(sr, 16000)
                a = resample_poly(a, 16000 // g, sr // g)
            except ImportError:               # linear fallback — adequate for a gate
                n = int(round(len(a) * 16000 / sr))
                a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a)
        return np.clip(a, -32768, 32767).astype(np.int16)


def make_detector(backend: Optional[str] = None) -> WakeDetector:
    backend = (backend or _cfg("WAKE_BACKEND", "stt_keyword")).lower()
    if backend in ("stt_keyword", "stt", "keyword"):
        return SttKeywordDetector()
    if backend in ("openwakeword", "oww"):
        return OpenWakeWordDetector()
    raise ValueError(f"unknown WAKE_BACKEND: {backend!r}")


# ---------------------------------------------------------------- audio source (pluggable)
class MicAudioSource:
    """Yield successive short WAV windows from the default mic via sounddevice
    (lazy/optional import). Robot swaps this for its own capture; tests inject frames."""

    def __init__(self, window_s: Optional[float] = None, samplerate: int = 16000):
        self.window_s = float(window_s or _cfg("WAKE_WINDOW_S", 1.5))
        self.samplerate = samplerate

    def windows(self):  # pragma: no cover - needs a real mic
        import tempfile
        import wave
        import numpy as np
        import sounddevice as sd
        frames = int(self.window_s * self.samplerate)
        while True:
            rec = sd.rec(frames, samplerate=self.samplerate, channels=1, dtype="int16")
            sd.wait()
            fd, path = tempfile.mkstemp(suffix=".wav")
            import os
            os.close(fd)
            with wave.open(path, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(self.samplerate)
                w.writeframes(rec.tobytes())
            yield path
            try:
                os.unlink(path)
            except OSError:
                pass


# ---------------------------------------------------------------- the loop
def wait_for_wake(detector: Optional[WakeDetector] = None,
                  windows: Optional[Iterable[str | Path]] = None,
                  on_listen: Optional[Callable[[MatchResult], None]] = None) -> MatchResult:
    """Pull short audio windows until the wake phrase fires; return the MatchResult.
    `windows` is any iterable of wav paths (a MicAudioSource by default). Inject a
    finite iterable in tests. `on_listen` gets every (non-firing) window's result."""
    detector = detector or make_detector()
    if windows is None:
        if not _cfg("WAKE_WORD_ENABLED", False):
            raise RuntimeError("WAKE_WORD_ENABLED is False; set it (config/env) to run the mic loop.")
        windows = MicAudioSource().windows()
    for wav in windows:
        res = detector.detect(wav)
        if res.fired:
            return res
        if on_listen:
            on_listen(res)
    return MatchResult(False, heard="<windows exhausted>")


def run_hands_free_loop(handle_query: Callable[[str], None],
                        detector: Optional[WakeDetector] = None,
                        capture_query: Optional[Callable[[], str]] = None,
                        greet: Optional[Callable[[], None]] = None) -> None:  # pragma: no cover
    """Robot/kiosk hands-free loop. On each wake: (optional greet) -> capture the
    query utterance -> STT -> handle_query(query_text). handle_query runs the pipeline
    (retrieval -> compose -> TTS); this module stays pipeline-agnostic per the seam."""
    detector = detector or make_detector()
    cooldown = float(_cfg("WAKE_COOLDOWN_S", 1.0))
    phrase = _cfg("WAKE_PHRASE", "Cee-Jap")
    print(f"[wake] armed — say “{phrase}”. (Ctrl-C to quit)")
    while True:
        res = wait_for_wake(detector)
        if not res.fired:
            break
        print(f"[wake] fired on {res.variant!r} (heard: {res.heard!r})")
        try:                                    # [head-orient] turn toward the speaker (opt-in, guarded)
            import head_orient
            ho = head_orient.orient_to_wake()   # fixed/hard-coded direction until real DOA lands
            if ho.get("turned"):
                print(f"[head] oriented: yaw={ho['yaw_deg']}° "
                      f"(azimuth={ho['azimuth_deg']}°, {ho['source']})")
        except Exception:
            pass                                # head-orient must never break a turn
        if greet:
            greet()
        query = capture_query() if capture_query else ""
        if query.strip():
            handle_query(query.strip())
        time.sleep(cooldown)


# ---------------------------------------------------------------- CLI / self-test
def _selftest() -> int:
    """$0 offline demo of the matcher on accept/reject cases."""
    m = WakePhraseMatcher()
    print(f"wake phrase: {_cfg('WAKE_PHRASE', 'Cee-Jap')!r}  matcher: {m}")
    accept = ["See-Jap", "hey see jap", "cee jap", "seejap", "see jab", "seejop",
              "okay see-jap what is the rule of law"]
    # legacy "Hey CJ" family retired per WW-5 decision 2026-07-27 —
    # spoken "CJ" ("see jay") must stay silent.
    reject = ["see the map", "what is the rule of law", "see japan", "cheese",
              "the japanese economy", "logic jump", "sea gull", "",
              "see jay", "hey see jay", "cee jay", "cj"]
    ok = True
    print("\nACCEPT (should fire):")
    for t in accept:
        r = m.match(t); ok &= r.fired
        print(f"  {'OK ' if r.fired else 'MISS'}  {t!r:52} -> {r.variant} ({r.score})")
    print("\nREJECT (should NOT fire):")
    for t in reject:
        r = m.match(t); ok &= (not r.fired)
        print(f"  {'OK ' if not r.fired else 'FALSE'}  {t!r:52} -> {r.variant} ({r.score})")
    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    return 0 if ok else 1


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="CJ wake-word front door")
    ap.add_argument("--selftest", action="store_true", help="offline matcher demo ($0)")
    ap.add_argument("--loop", action="store_true", help="live hands-free loop (needs mic + keys)")
    args = ap.parse_args()
    if args.loop:
        raise SystemExit("Run the live loop via `python wake_demo.py` (wires the develop pipeline).")
    raise SystemExit(_selftest())
