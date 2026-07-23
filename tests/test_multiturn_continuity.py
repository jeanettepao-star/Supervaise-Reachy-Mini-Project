"""Multi-turn continuity test (Phase-2c, S2-refutation + T5 per-turn reset).

The Phase-2c multi-turn audio death is BROWSER-side (the gapless component's global
`expected` index can't recover from an iframe remount). This test proves the PYTHON
side is sound: across 8 consecutive start_job turns — replicating the host's
`ss.chunk_base` accumulation — the GLOBAL chunk-index sequence stays contiguous (no
gap, no overlap, no duplicate), every turn produces audio, and every turn resets its
per-turn state. So a cross-turn queue HOLE (suspect S2) is not the cause. Browser-side
recovery (base-clamp in index.html) still needs a live 8-turn session to verify.

$0 stubs (no network / no model load). Follows the Q2 (verify_filler_v5) pattern.

Standalone (exits non-zero on failure): .venv/Scripts/python.exe tests/test_multiturn_continuity.py
Pytest-compatible.
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
import filler_route    # noqa: E402


class _Speech:
    def create(self, model, voice, input, speed=None, **kw):
        time.sleep(0.01)
        return types.SimpleNamespace(content=b"\xff\xfb\x90\x00" + b"\x00" * 128)


class FakeOAI:
    def __init__(self):
        self.audio = types.SimpleNamespace(speech=_Speech())


def stub_route(q):
    return {"top_topic": "rule_of_law", "top_cosine": 0.6, "in_scope": True,
            "routed_topics": [("rule_of_law", 0.6)]}


def stub_compose(q, selected, directives, client=None, on_text=None, **kw):
    time.sleep(0.3)
    for s in ("Sentence one.", "Sentence two."):
        if on_text:
            on_text(s + " ")
    return {"answer": "a", "envelope": {"doc_ids_cited": ["CA001"]}, "raw": "",
            "ttft_ms": 200.0, "stop_reason": "end_turn", "usage": None, "degraded": False}


def neutral_deck(n=4):
    return voice_job.Deck([(f"neutral_{i:02d}", b"clip", "mp3", 3.2) for i in range(1, n + 1)])


def run_session(n_turns=8):
    """Replicate the host's cross-turn chunk_base accumulation over N consecutive turns."""
    seq = {"turn": 0, "topic_template_decks": {}}
    chunk_base = 0
    all_idx, per_turn = [], []
    for t in range(n_turns):
        decks = {x: voice_job.Deck([]) for x in filler_route.THEMES}
        decks["NEUTRAL"] = neutral_deck()
        job = voice_job.start_job(f"Q{t}?", "TEST", 0.0, FakeOAI(), set(), None, "onyx",
                                  chunk_base, decks, seq, _route_fn=stub_route,
                                  _gate_fn=lambda q: {"scope": "in_corpus"},
                                  _retrieve_fn=lambda q, a, ri: {"selected": [("CA001::0", 0.9, {})]},
                                  _compose_fn=stub_compose)
        while not job["done"]:
            time.sleep(0.01)
        idxs = sorted(c["i"] for c in job["chunks"])
        all_idx += idxs
        per_turn.append(job)
        # exact host formula (streamlit_voice_demo.finalize path)
        chunk_base = job["base"] + max(job["n_chunks"], len(job["chunks"]))
    return all_idx, per_turn


def test_indices_contiguous_across_8_turns():
    all_idx, _ = run_session(8)
    assert all_idx, "no chunks produced"
    expected = list(range(all_idx[0], all_idx[-1] + 1))
    assert all_idx == expected, f"cross-turn queue HOLE/overlap (S2): {all_idx}"
    assert len(all_idx) == len(set(all_idx)), f"duplicate indices across turns: {all_idx}"


def test_every_turn_has_audio_and_resets():
    _, per_turn = run_session(8)
    for t, job in enumerate(per_turn):
        assert job["first_chunk_ready_s"] is not None and job["chunks"], f"turn {t}: silent!"
        assert job.get("turn_state_reset") is True, f"turn {t}: per-turn state not reset"
        assert job.get("deadair_watchdog_fired") is False, f"turn {t}: watchdog fired in normal op"


def main() -> int:
    print("=== multi-turn continuity (8 consecutive turns) ===")
    ok = True
    for name, fn in [("indices contiguous across 8 turns (S2 refuted)", test_indices_contiguous_across_8_turns),
                     ("every turn has audio + per-turn reset", test_every_turn_has_audio_and_resets)]:
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
