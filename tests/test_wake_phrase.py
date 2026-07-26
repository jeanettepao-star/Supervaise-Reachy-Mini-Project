"""Wake-phrase matcher + detector plumbing test (offline, $0).

The wake phrase "See-Jap" / "Hey Cee-Jap" is an OOV word Whisper mishears many ways;
the matcher must fire on the whole family (see jap / cee jap / seejap / cj / see jay /
seejop) and stay silent on near-misses (see the map / see japan / cheese / logic jump).

Standalone (exits non-zero on failure): .venv/Scripts/python.exe tests/test_wake_phrase.py
Pytest-compatible.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import wake_word  # noqa: E402
from wake_word import WakePhraseMatcher, SttKeywordDetector  # noqa: E402

# Whisper mishears of "See-Jap" / "Hey Cee-Jap" that MUST fire:
ACCEPT = [
    "See-Jap", "see jap", "Hey Cee-Jap", "hey see jap", "hey, see-jap!",
    "cee jap", "see jab", "cee jab", "sea jap", "see jip", "see jop", "see jay",
    "cee jay", "seejap", "ceejap", "cjap", "seejop", "seejay", "ceejay",
    "CJ", "cj", "hey cj", "okay see-jap, what is the rule of law",
    "hey cee jap tell me about the foundation",
]

# Near-misses that MUST NOT fire:
REJECT = [
    "", "   ", "see the map", "what is the rule of law", "see japan",
    "the japanese economy", "cheese", "sea gull", "logic jump", "see you later",
    "jump", "teenager", "the sea", "say japan please", "c sharp", "cheesecake",
]


def test_accept_all_variants():
    m = WakePhraseMatcher()
    misses = [t for t in ACCEPT if not m.match(t).fired]
    assert not misses, f"wake phrase failed to fire on: {misses}"


def test_reject_near_misses():
    m = WakePhraseMatcher()
    false = [t for t in REJECT if m.match(t).fired]
    assert not false, f"wake phrase FALSE-fired on: {false}"


def test_match_reports_variant_and_score():
    m = WakePhraseMatcher()
    r = m.match("hey see jap")
    assert r.fired and r.variant and 0.0 < r.score <= 1.0 and r.heard == "hey see jap"


def test_custom_phrase_is_parameterizable():
    # The matcher is driven by the variants list (seam: wake_phrase is a named param).
    m = WakePhraseMatcher(variants=["computer", "hal"])
    assert m.match("computer").fired and not m.match("see jap").fired


def test_detector_plumbing_with_mocked_stt(monkeypatch=None):
    """SttKeywordDetector transcribes a window then matches — verify end-to-end offline
    by faking voice_io.transcribe (no audio, no model, no network)."""
    fake = types.ModuleType("voice_io")
    heard = {"text": "hey see jap"}
    fake.transcribe = lambda path, backend=None, language=None: heard["text"]
    sys.modules["voice_io"] = fake
    try:
        det = SttKeywordDetector()
        assert det.detect("dummy.wav").fired, "detector should fire on 'hey see jap'"
        heard["text"] = "what is the rule of law"
        assert not det.detect("dummy.wav").fired, "detector should stay silent on a normal query"
        # an STT error must never fire and never raise
        fake.transcribe = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stt down"))
        assert not det.detect("dummy.wav").fired
    finally:
        sys.modules.pop("voice_io", None)


CASES = [
    ("accept all See-Jap variants", test_accept_all_variants),
    ("reject near-misses", test_reject_near_misses),
    ("match reports variant + score", test_match_reports_variant_and_score),
    ("custom phrase is parameterizable", test_custom_phrase_is_parameterizable),
    ("detector plumbing (mocked STT)", test_detector_plumbing_with_mocked_stt),
]


def main() -> int:
    print(f"=== wake-phrase test ({WakePhraseMatcher()}) ===")
    ok = True
    for name, fn in CASES:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            ok = False
            print(f"  FAIL  {name}: {e}")
    print(f"\n{'ALL PASS' if ok else 'FAILURES'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
