"""
W2.x-REBASELINE — arch-baseline-v2: re-baseline the NEW pipeline (adaptive top-p
softmax_temp/0.06, MIN_K=4, streamed composer, max_tokens 640) over the frozen
40-set. Persists ANSWER TEXT per query (for W2.7 TTS replay). native_sdk only.

Gates G1/G2/G3 run first and exit before any token spend on failure.
Usage:  python scripts/run_arch_baseline_v2.py [--gates-only]
"""
from __future__ import annotations
import argparse, json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
import config, retrieval, embeddings, service  # noqa: E402
from run_arch_baseline import gates, FROZEN_SHA  # noqa: E402
from run_baseline import _cost, pctl, PRICE      # noqa: E402

OUT_JSON = ROOT / "arch_baseline_v2.json"
OUT_JSONL = ROOT / "arch_baseline_v2.jsonl"
def did(c): return c.split("::")[0]


def config_snapshot():
    return {"RETRIEVAL_TOP_P_BASIS": config.RETRIEVAL_TOP_P_BASIS,
            "RETRIEVAL_SOFTMAX_TEMP": config.RETRIEVAL_SOFTMAX_TEMP,
            "RETRIEVAL_TOP_P": config.RETRIEVAL_TOP_P, "RETRIEVAL_MIN_K": config.RETRIEVAL_MIN_K,
            "COMPOSER_TOP_K_ceiling": config.COMPOSER_TOP_K, "COMPOSER_MAX_TOKENS": config.COMPOSER_MAX_TOKENS,
            "COMPOSER_MODEL_ID": config.COMPOSER_MODEL_ID,
            "LAMBDA": config.LAMBDA, "RRF_K": config.RRF_K, "OUT_OF_SCOPE_THRESHOLD": config.OUT_OF_SCOPE_THRESHOLD,
            "TOPIC_SOFTMAX_TEMPERATURE": config.TOPIC_SOFTMAX_TEMPERATURE}


