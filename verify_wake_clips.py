"""WAKE-REC-1 Phase 2 — replay verification of recorded wake clips.

For every .wav in evidence/wake_clips/, run the file through the CURRENT STT backend ->
the PRODUCTION matcher (imports app.wake_word — never copies its logic), derive the
expected FIRE/SILENT from the wake_pos_/wake_neg_ filename prefix, append one row per
clip to clip_manifest.md (with the RAW STT transcript), and FAIL (exit non-zero) on any
mismatch. A pos-clip that mishears toward the retired "see jay" is a FINDING for a
separate reviewed variant-add + enunciation coaching — this tool never edits the matcher.

  Replay:  python verify_wake_clips.py
  Self-check (no audio/STT): python verify_wake_clips.py --simulate --manifest <scratch>
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import wake_word  # noqa: E402  (production matcher/detector — never duplicated)

CLIPS_DIR = ROOT / "evidence" / "wake_clips"
MANIFEST_DEFAULT = CLIPS_DIR / "clip_manifest.md"
# canned transcripts for --simulate: pos-hit, pos-miss (misheard toward retired see-jay), neg-silent
SIMULATE = [
    ("wake_pos_ceejap_normal_sim_t1.wav", "cee jap"),
    ("wake_pos_ceejap_soft_sim.wav",      "see jay"),
    ("wake_neg_conversation_sim.wav",     "what is the rule of law today"),
]


def expected_from_name(fn: str):
    if fn.startswith("wake_pos_"):
        return "FIRE"
    if fn.startswith("wake_neg_"):
        return "SILENT"
    return None


def parse_name(fn: str):
    """wake_pos_ceejap_normal_<speaker>_t1.wav -> (form, speaker, take). Assumes a
    single-token speaker id (the recorder stamps --speaker verbatim)."""
    stem = fn[:-4] if fn.endswith(".wav") else fn
    body = stem.split("_")[2:]                      # drop 'wake' + 'pos'/'neg'
    take = ""
    if body and re.fullmatch(r"t\d+", body[-1]):
        take, body = body[-1][1:], body[:-1]
    speaker = body[-1] if body else "?"
    form = "_".join(body[:-1]) if len(body) > 1 else (body[0] if body else "?")
    return form, speaker, take


def _row(fn, speaker, form, take, expected, observed, transcript, date):
    return f"| {fn} | {speaker} | {form} | {take or '-'} | {expected} | {observed} | {transcript!r} | {date} |"


def evaluate(items, use_stt: bool):
    """items: list of (filename, transcript_or_wavpath). Returns (rows, results)."""
    matcher = wake_word.make_detector().matcher       # the production matcher
    detector = wake_word.make_detector() if use_stt else None
    date = datetime.now().strftime("%Y-%m-%d")
    rows, results = [], []
    for fn, payload in items:
        expected = expected_from_name(fn)
        if use_stt:
            res = detector.detect(payload)            # payload = wav path; STT + match
        else:
            res = matcher.match(payload)              # payload = canned transcript
        observed = "FIRE" if res.fired else "SILENT"
        form, speaker, take = parse_name(fn)
        rows.append(_row(fn, speaker, form, take, expected, observed, res.heard, date))
        results.append({"fn": fn, "expected": expected, "observed": observed,
                        "transcript": res.heard, "variant": res.variant})
    return rows, results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replay-verify recorded wake clips vs the production matcher.")
    ap.add_argument("--simulate", action="store_true", help="headless: 3 canned transcripts, no audio/STT")
    ap.add_argument("--manifest", default=str(MANIFEST_DEFAULT), help="manifest to append rows to")
    ap.add_argument("--clips", default=str(CLIPS_DIR), help="clips dir (default: evidence/wake_clips/)")
    args = ap.parse_args(argv)

    if args.simulate:
        print("[simulate] 3 canned transcripts through the production matcher + manifest writer")
        rows, results = evaluate(SIMULATE, use_stt=False)
    else:
        wavs = sorted(glob.glob(str(Path(args.clips) / "*.wav")))
        if not wavs:
            print(f"No .wav clips in {args.clips}/ yet — record them with "
                  f"`python record_wake_clips.py --speaker <name>` first.")
            return 0
        print(f"[replay] {len(wavs)} clips via STT_BACKEND -> production matcher")
        rows, results = evaluate([(Path(w).name, w) for w in wavs], use_stt=True)

    # append rows to the manifest (extends the markdown table)
    with open(args.manifest, "a", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")

    # scoring
    mism = [r for r in results if r["expected"] != r["observed"]]
    mishears = [r for r in results if r["expected"] == "FIRE" and r["observed"] == "SILENT"
                and re.search(r"\b(see|cee)\s*jay\b|jay", (r["transcript"] or "").lower())]
    print(f"\nclips: {len(results)}  ·  matches: {len(results)-len(mism)}  ·  mismatches: {len(mism)}")
    print(f"manifest rows appended -> {args.manifest}")
    if mishears:
        print("\n⚠️  MISHEARD toward the RETIRED \"see jay\" family (FINDING, do NOT re-accept the variant —")
        print("    remedy is enunciation coaching for the speaker):")
        for r in mishears:
            print(f"    {r['fn']}: STT heard {r['transcript']!r} -> stayed SILENT (correct per WW-5)")
    if mism:
        print("\n=== MISMATCH TABLE (pos went silent OR neg fired) ===")
        print("| clip | expected | observed | STT transcript |")
        print("|---|---|---|---|")
        for r in mism:
            print(f"| {r['fn']} | {r['expected']} | {r['observed']} | {r['transcript']!r} |")
        print("\nMismatched transcripts are FINDINGS for a separate reviewed variant-add — "
              "not fixed here (matcher/variants untouched).")
        return 1
    print("\nALL CLIPS MATCH EXPECTATION.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
