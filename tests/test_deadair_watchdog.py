"""Dead-air watchdog test (Phase-2 fix, Task 2.6).

The dead-air watchdog (app/voice_job.py) is an independent safety net: armed at
transcript-confirm, disarmed by the first enqueue of ANY audio, and — if NOTHING is
enqueued by t_confirm + DEADAIR_WATCHDOG_MS — it force-enqueues a neutral clip so a
turn can never be silent. It lives OUTSIDE the fillers() try-scope, so it fires even
when the fire path throws.

Cases:
  A. fire path THROWS  -> watchdog enqueues within the timeout (no dead air).
  B. normal fire       -> watchdog stays silent; exactly one filler chunk.
  C. race / idempotency -> audio already enqueued before the watchdog -> no-op, no double.

Drives the real voice_job.start_job with $0 stubs (no network). Short real timeouts
with wide margins (the sequencer spawns threads; a fully faked cross-thread clock is
out of scope for this surgical fix — matches the existing Q2 harness pattern).

Standalone (exits non-zero on failure):  .venv/Scripts/python.exe tests/test_deadair_watchdog.py
Pytest-compatible: the test_* functions are collected normally.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import config          # noqa: E402
config.FILLER_V5_ENABLED = True
config.STREAM_TTS_ENABLED = False
config.FILLER_FIRE_MODE = "unconditional"
import voice_job       # noqa: E402


# ---- $0 stubs -----------------------------------------------------------------
class _Speech:
    def create(self, model, voice, input, speed=None, **kw):
        time.sleep(0.02)
        return types.SimpleNamespace(content=b"\xff\xfb\x90\x00" + b"\x00" * 128)


class FakeOAI:
    def __init__(self):
        self.audio = types.SimpleNamespace(speech=_Speech())


class ThrowingDeck:
    """A NEUTRAL deck whose deal() always raises — simulates a fire-path exception."""
    def deal(self):
        raise RuntimeError("forced clip-deal failure")


def working_neutral_deck(n=4):
    return voice_job.Deck([(f"neutral_{i:02d}", b"clipbytes", "mp3", 3.2) for i in range(1, n + 1)])


def stub_compose(ttft_s=1.0, sentences=("The considered answer.",)):
    def _c(q, selected, directives, client=None, on_text=None, **kw):
        time.sleep(ttft_s)
        for s in sentences:
            if on_text:
                on_text(s + " ")
        return {"answer": " ".join(sentences), "envelope": {"doc_ids_cited": ["CA001"]},
                "raw": "", "ttft_ms": 300.0, "stop_reason": "end_turn", "usage": None, "degraded": False}
    return _c


def run_turn(neutral_deck, deadair_ms, content_ttft=1.0):
    config.DEADAIR_WATCHDOG_MS = deadair_ms
    decks = {t: voice_job.Deck([]) for t in voice_job.filler_route.THEMES}
    decks["NEUTRAL"] = neutral_deck
    seq = {"turn": 0, "topic_template_decks": {}}
    job = voice_job.start_job("Q?", "TEST", 0.0, FakeOAI(), set(), None, "onyx", 0, decks, seq,
                              _route_fn=lambda q: {"top_topic": "rule_of_law", "top_cosine": 0.6,
                                                   "in_scope": True, "routed_topics": [("rule_of_law", 0.6)]},
                              _gate_fn=lambda q: {"scope": "in_corpus"},
                              _retrieve_fn=lambda q, a, ri: {"selected": [("CA001::0", 0.9, {})]},
                              _compose_fn=stub_compose(content_ttft))
    while not job["done"]:
        time.sleep(0.01)
    return job


def _filler_chunks(job):
    return [c for c in job["chunks"]
            if str(c.get("clip_id", "")).startswith(("neutral", "theme", "topic", "_deadair"))]


def _no_hole(job):
    idxs = sorted(c["i"] for c in job["chunks"])
    contiguous = (not idxs) or idxs == list(range(idxs[0], idxs[-1] + 1))
    balanced = job["queue_reserved"] == job["queue_submitted"] + job["queue_released"]
    return contiguous and balanced and len(idxs) == len(set(idxs))


# ---- cases --------------------------------------------------------------------
def test_A_fire_throws_watchdog_backstops():
    job = run_turn(ThrowingDeck(), deadair_ms=150, content_ttft=1.0)
    assert job["filler_fire_exception"] == "RuntimeError", "fire path should have thrown"
    assert job["deadair_watchdog_fired"] is True, "watchdog must fire when the fire path threw"
    assert len(job["chunks"]) >= 1 and job["first_chunk_ready_s"] is not None, "no audio enqueued -> dead air!"
    assert job["first_chunk_ready_s"] <= 0.6, f"backstop too slow: {job['first_chunk_ready_s']}s"
    assert _no_hole(job), "reservation invariant violated"


def test_B_normal_fire_watchdog_silent():
    job = run_turn(working_neutral_deck(), deadair_ms=150, content_ttft=1.0)
    assert job["filler_fire_exception"] is None
    assert job["deadair_watchdog_fired"] is False, "watchdog must stay silent when the fire succeeded"
    fc = _filler_chunks(job)
    assert len(fc) == 1, f"expected exactly one filler chunk, got {len(fc)}"
    assert str(fc[0]["clip_id"]).startswith("neutral"), "filler should be the dealt neutral clip"
    assert _no_hole(job)


def test_C_race_no_double_filler():
    # tiny watchdog window: the ~0-2ms unconditional fire still wins; the atomic
    # check-and-fill must prevent a second filler chunk even under the race.
    job = run_turn(working_neutral_deck(), deadair_ms=5, content_ttft=1.0)
    fc = _filler_chunks(job)
    assert len(fc) == 1, f"double-filler under race: {[c['clip_id'] for c in fc]}"
    assert _no_hole(job)


CASES = [("A fire throws -> watchdog backstops", test_A_fire_throws_watchdog_backstops),
         ("B normal fire -> watchdog silent", test_B_normal_fire_watchdog_silent),
         ("C race -> no double filler", test_C_race_no_double_filler)]


def main() -> int:
    print(f"=== dead-air watchdog test (FILLER_FIRE_MODE={config.FILLER_FIRE_MODE}) ===")
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
