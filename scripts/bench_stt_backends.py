"""bench_stt_backends.py — measure faster-whisper (local) vs OpenAI whisper-1
(cloud) on the frozen 3-clip SAPI harness in eval/results/stt_bench_clips/.

Emits eval/results/w3_12_stt_local_vs_openai_bench.json + .md so the config
default flip (STT_BACKEND=openai -> local) is grounded in a committed
measurement, not a vibe.

Timing convention: `first_call_ms` includes the CTranslate2 cold-load or
OpenAI TLS-warmup penalty a fresh process pays exactly once; `warm_ms` is
the steady-state pure-transcription time (what the demo pays on Q2+).

Usage:
    python scripts/bench_stt_backends.py
    STT_BACKEND=local python scripts/bench_stt_backends.py     # (env is ignored, both are always run)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

# .env resolution — the demo wrapper loads from app/.env; do the same here so the
# OpenAI leg has its key without the operator exporting it manually.
try:
    from dotenv import load_dotenv
    for _p in (ROOT / "app" / ".env", ROOT / ".env"):
        if _p.exists():
            load_dotenv(_p, override=False)
except Exception:
    pass

import config  # noqa: E402
import voice_io  # noqa: E402

CLIPS_DIR = ROOT / "eval" / "results" / "stt_bench_clips"
OUT_JSON = ROOT / "eval" / "results" / "w3_12_stt_local_vs_openai_bench.json"
OUT_MD = ROOT / "eval" / "results" / "w3_12_stt_local_vs_openai_bench.md"

# Frozen 3-clip harness. Reference text = SAPI-spoken text (exact source strings
# in scripts/gen_stt_bench_clips.ps1). Diff is word-level Levenshtein.
CLIPS = [
    ("q1_flp.wav",       "What is the foundation for liberty and prosperity?"),
    ("q2_baron.wav",     "What is baron travel?"),
    ("q3_dont_know.wav", "I don't know."),
]


def _norm(text: str) -> str:
    """Lowercase + strip terminal punctuation for a fair diff."""
    return " ".join(text.lower().replace("?", "").replace(".", "").replace(",", "").split())


def _word_edit_distance(a: str, b: str) -> int:
    aw, bw = _norm(a).split(), _norm(b).split()
    if not aw:
        return len(bw)
    if not bw:
        return len(aw)
    prev = list(range(len(bw) + 1))
    for i, wa in enumerate(aw, 1):
        cur = [i] + [0] * len(bw)
        for j, wb in enumerate(bw, 1):
            cur[j] = min(cur[j - 1] + 1,
                          prev[j] + 1,
                          prev[j - 1] + (0 if wa == wb else 1))
        prev = cur
    return prev[-1]


def _bench_backend(name: str, transcribe_fn) -> dict:
    per_clip = []
    t_first_start = time.perf_counter()
    for i, (fname, ref) in enumerate(CLIPS):
        path = CLIPS_DIR / fname
        t0 = time.perf_counter()
        hyp = transcribe_fn(path)
        ms = int((time.perf_counter() - t0) * 1000)
        wer = _word_edit_distance(ref, hyp)
        n_ref = len(_norm(ref).split())
        per_clip.append({
            "clip": fname,
            "ref": ref,
            "hyp": hyp,
            "ms": ms,
            "word_edits_vs_ref": wer,
            "ref_word_count": n_ref,
            "wer_pct": round(100 * wer / max(1, n_ref), 1),
        })
    total_ms = int((time.perf_counter() - t_first_start) * 1000)
    warm_ms_median = sorted([c["ms"] for c in per_clip[1:]])[len(per_clip[1:]) // 2] if len(per_clip) > 1 else per_clip[0]["ms"]
    return {
        "backend": name,
        "per_clip": per_clip,
        "first_call_ms": per_clip[0]["ms"],
        "warm_ms_median": warm_ms_median,
        "total_run_ms": total_ms,
        "total_word_edits": sum(c["word_edits_vs_ref"] for c in per_clip),
    }


def main():
    if not CLIPS_DIR.is_dir() or not all((CLIPS_DIR / c).exists() for c, _ in CLIPS):
        print(f"[FAIL] missing bench clips in {CLIPS_DIR} — run scripts\\gen_stt_bench_clips.ps1 first")
        sys.exit(2)

    results = {
        "harness_version": "1.0",
        "clips_dir": str(CLIPS_DIR.relative_to(ROOT)).replace("\\", "/"),
        "clips": [c for c, _ in CLIPS],
        "config": {
            "STT_BACKEND_at_run": config.STT_BACKEND,
            "LOCAL_STT_MODEL": config.LOCAL_STT_MODEL,
            "LOCAL_STT_COMPUTE": config.LOCAL_STT_COMPUTE,
            "LOCAL_STT_DEVICE": config.LOCAL_STT_DEVICE,
            "OPENAI_STT_MODEL": config.OPENAI_STT_MODEL,
        },
        "backends": [],
    }

    print("[bench] running LOCAL (faster-whisper small/int8/cpu)…")
    results["backends"].append(_bench_backend("local", voice_io.transcribe_local))

    print("[bench] running OPENAI (whisper-1)…")
    results["backends"].append(_bench_backend("openai", voice_io.transcribe_openai))

    OUT_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    md = ["# STT backend bench — local (faster-whisper) vs OpenAI whisper-1",
          "", f"Harness: {results['clips_dir']}  |  clips: {', '.join(results['clips'])}  ",
          f"Config: LOCAL={config.LOCAL_STT_MODEL}/{config.LOCAL_STT_COMPUTE}/{config.LOCAL_STT_DEVICE} · OPENAI={config.OPENAI_STT_MODEL}",
          "",
          "Bench clips are Windows-SAPI stand-ins (scripts/gen_stt_bench_clips.ps1); "
          "they are robotic-timbred and slightly favor accuracy over natural-speech "
          "latency on both engines. Re-run on human clips before making a hardware-",
          "specific final call.",
          "", "## Per-clip transcription (ms) and text diff",
          "", "| clip | ref | local_ms | local_hyp | oai_ms | oai_hyp |",
          "|---|---|---|---|---|---|"]
    local, oai = results["backends"]
    for lc, oc in zip(local["per_clip"], oai["per_clip"]):
        md.append(
            f"| {lc['clip']} | {lc['ref']} | **{lc['ms']}** | {lc['hyp']} | **{oc['ms']}** | {oc['hyp']} |")
    md += ["", "## Summary",
           "",
           f"- **local (faster-whisper {config.LOCAL_STT_MODEL}/{config.LOCAL_STT_COMPUTE}/{config.LOCAL_STT_DEVICE})**: "
           f"first-call {local['first_call_ms']}ms (cold CT2 load), "
           f"warm median {local['warm_ms_median']}ms, total edits {local['total_word_edits']}",
           f"- **openai (whisper-1 cloud)**: first-call {oai['first_call_ms']}ms, "
           f"warm median {oai['warm_ms_median']}ms, total edits {oai['total_word_edits']}",
           ""]
    winner = "local" if local["warm_ms_median"] < oai["warm_ms_median"] else "openai"
    md.append(f"**Warm-median latency winner (Q2+ felt): `{winner}`.**  "
              f"Accuracy: local={local['total_word_edits']} vs openai={oai['total_word_edits']} "
              "total word edits (SAPI harness — small sample).")
    md += ["",
           "## Config default disposition",
           "",
           f"Per the task rule (\"if local wins, leave STT_BACKEND=local\"): the bench",
           f"outcome above sets `config.STT_BACKEND`'s shipping default. This bench",
           f"was run on the build laptop (Zen+ APU per CLAUDE.md); the local warm",
           f"median may drop below OpenAI on a faster CPU (Reachy Mini Pi 5, modern",
           f"demo host) — re-bench there before the final flip.",
           "",
           "## MC#8 preemption (delivery week)",
           "",
           "Regardless of the latency winner, `STT_BACKEND=local` now unblocks the",
           "offline-ready path: the demo can transcribe with zero network + zero API",
           "spend by flipping one env var, so a Wi-Fi/API outage during delivery week",
           "cannot brick the STT stage. Same transcript-confirm contract, filler",
           "sequencer untouched.",
           ""]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"[bench] wrote {OUT_JSON.name}, {OUT_MD.name}")
    print(f"[bench] warm-median: local={local['warm_ms_median']}ms  openai={oai['warm_ms_median']}ms  -> winner={winner}")


if __name__ == "__main__":
    main()
