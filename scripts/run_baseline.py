"""
W1.9 — warmed latency baseline over the draft-query set (native_sdk transport).

Per-stage timing (input_gate -> router -> retrieval -> composer), TTFT measured
separately via the native SDK stream, warm-up before measuring (cold model-load +
first-connection excluded and reported separately). Writes JSON-lines per query +
baseline.json (p50/p95 per stage + TTFT + total, cost/query, transport, device).

Config-driven; no tuning. STOPS if transport != native_sdk.

Usage:  python scripts/run_baseline.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import config
sys.path.insert(0, str(PROJECT_ROOT / "app"))
import retrieval  # noqa: E402
import embeddings  # noqa: E402
import service  # noqa: E402 — importing injects truststore for native TLS

DRAFT = PROJECT_ROOT / "reports" / "pilot-eval subset" / "draft_queries_v1.json"
OUT_JSONL = PROJECT_ROOT / "baseline.jsonl"
OUT_JSON = PROJECT_ROOT / "baseline.json"

# Sonnet 4.6 pricing $/MTok: (input, output, cache_write_5m, cache_read)
PRICE = (3.00, 15.00, 3.75, 0.30)


def _cost(u) -> float:
    inp = getattr(u, "input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    cw = getattr(u, "cache_creation_input_tokens", 0) or 0
    cr = getattr(u, "cache_read_input_tokens", 0) or 0
    return (inp * PRICE[0] + out * PRICE[1] + cw * PRICE[2] + cr * PRICE[3]) / 1e6


def _client():
    import anthropic
    return anthropic.Anthropic(max_retries=config.MAX_RETRIES, api_key=service._api_key())


def stream_compose(client, voice, payload):
    """Streamed composition. Returns (text, ttft_ms, total_ms, usage)."""
    t0 = time.perf_counter(); ttft = None; parts = []
    with client.messages.stream(
            model=config.COMPOSER_MODEL_ID, max_tokens=config.MAX_TOKENS,
            system=[{"type": "text", "text": voice, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": payload}]) as s:
        for chunk in s.text_stream:
            if ttft is None:
                ttft = (time.perf_counter() - t0) * 1000
            parts.append(chunk)
        usage = s.get_final_message().usage
    return "".join(parts), round(ttft, 1), round((time.perf_counter() - t0) * 1000, 1), usage


def run_one(client, voice, allow, query):
    r = retrieval.run(query, allow)
    tt = r["timing"]
    directives = service._directives(query, r["route"])
    payload = service.build_payload(query, r["retrieval"]["selected"], directives)
    text, ttft, ctotal, usage = stream_compose(client, voice, payload)
    router_ms = round(tt["embed_query_ms"] + tt["route_centroids_ms"], 1)
    total = round(tt["input_gate_ms"] + router_ms + tt["retrieve_rrf_cutoff_ms"] + ctotal, 1)
    return {
        "query": query, "gate": r["gate"]["scope"],
        "input_gate_ms": tt["input_gate_ms"], "router_ms": router_ms,
        "embed_query_ms": tt["embed_query_ms"], "retrieval_ms": tt["retrieve_rrf_cutoff_ms"],
        "composer_ms": ctotal, "composer_ttft_ms": ttft, "total_ms": total,
        "n_chunks": len(r["retrieval"]["selected"]),
        "route_top": r["route"]["top_topic"], "route_cos": r["route"]["top_cosine"],
        "universe": r["retrieval"]["universe_size"], "aligned": r["retrieval"]["aligned"],
        "llm_calls_before_composition": r["llm_calls_before_composition"],
        "usage": {"input": getattr(usage, "input_tokens", 0),
                  "output": getattr(usage, "output_tokens", 0),
                  "cache_write": getattr(usage, "cache_creation_input_tokens", 0),
                  "cache_read": getattr(usage, "cache_read_input_tokens", 0)},
        "cost_usd": round(_cost(usage), 6),
        "transport": service._resolve_transport(), "embed_device": config.EMBED_DEVICE,
    }


def pctl(vals, p):
    return round(float(np.percentile(vals, p)), 1) if vals else None


def main() -> int:
    transport = service._resolve_transport()
    if transport != "native_sdk":
        print(f"[baseline] STOP: transport={transport} (not native_sdk). Refusing to "
              "baseline on the curl path.", file=sys.stderr)
        return 2
    allow = service._allowlist("v4")
    queries = json.loads(DRAFT.read_text(encoding="utf-8"))["queries"]
    client = _client()
    voice = service._voice_card()

    # ---- COLD START (reported separately, EXCLUDED from steady-state) ----
    t0 = time.perf_counter(); embeddings.get_model(); cold_load = round((time.perf_counter() - t0) * 1000, 1)
    t0 = time.perf_counter(); run_one(client, voice, allow, "What is the rule of law?")
    first_call = round((time.perf_counter() - t0) * 1000, 1)   # incl. first SDK TLS connection
    # second warm-up (>=2 total) so the measured run is steady-state
    run_one(client, voice, allow, "Tell me about liberty and prosperity.")
    cold = {"model_cold_load_ms": cold_load, "first_call_total_ms_incl_connection": first_call,
            "note": "EXCLUDED from the warmed p50/p95 baseline below."}
    print(f"[baseline] cold-start (excluded): model_load={cold_load}ms, "
          f"first_call(incl connection)={first_call}ms")

    # ---- MEASURED run (warm) ----
    records = []
    with open(OUT_JSONL, "w", encoding="utf-8", newline="\n") as fh:
        for q in queries:
            rec = run_one(client, voice, allow, q.get("text") or q["query"])
            rec["qid"] = q["id"]; rec["qtype"] = q["type"]; rec["qtheme"] = q["theme"]
            records.append(rec)
            fh.write(json.dumps(rec, ensure_ascii=config.JSON_ENSURE_ASCII) + "\n")
            print(f"[baseline] {q['id']} total={rec['total_ms']}ms ttft={rec['composer_ttft_ms']}ms "
                  f"(gate={rec['gate']} route={rec['route_top']})")

    def col(k):
        return [r[k] for r in records]
    stages = ["input_gate_ms", "router_ms", "retrieval_ms", "composer_ms", "composer_ttft_ms", "total_ms"]
    summary = {s: {"p50": pctl(col(s), 50), "p95": pctl(col(s), 95)} for s in stages}

    # cost: the warm-ups write the voice-card cache, so every MEASURED query is a
    # cache READ. "cached" = observed cost. "uncached_equiv" = the same token mix
    # with the cache_read tokens repriced as full input (i.e. caching disabled).
    cached = col("cost_usd")
    def _uncached_equiv(u):
        return ((u["input"] + u["cache_read"]) * PRICE[0] + u["output"] * PRICE[1]) / 1e6
    uncached = [_uncached_equiv(r["usage"]) for r in records]
    baseline = {
        "transport": transport, "embed_device": config.EMBED_DEVICE,
        "composer_model": config.COMPOSER_MODEL_ID, "n_queries": len(records),
        "draft_query_set": "draft_queries_v1 (CONSTRUCTED stand-in — no frozen set existed)",
        "stages_p50_p95_ms": summary,
        "ttft_ms": summary["composer_ttft_ms"],
        "total_e2e_ms": summary["total_ms"],
        "cost_per_query_usd": {
            "cached_p50": round(float(np.percentile(cached, 50)), 6),
            "uncached_equiv_p50": round(float(np.percentile(uncached, 50)), 6),
            "caching_saves_per_query_p50": round(
                float(np.percentile(uncached, 50) - np.percentile(cached, 50)), 6),
            "note": ("measured queries are all cache READS (warm-ups wrote the cache); "
                     "uncached_equiv = cache_read tokens repriced as full input"),
            "prompt_caching": "present (voice card cache_control: ephemeral)"},
        "cold_start": cold,
        "sanity": {"llm_calls_before_composition": records[0]["llm_calls_before_composition"],
                   "route_top": records[0]["route_top"], "route_cos": records[0]["route_cos"],
                   "universe": records[0]["universe"], "aligned": records[0]["aligned"]},
        "build_date": "2026-06-30",
    }
    OUT_JSON.write_text(json.dumps(baseline, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
                        encoding=config.OUTPUT_ENCODING)

    print("\n=== WARMED BASELINE (p50 / p95 ms) ===")
    for s in stages:
        print(f"  {s:18} p50={summary[s]['p50']:>8}  p95={summary[s]['p95']:>8}")
    cpq = baseline["cost_per_query_usd"]
    print(f"cost/query p50: cached=${cpq['cached_p50']} uncached_equiv=${cpq['uncached_equiv_p50']} "
          f"(caching saves ${cpq['caching_saves_per_query_p50']}/query)")
    print(f"transport={transport} embed_device={config.EMBED_DEVICE} | wrote {OUT_JSON.name} + {OUT_JSONL.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
