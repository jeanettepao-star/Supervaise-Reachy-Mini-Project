"""ENVELOPE guard test (Phase-1 diagnosis, 2026-07-24).

Verifies the PRODUCTION function that splits the composer stream into TTS-bound
prose vs the trailing ENVELOPE metadata: voice_stream.SentenceChunker. On the live
voice path (app/voice_job.py) the composer's streamed text flows

    compose_streamed on_text -> chunker.feed(piece) -> submit(sent) -> TTS

and the trailing ENVELOPE (after config.COMPOSER_ENVELOPE_SENTINEL) must NEVER reach
a TTS call. SentenceChunker.feed() suppresses everything from the sentinel onward
(voice_stream.py:49) and holds a partial tail until flush() (voice_stream.py:65).
We drive that function DIRECTLY (never a copy of its logic), exactly as the live
path drives it (feed each streamed piece, then flush), and collect the TTS-bound
chunks.

Assertions (per required case):
  * no ENVELOPE bytes (the sentinel, or any envelope-JSON marker) ever appear in the
    TTS-bound text;
  * the prose is never truncated by the split (spoken == prose, whitespace-normalized).

Required cases (1-4): well-formed, split-across-chunks, malformed/truncated JSON,
and a negative control (ENVELOPE-LIKE text inside prose must survive). Case 5 is an
additional edge probe (sentinel itself truncated mid-token at stream end); its result
is REPORTED, not fixed here (boundary rule 2).

Run standalone (exits non-zero on failure of a required case):
    .venv/Scripts/python.exe tests/test_envelope_never_spoken.py
Pytest-compatible: the test_* functions below are collected normally.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import config          # noqa: E402
import voice_stream    # noqa: E402

SENTINEL = config.COMPOSER_ENVELOPE_SENTINEL


# --------------------------------------------------------------------------- helpers
def spoken_chunks(pieces):
    """Drive SentenceChunker EXACTLY as app/voice_job.py does: feed each streamed
    piece, then flush the tail. Returns (list_of_tts_chunks, joined_text)."""
    ch = voice_stream.SentenceChunker()
    out = []
    for p in pieces:
        out += ch.feed(p)
    out += ch.flush()          # live path: `for sent in chunker.flush(): submit(sent)`
    return out, " ".join(out)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _stream_pieces(raw: str, size: int = 17):
    """Slice raw into fixed-size streamed pieces (deterministic, size-independent)."""
    return [raw[i:i + size] for i in range(0, len(raw), size)]


def assert_no_envelope(joined: str, markers):
    assert SENTINEL not in joined, f"SENTINEL leaked into TTS text: {joined!r}"
    for m in markers:
        assert m not in joined, f"envelope marker {m!r} leaked into TTS text: {joined!r}"


def assert_prose_intact(joined: str, prose: str):
    got, want = _norm(joined), _norm(prose)
    assert got == want, f"prose altered/truncated by the split:\n  want={want!r}\n  got ={got!r}"


# --------------------------------------------------------------------------- cases
def test_case1_well_formed():
    """1. Well-formed answer + well-formed trailing ENVELOPE."""
    prose = ("The rule of law is the foundation of a just society. "
             "It restrains power and protects the weak from the strong.")
    env = SENTINEL + '\n{"doc_ids_cited": ["CA242"], "register_used": "A"}'
    raw = prose + "\n" + env
    _, joined = spoken_chunks(_stream_pieces(raw))
    assert_no_envelope(joined, ["CA242", "doc_ids_cited", "register_used", "{", "}"])
    assert_prose_intact(joined, prose)


def test_case2_sentinel_split_across_chunks():
    """2. ENVELOPE split across stream-chunk boundaries (the realistic streaming case)."""
    prose = ("Prosperity and liberty are twin beacons. "
             "Neither survives long without the other.")
    tail = "\n" + SENTINEL + '\n{"doc_ids_cited": ["CA100"]}'
    raw = prose + tail
    # Force the split to land INSIDE the sentinel: cut 6 chars into "---ENVELOPE---".
    cut = raw.find(SENTINEL) + 6
    pieces = [raw[:cut], raw[cut:]]
    _, joined = spoken_chunks(pieces)
    assert_no_envelope(joined, ["CA100", "doc_ids_cited", "ENVELOPE", "{", "}"])
    assert_prose_intact(joined, prose)


def test_case3_malformed_truncated_json():
    """3. Malformed / truncated ENVELOPE (sentinel present, JSON garbled + cut off)."""
    prose = "A judge reasons from the record, not from the noise of the day."
    raw = prose + "\n" + SENTINEL + '\n{"doc_ids_cited": ["CA2'   # JSON truncated mid-string
    _, joined = spoken_chunks(_stream_pieces(raw))
    assert_no_envelope(joined, ["CA2", "doc_ids_cited", "{", "["])
    assert_prose_intact(joined, prose)


def test_case4_negative_control_envelope_like_prose():
    """4. Negative control: ENVELOPE-LIKE text quoted INSIDE prose must NOT be stripped.
    The guard keys on the EXACT sentinel, not on the word 'envelope'."""
    prose = ('I once described the ENVELOPE of judicial discretion as narrow; '
             'the word envelope, and even a dash — like this, belong in the answer.')
    raw = prose + "\n" + SENTINEL + '\n{"doc_ids_cited": []}'
    _, joined = spoken_chunks(_stream_pieces(raw))
    # the sentinel + JSON are stripped, but the prose (incl. 'ENVELOPE'/'envelope') survives
    assert SENTINEL not in joined
    assert "doc_ids_cited" not in joined
    assert "ENVELOPE of judicial discretion" in joined, "negative control: prose word stripped!"
    assert "the word envelope" in joined, "negative control: prose word stripped!"
    assert_prose_intact(joined, prose)


def probe_case5_truncated_sentinel_tail():
    """5. EDGE PROBE (reported, not fixed): the SENTINEL itself is truncated at stream
    end (model cut mid-token by max_tokens). feed() only suppresses the COMPLETE
    sentinel (voice_stream.py:49); a partial tail is held and then EMITTED by flush()
    (voice_stream.py:65-68). Returns (leaked: bool, joined_text)."""
    prose = "This is the complete spoken answer."
    raw = prose + "\n---ENV"          # partial sentinel; a full SENTINEL never appears
    _, joined = spoken_chunks(_stream_pieces(raw))
    leaked = "---ENV" in joined
    return leaked, joined


# --------------------------------------------------------------------------- runner
REQUIRED = [
    ("1 well-formed", test_case1_well_formed),
    ("2 sentinel split across chunks", test_case2_sentinel_split_across_chunks),
    ("3 malformed/truncated JSON", test_case3_malformed_truncated_json),
    ("4 negative control (envelope-like prose)", test_case4_negative_control_envelope_like_prose),
]


def main() -> int:
    print(f"=== ENVELOPE guard test — SENTINEL={SENTINEL!r} — target voice_stream.SentenceChunker ===")
    ok = True
    for name, fn in REQUIRED:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            ok = False
            print(f"  FAIL  {name}: {e}")
    # edge probe — result reported; does NOT gate the required-case verdict
    leaked, joined = probe_case5_truncated_sentinel_tail()
    if leaked:
        print(f"  FINDING  5 truncated-sentinel tail LEAKS to TTS via flush() "
              f"(voice_stream.py:49 suppresses only the COMPLETE sentinel; flush() "
              f"voice_stream.py:65-68 emits the partial tail). spoken={joined!r} "
              f"-> Phase-2 hardening item (rare: needs truncation inside the 14-char sentinel).")
    else:
        print(f"  PROBE-OK 5 truncated-sentinel tail did not leak: {joined!r}")
    print(f"\nREQUIRED CASES {'ALL PASS' if ok else 'HAVE FAILURES'} "
          f"(case-5 edge leak={leaked}; reported, not fixed)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
