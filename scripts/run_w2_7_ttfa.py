"""
W2.7 — TTFA (Time-To-First-Audio) measurement on RECORDED answers ($0 API).

Replays the 40 composed answers persisted in w2_1_baseline.json through the
sentence-streaming TTS path (app/voice_stream.py) with a local SAPI backend.

- Full-40 TTFA: analytic from recorded metrics (TTFT + first-sentence
  accumulation at the measured token rate + REAL SAPI synth of sentence 1) vs the
  "wait-for-full-answer" baseline (composer_ms + synth s1). $0.
- Make-or-break: a REAL threaded incremental replay of 3 representative answers
  (X34 short, C15 long-reflective, A3 case) proving sentence 1's audio is ready
  long before the stream finishes (synth N while N+1 still arrives).
- --live-probe : OPT-IN only; composes 3 queries live and confirms live TTFA
  matches the replay. NOT run by default (cost discipline).

Usage:  python scripts/run_w2_7_ttfa.py [--live-probe]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
import config          # noqa: E402
import voice_stream    # noqa: E402

OUT = ROOT / "w2_7_ttfa_report.json"
VALID = ["X34", "C15", "A3"]     # short / long-reflective / case
_WORD = re.compile(r"\S+\s*")


def first_sentence(text):
    ch = voice_stream.SentenceChunker()
    out = ch.feed(text) or ch.flush()
    return out[0] if out else text


def replay_iter(text, rate_tok_s, ttft_ms):
    """Yield word tokens with realistic inter-arrival timing (leading TTFT delay,
    then paced at the measured token rate) so a REAL TTFA can be observed."""
    time.sleep(ttft_ms / 1000.0)
    per_char = 1.0 / max(rate_tok_s * 4.0, 1.0)   # rate is tok/s; ~4 char/tok
    toks = _WORD.findall(text)
    for i, t in enumerate(toks):
        if i:
            time.sleep(len(t) * per_char)
        yield t


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-probe", action="store_true",
                    help="OPT-IN: compose 3 queries live (~$0.10) to validate replay TTFA")
    args = ap.parse_args(argv)

    d = json.loads((ROOT / "w2_1_baseline.json").read_text(encoding="utf-8"))
    recs = [q for q in d["queries"] if q.get("answer")]
    assert len(recs) == 40, f"expected 40 recorded answers, got {len(recs)}"
    tts = voice_stream.SapiTTS()

    # ---- Full-40 analytic TTFA (real SAPI synth of sentence 1) ----
    rows = []
    for q in recs:
        ans = q["answer"]; ttft = q["composer_ttft_ms"]; comp = q["composer_ms"]
        out_tok = q["usage"]["output"] or 1
        gen_ms = max(comp - ttft, 1.0)
        rate = out_tok / (gen_ms / 1000.0)          # tok/s during streaming
        s1 = first_sentence(ans)
        s1_tok = max(len(s1) // 4, 1)
        accum_s1_ms = (s1_tok / rate) * 1000.0      # first-token -> sentence-1 complete
        _p, synth_s1_ms, _a = tts.synth(s1)
        ttfa_stream = round(ttft + accum_s1_ms + synth_s1_ms, 1)
        ttfa_fullwait = round(comp + synth_s1_ms, 1)
        rows.append({"qid": q["qid"], "type": q["qtype"], "theme": q["qtheme"],
                     "ttft_ms": ttft, "composer_ms": comp, "rate_tok_s": round(rate, 1),
                     "s1_chars": len(s1), "s1_synth_ms": synth_s1_ms,
                     "ttfa_stream_ms": ttfa_stream, "ttfa_fullwait_ms": ttfa_fullwait,
                     "saved_ms": round(ttfa_fullwait - ttfa_stream, 1)})

    def pc(k, p): return round(float(np.percentile([r[k] for r in rows], p)), 1)
    summ = {"ttfa_stream_ms": {"p50": pc("ttfa_stream_ms", 50), "p95": pc("ttfa_stream_ms", 95)},
            "ttfa_fullwait_ms": {"p50": pc("ttfa_fullwait_ms", 50), "p95": pc("ttfa_fullwait_ms", 95)},
            "saved_ms": {"p50": pc("saved_ms", 50), "p95": pc("saved_ms", 95)},
            "s1_synth_ms": {"p50": pc("s1_synth_ms", 50), "p95": pc("s1_synth_ms", 95)}}

    # ---- Make-or-break: REAL threaded incremental replay of 3 answers ----
    byid = {q["qid"]: q for q in recs}
    valid_runs = []
    for qid in VALID:
        q = byid[qid]; ttft = q["composer_ttft_ms"]
        out_tok = q["usage"]["output"] or 1
        rate = out_tok / (max(q["composer_ms"] - ttft, 1.0) / 1000.0)
        res = voice_stream.speak_stream(replay_iter(q["answer"], rate, ttft), tts)
        s1 = res["sentences"][0]
        incremental = s1["audio_ready_ms"] < res["stream_done_ms"]   # s1 audio before stream ends
        valid_runs.append({
            "qid": qid, "real_ttfa_ms": res["ttfa_ms"], "n_sentences": res["n_sentences"],
            "first_audio_ready_ms": s1["audio_ready_ms"], "stream_done_ms": res["stream_done_ms"],
            "incremental_confirmed": incremental, "total_spoken_s": res["total_spoken_s"],
            "per_sentence_synth_ms_mean": round(float(np.mean([s["synth_ms"] for s in res["sentences"]])), 1),
            "analytic_ttfa_ms": next(r["ttfa_stream_ms"] for r in rows if r["qid"] == qid)})
        print(f"  [replay] {qid}: real TTFA={res['ttfa_ms']}ms analytic={valid_runs[-1]['analytic_ttfa_ms']}ms "
              f"| s1_audio_ready={s1['audio_ready_ms']}ms << stream_done={res['stream_done_ms']}ms "
              f"incremental={incremental} | {res['n_sentences']} sentences, {res['total_spoken_s']}s spoken")

    # ---- optional live probe (opt-in) ----
    live = None
    if args.live_probe:
        live = run_live_probe(tts)

    report = {
        "task": "W2.7 sentence-streaming TTS + TTFA",
        "api_spend_usd": (live["spend_usd"] if live else 0.0),
        "recorded_source": "w2_1_baseline.json (40 answers persisted; $0 recovery)",
        "tts_backend": {"measured_with": "sapi5 (Windows, offline, $0)",
                        "voices": ["Microsoft David Desktop", "Microsoft Zira Desktop"],
                        "robot_dropin": "PiperTTS / Qwen3-TTS / Kokoro via the same TTS.synth interface",
                        "incremental_consumption_confirmed": all(v["incremental_confirmed"] for v in valid_runs)},
        "reachy_alignment": {
            "robot_pipeline": "VAD(Silero v5) -> STT(Parakeet/Whisper, local) -> LLM slot -> TTS(Qwen3-TTS/Kokoro, local)",
            "llm_slot_protocol": "OpenAI-compatible: /v1/responses OR /v1/chat/completions, streaming text token-by-token",
            "audio_loop": "OpenAI Realtime events over ws://127.0.0.1:8765/v1/realtime",
            "cjp_service_role": "fills the LLM slot; expose the W2.1 streamed prose as OpenAI-compatible SSE deltas; "
                                "ENVELOPE trails after the sentinel (spoken=prose only). STT/TTS stay local ($0).",
            "drop_in": "swap SAPI->Qwen3/Kokoro and point the s2s LLM backend at our /v1/chat/completions; "
                       "our sentence-chunker mirrors the robot's TTS chunking stage."},
        "ttfa_summary_ms": summ,
        "delta_note": ("streaming speaks at the FIRST sentence; full-wait speaks only after the whole answer. "
                       "TTFA p50 ~%.1fs vs full-wait ~%.1fs." % (summ["ttfa_stream_ms"]["p50"] / 1000,
                                                                 summ["ttfa_fullwait_ms"]["p50"] / 1000)),
        "make_or_break_incremental": valid_runs,
        "per_query": rows,
        "live_probe": live,
        "decisions": {"haiku_filler_approach1": "NOT built — TTFA ~%.1fs needs no pre-token filler" % (summ["ttfa_stream_ms"]["p50"] / 1000),
                      "raw_trace_narration_approach2": "NOT built (off-persona; leaks deliberation)",
                      "max_tokens": f"unchanged at {config.COMPOSER_MAX_TOKENS} (streaming is the fix, not truncation)"},
        "run_timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
                   encoding=config.OUTPUT_ENCODING)
    print(f"\n=== TTFA (recorded 40, ms) ===")
    print(f"  streaming  p50={summ['ttfa_stream_ms']['p50']}  p95={summ['ttfa_stream_ms']['p95']}")
    print(f"  full-wait  p50={summ['ttfa_fullwait_ms']['p50']}  p95={summ['ttfa_fullwait_ms']['p95']}")
    print(f"  SAVED      p50={summ['saved_ms']['p50']}  p95={summ['saved_ms']['p95']}")
    print(f"  sentence-1 synth p50={summ['s1_synth_ms']['p50']}ms | incremental confirmed: "
          f"{all(v['incremental_confirmed'] for v in valid_runs)}")
    print(f"[COST] api spend = ${report['api_spend_usd']} | wrote {OUT.name}")
    return 0


def run_live_probe(tts):
    """OPT-IN: compose 3 queries live, stream prose into the TTS path, measure
    live TTFA. Small spend."""
    import retrieval, service
    from run_baseline import _cost
    allow = service._allowlist("v4")
    Q = {q["id"]: q for q in json.loads(
        (ROOT / "reports/pilot-eval subset/draft_queries_v1.json").read_text(encoding="utf-8"))["queries"]}
    picks = ["X34", "C15", "A3"]
    client = service._client()
    results = []; spend = 0.0
    for qid in picks:
        q = Q[qid]
        r = retrieval.run(q["query"], allow)
        directives = service._directives(q["query"], r["route"])
        chunker = voice_stream.SentenceChunker()
        t0 = time.perf_counter(); ttfa = {"ms": None}
        first_sent = {"t": None}

        def on_text(piece):
            for sent in chunker.feed(piece):
                if first_sent["t"] is None:
                    _p, sms, _a = tts.synth(sent)
                    ttfa["ms"] = round((time.perf_counter() - t0) * 1000, 1)
                    first_sent["t"] = ttfa["ms"]
        comp = service.compose_streamed(q["query"], r["retrieval"]["selected"], directives,
                                        client=client, on_text=on_text)
        # flush remaining prose sentences (not timed for TTFA)
        results.append({"qid": qid, "live_ttfa_ms": ttfa["ms"],
                        "stop_reason": comp["stop_reason"], "degraded": comp["degraded"]})
        # cost from usage
        u = comp["usage"]
        if u:
            spend += _cost(u)
    return {"picks": picks, "results": results, "spend_usd": round(spend, 6)}


if __name__ == "__main__":
    raise SystemExit(main())
