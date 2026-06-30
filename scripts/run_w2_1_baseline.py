"""
W2.1 — measure the production streamed composer (max_tokens cap + length
discipline + trailing ENVELOPE + retries/degradation) over the SAME frozen
40-query set (sha 65492b65), warmed, native_sdk. Same schema as arch_baseline.

Truncation guardrail: ZERO legitimate answers may be cut (stop_reason==max_tokens
or mid-sentence). Config DEFAULTS for retrieval; NO threshold tuning.

Usage:  python scripts/run_w2_1_baseline.py
"""
from __future__ import annotations

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
import config            # noqa: E402
import retrieval         # noqa: E402
import embeddings        # noqa: E402
import service           # noqa: E402
from run_arch_baseline import gates, FROZEN_SHA  # noqa: E402  (reuse the 3 gates)
from run_baseline import _cost, pctl, PRICE       # noqa: E402

OUT_JSON = ROOT / "w2_1_baseline.json"
OUT_JSONL = ROOT / "w2_1_baseline.jsonl"


def run_one(client, allow, qrec):
    query = qrec["query"]
    r = retrieval.run(query, allow)
    tt, route, rr = r["timing"], r["route"], r["retrieval"]
    directives = service._directives(query, route)
    t0 = time.perf_counter()
    comp = service.compose_streamed(query, rr["selected"], directives, client=client)
    composer_ms = round((time.perf_counter() - t0) * 1000, 1)
    router_ms = round(tt["embed_query_ms"] + tt["route_centroids_ms"], 1)
    total = round(tt["input_gate_ms"] + router_ms + tt["retrieve_rrf_cutoff_ms"] + composer_ms, 1)
    usage = comp["usage"]
    u = {"input": getattr(usage, "input_tokens", 0), "output": getattr(usage, "output_tokens", 0),
         "cache_write": getattr(usage, "cache_creation_input_tokens", 0),
         "cache_read": getattr(usage, "cache_read_input_tokens", 0)} if usage else \
        {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    cached = round(_cost(usage), 6) if usage else 0.0
    uncached = round(((u["input"] + u["cache_read"]) * PRICE[0] + u["output"] * PRICE[1]) / 1e6, 6)
    prose = comp["answer"]
    # robust: a sentence-ender optionally followed by closing quotes/brackets
    ends_clean = bool(re.search(r'[.!?…][\")\'’”\]]*$', prose.rstrip()))
    hit_max = comp["stop_reason"] == "max_tokens"
    return {
        "answer": prose,
        "qid": qrec["id"], "qtype": qrec["type"], "qtheme": qrec["theme"], "query": query,
        "input_gate_ms": tt["input_gate_ms"], "router_ms": router_ms,
        "retrieval_ms": tt["retrieve_rrf_cutoff_ms"], "composer_ms": composer_ms,
        "composer_ttft_ms": comp["ttft_ms"], "total_ms": total,
        "routed_topic": route["top_topic"], "routed_theme_cos": route["top_cosine"],
        "in_scope": route["in_scope"], "n_chunks": len(rr["selected"]),
        "retrieved_chunk_ids": [c for c, _, _ in rr["selected"]],
        "universe": rr["universe_size"], "aligned": rr["aligned"],
        "llm_calls_before_composition": r["llm_calls_before_composition"],
        "usage": u, "cost_cached_usd": cached, "cost_uncached_equiv_usd": uncached,
        "stop_reason": comp["stop_reason"], "degraded": comp["degraded"],
        "hit_max_tokens": hit_max, "ends_clean": ends_clean,
        "truncated": bool(hit_max or (not ends_clean and not comp["degraded"])),
        "envelope": comp["envelope"], "answer_chars": len(prose),
        "raw": comp["raw"],
    }


def main() -> int:
    queries, transport = gates()
    allow = service._allowlist("v4")
    client = service._client()

    # ---- WARM (cold-start reported SEPARATELY) ----
    t0 = time.perf_counter(); embeddings.get_model()
    cold_load = round((time.perf_counter() - t0) * 1000, 1)
    t0 = time.perf_counter()
    w1 = run_one(client, allow, {"id": "warm1", "type": "warm", "theme": "A",
                                 "query": "What is the rule of law?"})
    first_call = round((time.perf_counter() - t0) * 1000, 1)
    run_one(client, allow, {"id": "warm2", "type": "warm", "theme": "B",
                            "query": "Tell me about liberty and prosperity."})
    if w1["composer_ttft_ms"] is None:
        print("[G2] STOP: stream produced no chunk.", file=sys.stderr); return 2
    print(f"[G2] stream first chunk (warm TTFT={w1['composer_ttft_ms']}ms) -> PASS")
    cold = {"model_cold_load_ms": cold_load, "first_call_total_ms_incl_connection": first_call,
            "note": "EXCLUDED from the warmed p50/p95 percentiles."}
    print(f"[cold-start] model_load={cold_load}ms first_call(incl TLS)={first_call}ms (excluded)")

    # ---- MEASURE 40 (light inter-query pacing to avoid bursting the rate limit;
    #      the pause is OUTSIDE the per-query timed region, so it never enters the
    #      latency percentiles) ----
    records = []
    with open(OUT_JSONL, "w", encoding="utf-8", newline="\n") as fh:
        for i, q in enumerate(queries):
            rec = run_one(client, allow, q)
            records.append(rec)
            slim = {k: v for k, v in rec.items() if k != "raw"}
            fh.write(json.dumps(slim, ensure_ascii=config.JSON_ENSURE_ASCII) + "\n")
            print(f"  {q['id']:4} total={rec['total_ms']:>8}ms ttft={str(rec['composer_ttft_ms']):>7} "
                  f"out={rec['usage']['output']:>4}tok stop={str(rec['stop_reason']):10} "
                  f"trunc={rec['truncated']} llm_pre={rec['llm_calls_before_composition']}")
            if i < len(queries) - 1:
                time.sleep(1.0)

    # percentiles/cost over SUCCESSFUL (non-degraded) records only; degraded
    # rows are reported separately so a transient API fault can't pollute the anchor.
    succ = [r for r in records if not r["degraded"]]
    def col(k): return [r[k] for r in succ]
    stages = ["input_gate_ms", "router_ms", "retrieval_ms", "composer_ms", "composer_ttft_ms", "total_ms"]
    summary = {s: {"p50": pctl(col(s), 50), "p95": pctl(col(s), 95)} for s in stages}
    mean_cached = round(float(np.mean(col("cost_cached_usd"))), 6)
    mean_uncached = round(float(np.mean(col("cost_uncached_equiv_usd"))), 6)
    total_cost = round(float(np.sum(col("cost_cached_usd"))), 6)

    all_zero = all(r["llm_calls_before_composition"] == 0 for r in records)
    in_scope_n = sum(1 for r in records if r["in_scope"])
    trunc = [r["qid"] for r in succ if r["hit_max_tokens"]]
    midsent = [r["qid"] for r in succ if not r["ends_clean"]]
    degraded = [r["qid"] for r in records if r["degraded"]]
    env_ok = sum(1 for r in succ if r["envelope"] and "doc_ids_cited" in r["envelope"])
    spot = next((r for r in succ if r["qid"] == "A1"), succ[0] if succ else records[0])

    # pick a long reflective answer as the streamed-prose + envelope example
    c_succ = [r for r in succ if r["qtheme"] == "C"]
    ex = max(c_succ or succ, key=lambda r: r["usage"]["output"]) if succ else None

    out = {
        "anchor": "w2.1 (production streamed composer: cap + length discipline + trailing envelope)",
        "compared_against": "arch-baseline (immutable W1 anchor)",
        "frozen_set_sha256": FROZEN_SHA, "n_queries": len(records),
        "n_measured": len(succ), "n_degraded": len(degraded), "degraded_qids": degraded,
        "transport": transport, "embed_device": config.EMBED_DEVICE,
        "composer_model": config.COMPOSER_MODEL_ID,
        "composer_governance": {
            "COMPOSER_MAX_TOKENS": config.COMPOSER_MAX_TOKENS,
            "COMPOSER_TARGET_PARAGRAPHS": config.COMPOSER_TARGET_PARAGRAPHS,
            "COMPOSER_TIMEOUT_S": config.COMPOSER_TIMEOUT_S,
            "COMPOSER_MAX_RETRIES": config.COMPOSER_MAX_RETRIES,
            "COMPOSER_BACKOFF_BASE_S": config.COMPOSER_BACKOFF_BASE_S,
            "envelope_sentinel": config.COMPOSER_ENVELOPE_SENTINEL},
        "config_defaults": {"LAMBDA": config.LAMBDA, "TAU": config.TAU, "RRF_K": config.RRF_K,
                            "MIN_K": config.MIN_K, "MAX_K": config.MAX_K,
                            "OUT_OF_SCOPE_THRESHOLD": config.OUT_OF_SCOPE_THRESHOLD,
                            "TOPIC_SOFTMAX_TEMPERATURE": config.TOPIC_SOFTMAX_TEMPERATURE},
        "stages_p50_p95_ms": summary,
        "ttft_ms": summary["composer_ttft_ms"], "total_e2e_ms": summary["total_ms"],
        "cost_per_query_usd": {"mean_cached": mean_cached, "mean_uncached_equiv": mean_uncached,
                               "prompt_caching": "present (system block cache_control: ephemeral)"},
        "total_run_cost_usd_cached": total_cost,
        "cold_start": cold,
        "truncation_check": {"hit_max_tokens": trunc, "mid_sentence_end_turn": midsent,
                             "degraded": degraded,
                             "legitimate_truncations": len(trunc) + len(midsent),
                             "PASS": (len(trunc) + len(midsent)) == 0},
        "envelope_parsed_ok": f"{env_ok}/{len(records)}",
        "verify": {"llm_calls_before_composition_all_zero": all_zero,
                   "in_scope_count": in_scope_n, "out_of_scope_count": 40 - in_scope_n,
                   "parity_spotcheck": {"qid": "A1", "routed_topic": spot["routed_topic"],
                                        "routed_cos": spot["routed_theme_cos"],
                                        "universe": spot["universe"], "aligned": spot["aligned"]}},
        "example": ({"qid": ex["qid"], "query": ex["query"], "prose": ex["answer"],
                     "envelope": ex["envelope"], "stop_reason": ex["stop_reason"],
                     "output_tokens": ex["usage"]["output"]} if ex else None),
        "run_timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "queries": [{k: v for k, v in r.items() if k != "raw"} for r in records],
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
                        encoding=config.OUTPUT_ENCODING)

    print(f"\n=== W2.1 (warmed p50/p95, ms) | measured {len(succ)}/40, degraded {len(degraded)} ===")
    if degraded:
        print(f"  *** WARNING: {len(degraded)} queries DEGRADED (API transient): {degraded} — "
              "percentiles are over the successful subset; re-run for a clean 40/40 anchor. ***")
    for s in stages:
        print(f"  {s:18} p50={summary[s]['p50']:>9}  p95={summary[s]['p95']:>9}")
    print(f"cost/query: cached=${mean_cached} uncached-equiv=${mean_uncached} | total=${total_cost}")
    print(f"[VERIFY] llm_pre==0 all 40: {all_zero} | in_scope {in_scope_n}/40 | envelope {env_ok}/40")
    print(f"[TRUNCATION] hit_max_tokens={trunc} mid_sentence={midsent} -> "
          f"{'PASS (0 truncated)' if not (trunc or midsent) else 'FAIL'}")
    if ex:
        print(f"\n--- EXAMPLE ({ex['qid']}) streamed prose ---\n{ex['answer']}\n"
              f"--- trailing ENVELOPE ---\n{json.dumps(ex['envelope'], ensure_ascii=False)}")
    print(f"\nwrote {OUT_JSON.name} + {OUT_JSONL.name}")
    if not all_zero:
        print("STOP: an LLM call happened before composition.", file=sys.stderr); return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
