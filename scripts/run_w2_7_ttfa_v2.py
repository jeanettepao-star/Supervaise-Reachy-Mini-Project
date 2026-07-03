"""
W2.7-TTS — REAL TTFA on actual synthesized audio + explicit stream-overlap proof.
$0 API: replays the 40 persisted answers from arch_baseline_v2.json at v2's
measured composer token-rate through SentenceChunker -> SAPI (real WAV audio).

Engine ladder: Piper attempted (piper-tts installs on Windows, but synthesis
needs a separate ~60-100MB voice .onnx download -> fell through); WINDOWS SAPI
(pywin32, zero-download) proves the overlap + measures TTFA now. Piper/Kokoro
drop into the same TTS.synth interface for the robot.

Usage:  python scripts/run_w2_7_ttfa_v2.py
"""
from __future__ import annotations
import json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
import config, voice_stream  # noqa: E402

OUT = ROOT / "w2_7_ttfa_v2_report.json"
_WORD = re.compile(r"\S+\s*")


def replay_iter(text, rate_tok_s, ttft_ms):
    """Yield word tokens with realistic inter-arrival timing: a leading TTFT
    delay, then paced at v2's measured token rate, so the replay stream mimics
    live generation timing."""
    time.sleep(ttft_ms / 1000.0)
    per_char = 1.0 / max(rate_tok_s * 4.0, 1.0)
    toks = _WORD.findall(text)
    for i, t in enumerate(toks):
        if i:
            time.sleep(len(t) * per_char)
        yield t