def run_one(client, allow, q):
    query = q["query"]
    r = retrieval.run(query, allow)
    tt, route, rr = r["timing"], r["route"], r["retrieval"]
    directives = service._directives(query, route)
    t0 = time.perf_counter()
    comp = service.compose_streamed(query, rr["selected"], directives, client=client)
    composer_ms = round((time.perf_counter() - t0) * 1000, 1)
    nucleus = len(rr["selected"])
    chunks_sent = min(nucleus, config.COMPOSER_TOP_K)
    u = comp["usage"]
    usage = {"input": getattr(u, "input_tokens", 0), "output": getattr(u, "output_tokens", 0),
             "cache_write": getattr(u, "cache_creation_input_tokens", 0),
             "cache_read": getattr(u, "cache_read_input_tokens", 0)} if u else \
        {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    uncached = ((usage["input"] + usage["cache_read"]) * PRICE[0] + usage["output"] * PRICE[1]) / 1e6
    router_ms = round(tt["embed_query_ms"] + tt["route_centroids_ms"], 1)
    total = round(tt["input_gate_ms"] + router_ms + tt["retrieve_rrf_cutoff_ms"] + composer_ms, 1)
    return {"qid": q["id"], "qtype": q["type"], "qtheme": q["theme"], "query": query,
            "input_gate_ms": tt["input_gate_ms"], "router_ms": router_ms,
            "retrieval_ms": tt["retrieve_rrf_cutoff_ms"], "composer_ms": composer_ms,
            "composer_ttft_ms": comp["ttft_ms"], "total_ms": total,
            "nucleus_size": nucleus, "chunks_sent": chunks_sent,
            "retrieved_chunk_ids": [c for c, _, _ in rr["selected"]],
            "routed_topic": route["top_topic"], "routed_theme_cos": route["top_cosine"],
            "in_scope": route["in_scope"], "universe": rr["universe_size"], "aligned": rr["aligned"],
            "llm_calls_before_composition": r["llm_calls_before_composition"],
            "usage": usage, "cost_cached_usd": round(_cost(u), 6) if u else 0.0,
            "cost_uncached_equiv_usd": round(uncached, 6),
            "stop_reason": comp["stop_reason"], "degraded": comp["degraded"],
            "answer": comp["answer"], "envelope": comp["envelope"]}


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--gates-only", action="store_true")
    args = ap.parse_args(argv)
    queries, transport = gates()
    print("[G4] config:", json.dumps(config_snapshot()))
    if args.gates_only:
        print("[gates-only] all gates passed; not spending."); return 0

    allow = service._allowlist("v4")
    client = service._client()
    # WARM (cold-start separate)
    t0 = time.perf_counter(); embeddings.get_model(); cold_load = round((time.perf_counter() - t0) * 1000, 1)
    t0 = time.perf_counter(); w1 = run_one(client, allow, {"id": "w1", "type": "warm", "theme": "A", "query": "What is the rule of law?"})
    first_call = round((time.perf_counter() - t0) * 1000, 1)
    run_one(client, allow, {"id": "w2", "type": "warm", "theme": "B", "query": "Tell me about liberty and prosperity."})
    if w1["composer_ttft_ms"] is None:
        print("[G2] STOP: warm stream produced no chunk.", file=sys.stderr); return 2
    cold = {"model_cold_load_ms": cold_load, "first_call_total_ms_incl_connection": first_call,
            "note": "EXCLUDED from warmed p50/p95."}
    print(f"[cold-start] model_load={cold_load}ms first_call={first_call}ms (excluded)")

    recs = []
    with open(OUT_JSONL, "w", encoding="utf-8", newline="\n") as fh:
        for q in queries:
            rec = run_one(client, allow, q)
            recs.append(rec)
            fh.write(json.dumps({k: v for k, v in rec.items() if k != "answer"}, ensure_ascii=config.JSON_ENSURE_ASCII) + "\n")
            print(f"  {q['id']:4} total={rec['total_ms']:>8} ttft={str(rec['composer_ttft_ms']):>7} "
                  f"nucleus={rec['nucleus_size']:>2} sent={rec['chunks_sent']:>2} out={rec['usage']['output']:>4} "
                  f"stop={str(rec['stop_reason']):10} llm_pre={rec['llm_calls_before_composition']}")

    succ = [r for r in recs if not r["degraded"]]
    def col(k): return [r[k] for r in succ]
    stages = ["input_gate_ms", "router_ms", "retrieval_ms", "composer_ms", "composer_ttft_ms", "total_ms"]
    summ = {s: {"p50": pctl(col(s), 50), "p95": pctl(col(s), 95)} for s in stages}
    all_zero = all(r["llm_calls_before_composition"] == 0 for r in recs)
    in_scope_n = sum(1 for r in recs if r["in_scope"])
    spot = next(r for r in recs if r["qid"] == "A1")
    answers_persisted = sum(1 for r in recs if r.get("answer"))
    out = {
        "anchor": "arch-baseline-v2 (adaptive top-p softmax_temp/0.06 MIN_K=4 + streamed composer 640)",
        "NOT_comparable_to_v1_on_composer_axis": "retrieval (flat12->adaptive nucleus) AND composer "
            "(MAX_TOKENS 300->640, +directives, streamed) both changed; v2 is the new comparator.",
        "frozen_set_sha256": FROZEN_SHA, "n_queries": len(recs),
        "n_measured": len(succ), "n_degraded": len(recs) - len(succ),
        "transport": transport, "embed_device": config.EMBED_DEVICE, "config_snapshot": config_snapshot(),
        "stages_p50_p95_ms": summ, "ttft_ms": summ["composer_ttft_ms"], "total_e2e_ms": summ["total_ms"],
        "chunks_sent": {"mean": round(float(np.mean(col("chunks_sent"))), 2),
                        "p50": pctl(col("chunks_sent"), 50), "min": min(col("chunks_sent")),
                        "max": max(col("chunks_sent")), "old_flat": config.COMPOSER_TOP_K},
        "nucleus_size_mean": round(float(np.mean(col("nucleus_size"))), 2),
        "cost_per_query_usd": {"mean_cached": round(float(np.mean(col("cost_cached_usd"))), 6),
                               "mean_uncached_equiv": round(float(np.mean(col("cost_uncached_equiv_usd"))), 6)},
        "total_run_cost_usd_cached": round(float(np.sum(col("cost_cached_usd"))), 6),
        "cold_start": cold,
        "verify": {"llm_calls_before_composition_all_zero": all_zero, "in_scope_count": in_scope_n,
                   "out_of_scope_count": 40 - in_scope_n,
                   "parity_A1": {"routed_topic": spot["routed_topic"], "routed_cos": spot["routed_theme_cos"],
                                 "universe": spot["universe"], "aligned": spot["aligned"]},
                   "answer_text_persisted": f"{answers_persisted}/{len(recs)}"},
        "run_timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "queries": recs,
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n", encoding=config.OUTPUT_ENCODING)
    print("\n=== arch-baseline-v2 (warmed p50/p95 ms | measured %d/40) ===" % len(succ))
    for s in stages:
        print(f"  {s:18} p50={summ[s]['p50']:>9} p95={summ[s]['p95']:>9}")
    print(f"chunks_sent mean={out['chunks_sent']['mean']} (old flat 12) | nucleus mean={out['nucleus_size_mean']}")
    print(f"cost/q cached=${out['cost_per_query_usd']['mean_cached']} uncached=${out['cost_per_query_usd']['mean_uncached_equiv']} "
          f"| total=${out['total_run_cost_usd_cached']}")
    print(f"[VERIFY] llm_pre==0 all: {all_zero} | in_scope {in_scope_n}/40 | answers {answers_persisted}/40 | "
          f"parity A1 {spot['routed_topic']} cos {spot['routed_theme_cos']} univ {spot['universe']}")
    print(f"wrote {OUT_JSON.name}")
    return 0 if all_zero else 3


if __name__ == "__main__":
    raise SystemExit(main())