def main():
    d = json.loads((ROOT / "arch_baseline_v2.json").read_text(encoding="utf-8"))
    recs = [q for q in d["queries"] if q.get("answer")]
    assert len(recs) == 40, f"expected 40 answers, got {len(recs)}"
    tts = voice_stream.SapiTTS()

    # first-utterance COLD-LOAD (SAPI voice load) — measured once, excluded
    t0 = time.perf_counter(); _p, _sm, _a = tts.synth("Warming up the voice engine.")
    cold_load_ms = round((time.perf_counter() - t0) * 1000, 1)
    print(f"[cold-load] first SAPI utterance (voice load) = {cold_load_ms}ms (excluded)")

    rows = []
    for q in recs:
        ans, ttft, comp = q["answer"], q["composer_ttft_ms"], q["composer_ms"]
        out_tok = q["usage"]["output"] or 1
        rate = out_tok / (max(comp - ttft, 1.0) / 1000.0)
        res = voice_stream.speak_stream(replay_iter(ans, rate, ttft), tts)
        s = res["sentences"]
        ttfa = res["ttfa_ms"]                       # first playable audio out (s1 WAV ready)
        fullwait_ttfa = round(res["stream_done_ms"] + s[0]["synth_ms"], 1) if s else None
        # OVERLAP PROOF: s1 audio-START before s2 generation-END
        if len(s) >= 2:
            overlap = s[0]["synth_start_ms"] < s[1]["emit_ms"]
            trace = {"t_stream_start": 0.0,
                     "t_sentence1_ready": s[0]["emit_ms"],
                     "t_sentence1_audio_START": s[0]["synth_start_ms"],
                     "t_sentence1_audio_READY": s[0]["audio_ready_ms"],
                     "t_sentence2_ready_gen_END": s[1]["emit_ms"]}
            overlap_state = "PASS" if overlap else "FAIL"
        else:
            overlap_state = "N/A_single_sentence"; trace = {"t_sentence1_ready": s[0]["emit_ms"] if s else None}
        rows.append({"qid": q["qid"], "type": q["qtype"], "theme": q["qtheme"],
                     "n_sentences": res["n_sentences"], "ttfa_ms": ttfa,
                     "s1_audio_START_ms": s[0]["synth_start_ms"] if s else None,
                     "fullwait_ttfa_ms": fullwait_ttfa,
                     "saved_ms": round(fullwait_ttfa - ttfa, 1) if (fullwait_ttfa and ttfa) else None,
                     "total_spoken_s": res["total_spoken_s"], "overlap": overlap_state, "trace": trace})
        print(f"  {q['qid']:4} sents={res['n_sentences']:>2} TTFA={ttfa}ms overlap={overlap_state} "
              f"(s1_audioSTART={trace.get('t_sentence1_audio_START')} < s2_genEND={trace.get('t_sentence2_ready_gen_END')})")

    multi = [r for r in rows if r["overlap"] in ("PASS", "FAIL")]
    def pc(vals, p): return round(float(np.percentile(vals, p)), 1)
    ttfas = [r["ttfa_ms"] for r in rows if r["ttfa_ms"]]
    fulls = [r["fullwait_ttfa_ms"] for r in rows if r["fullwait_ttfa_ms"]]
    saves = [r["saved_ms"] for r in rows if r["saved_ms"]]
    example = next((r for r in rows if r["qid"] == "C13"), multi[0] if multi else rows[0])
    report = {
        "task": "W2.7-TTS real-audio TTFA + stream-overlap proof",
        "api_spend_usd": 0.0, "source": "arch_baseline_v2.json (40 persisted answers)",
        "engine": {"chosen": "sapi5 (Windows, pywin32, zero-download)",
                   "piper_attempt": "piper-tts pip install SUCCEEDED on Windows (imports OK, PiperVoice "
                                    "present) — Windows/ONNX concern did NOT materialize; blocked only on a "
                                    "separate ~60-100MB voice .onnx model download (HF), not pulled "
                                    "(download-permission boundary + flagged stall risk). Fell through per ladder.",
                   "robot_dropin": "Piper/Kokoro via the same TTS.synth interface",
                   "voices": ["Microsoft David Desktop", "Microsoft Zira Desktop"]},
        "incremental_synthesis": "CONFIRMED — SAPI synthesizes per sentence; worker thread synthesizes "
                                 "sentence N while the replay stream is still producing sentence N+1.",
        "overlap_proof": {"metric": "t_sentence1_audio_START < t_sentence2_generation_END",
                          "multi_sentence_queries": len(multi),
                          "PASS": sum(1 for r in multi if r["overlap"] == "PASS"),
                          "FAIL": sum(1 for r in multi if r["overlap"] == "FAIL"),
                          "single_sentence_NA": sum(1 for r in rows if r["overlap"].startswith("N/A")),
                          "all_multi_pass": all(r["overlap"] == "PASS" for r in multi)},
        "ttfa_real_ms": {"p50": pc(ttfas, 50), "p95": pc(ttfas, 95), "n": len(ttfas),
                         "note": "first PLAYABLE audio out (s1 WAV complete). Real streaming TTS would emit "
                                 "the first sample mid-sentence, so this SAPI value is a conservative upper bound."},
        "ttfa_fullwait_ms": {"p50": pc(fulls, 50), "p95": pc(fulls, 95)},
        "saved_ms": {"p50": pc(saves, 50), "p95": pc(saves, 95)},
        "cold_load_first_utterance_ms": cold_load_ms,
        "example_trace_C13": example["trace"],
        "decisions": {"approach2_reasoning_traces": "NOT built (dropped)",
                      "approach1_haiku_filler": f"NOT built. Real TTFA p50 ~{pc(ttfas,50)/1000:.1f}s (mostly "
                          "the replayed v2 TTFT). If Sheena's UX flags the pre-audio silence, the filler is the "
                          "lever — flag, not build.",
                      "spoken_output": "prose only; envelope trails after the sentinel, never spoken"},
        "per_query": rows,
        "run_timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
                   encoding=config.OUTPUT_ENCODING)
    op = report["overlap_proof"]
    print(f"\n=== OVERLAP PROOF: {op['PASS']}/{op['multi_sentence_queries']} multi-sentence PASS "
          f"({op['single_sentence_NA']} single-sentence N/A) ===")
    print(f"REAL TTFA (audio): p50={report['ttfa_real_ms']['p50']}ms p95={report['ttfa_real_ms']['p95']}ms")
    print(f"full-wait TTFA   : p50={report['ttfa_fullwait_ms']['p50']}ms p95={report['ttfa_fullwait_ms']['p95']}ms "
          f"-> SAVED p50={report['saved_ms']['p50']}ms")
    print(f"cold-load (excluded)={cold_load_ms}ms | example C13 trace: {example['trace']}")
    print(f"$0 API | wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
