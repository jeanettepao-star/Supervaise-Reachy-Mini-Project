"""
W1.11 — arch-baseline: first new-arch e2e over the FROZEN 40-query set, the
OFFICIAL W3.3 comparison anchor (NOT the old Haiku-in-path pilot-baseline).

Config DEFAULTS, NO tuning. Three precondition gates run FIRST and exit before
any token spend on failure:
  G1 frozen set intact (frozen==true, n==40, sha256 == FROZEN_SHA)
  G2 transport native_sdk (curl can't stream -> TTFT invalid)
  G3 verify_pin PASS, key present, centroids(34)/pilot_dense(827)/BM25 load

Usage:  python scripts/run_arch_baseline.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
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
# reuse the W1.9 helpers so cost/stream logic does not drift
from run_baseline import stream_compose, _cost, _client, pctl, PRICE  # noqa: E402

FROZEN_SHA = "65492b650aec8dda5e76be21c32aaae3faf61f9663c6c58ace02b5a6c4bc9a63"
QFILE = ROOT / "reports" / "pilot-eval subset" / "draft_queries_v1.json"
OUT_JSON = ROOT / "arch_baseline.json"
OUT_JSONL = ROOT / "arch_baseline.jsonl"


def _did(cid):
    return cid.split("::")[0]


def gates():
    """Return (queries, transport) or exit(non-zero) on any gate failure."""
    # ---- G1: frozen set intact ----
    doc = json.loads(QFILE.read_text(encoding="utf-8"))
    meta, queries = doc["meta"], doc["queries"]
    sha = hashlib.sha256("\n".join(sorted(q["query"] for q in queries)).encode("utf-8")).hexdigest()
    g1 = (meta.get("frozen") is True and meta.get("n") == 40 and len(queries) == 40 and sha == FROZEN_SHA)
    print(f"[G1] frozen={meta.get('frozen')} n={meta.get('n')} len={len(queries)} "
          f"sha={sha[:8]}.. == 65492b65 -> {'PASS' if g1 else 'FAIL'}")
    if not g1:
        print("[G1] STOP: frozen set edited/stale; refusing to baseline.", file=sys.stderr)
        sys.exit(2)

    # ---- G3a: verify_pin ----
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_pin.py")],
                       capture_output=True, text=True)
    pin_ok = "PASS" in (r.stdout + r.stderr)
    print(f"[G3] verify_pin -> {'PASS' if pin_ok else 'FAIL'}")
    if not pin_ok:
        print("[G3] STOP: verify_pin failed.", file=sys.stderr); sys.exit(2)

    # ---- G3b: key present ----
    try:
        service._api_key()
        print("[G3] ANTHROPIC_API_KEY present -> PASS")
    except Exception as e:
        print(f"[G3] STOP: {e}", file=sys.stderr); sys.exit(2)

    # ---- G3c: indexes load (centroids 34 / pilot_dense 827 / BM25) ----
    cen, _ = retrieval._load_centroids()
    mat, dmeta = embeddings.load_dense_index()
    import sparse as _sp
    _sp.sparse_score("rule of law", allowlist=service._allowlist("v4"), k=5)  # forces BM25 load
    g3c = (cen.shape[0] == 34 and mat.shape[0] == 827)
    print(f"[G3] centroids={cen.shape[0]} pilot_dense={mat.shape[0]} BM25=loaded -> "
          f"{'PASS' if g3c else 'FAIL'}")
    if not g3c:
        print("[G3] STOP: index shapes wrong.", file=sys.stderr); sys.exit(2)

    # ---- G2: transport native_sdk ----
    transport = service._resolve_transport()
    print(f"[G2] transport -> {transport} {'PASS' if transport == 'native_sdk' else 'FAIL'}")
    if transport != "native_sdk":
        print("[G2] STOP: not native_sdk; curl can't stream -> TTFT invalid.", file=sys.stderr)
        sys.exit(2)
    return queries, transport


def run_one(client, voice, allow, query):
    """Full e2e for one query: retrieval (per-stage timing) + streamed compose."""
    r = retrieval.run(query, allow)
    tt, route, rr = r["timing"], r["route"], r["retrieval"]
    directives = service._directives(query, route)
    payload = service.build_payload(query, rr["selected"], directives)
    _text, ttft, ctotal, usage = stream_compose(client, voice, payload)
    router_ms = round(tt["embed_query_ms"] + tt["route_centroids_ms"], 1)
    total = round(tt["input_gate_ms"] + router_ms + tt["retrieve_rrf_cutoff_ms"] + ctotal, 1)
    u = {"input": getattr(usage, "input_tokens", 0), "output": getattr(usage, "output_tokens", 0),
         "cache_write": getattr(usage, "cache_creation_input_tokens", 0),
         "cache_read": getattr(usage, "cache_read_input_tokens", 0)}
    uncached = ((u["input"] + u["cache_read"]) * PRICE[0] + u["output"] * PRICE[1]) / 1e6
    return {
        "query": query, "gate": r["gate"]["scope"],
        "input_gate_ms": tt["input_gate_ms"], "router_ms": router_ms,
        "retrieval_ms": tt["retrieve_rrf_cutoff_ms"], "composer_ms": ctotal,
        "composer_ttft_ms": ttft, "total_ms": total,
        "routed_topic": route["top_topic"], "routed_theme_cos": route["top_cosine"],
        "in_scope": route["in_scope"], "n_chunks": len(rr["selected"]),
        "retrieved_chunk_ids": [c for c, _, _ in rr["selected"]],
        "universe": rr["universe_size"], "aligned": rr["aligned"],
        "llm_calls_before_composition": r["llm_calls_before_composition"],
        "usage": u, "cost_cached_usd": round(_cost(usage), 6),
        "cost_uncached_equiv_usd": round(uncached, 6),
    }


def main() -> int:
    queries, transport = gates()
    allow = service._allowlist("v4")
    client = _client()
    voice = service._voice_card()

    # ---- WARM (cold-start reported SEPARATELY, excluded from percentiles) ----
    t0 = time.perf_counter(); embeddings.get_model()
    cold_load = round((time.perf_counter() - t0) * 1000, 1)
    t0 = time.perf_counter(); w1 = run_one(client, voice, allow, "What is the rule of law?")
    first_call = round((time.perf_counter() - t0) * 1000, 1)
    run_one(client, voice, allow, "Tell me about liberty and prosperity.")  # warm-up #2
    stream_ok = w1["composer_ttft_ms"] is not None
    print(f"[G2] Messages.stream yielded first chunk (warm-up TTFT={w1['composer_ttft_ms']}ms) -> "
          f"{'PASS' if stream_ok else 'FAIL'}")
    if not stream_ok:
        print("[G2] STOP: stream produced no chunk.", file=sys.stderr); return 2
    cold = {"model_cold_load_ms": cold_load, "first_call_total_ms_incl_connection": first_call,
            "note": "EXCLUDED from the warmed p50/p95 percentiles below."}
    print(f"[cold-start] model_load={cold_load}ms first_call(incl TLS)={first_call}ms (excluded)")

    # ---- MEASURE 40 frozen queries ----
    qmeta = {q["query"]: q for q in queries}
    records = []
    with open(OUT_JSONL, "w", encoding="utf-8", newline="\n") as fh:
        for q in queries:
            rec = run_one(client, voice, allow, q["query"])
            rec["qid"] = q["id"]; rec["qtype"] = q["type"]; rec["qtheme"] = q["theme"]
            records.append(rec)
            fh.write(json.dumps(rec, ensure_ascii=config.JSON_ENSURE_ASCII) + "\n")
            print(f"  {q['id']:4} total={rec['total_ms']:>8}ms ttft={rec['composer_ttft_ms']:>7}ms "
                  f"route={rec['routed_topic'][:28]:28} in_scope={rec['in_scope']} "
                  f"llm_pre={rec['llm_calls_before_composition']}")

    # ---- SUMMARISE ----
    def col(k): return [r[k] for r in records]
    stages = ["input_gate_ms", "router_ms", "retrieval_ms", "composer_ms", "composer_ttft_ms", "total_ms"]
    summary = {s: {"p50": pctl(col(s), 50), "p95": pctl(col(s), 95)} for s in stages}
    mean_cached = round(float(np.mean(col("cost_cached_usd"))), 6)
    mean_uncached = round(float(np.mean(col("cost_uncached_equiv_usd"))), 6)
    total_cost = round(float(np.sum(col("cost_cached_usd"))), 6)

    # ---- VERIFY ----
    all_zero = all(r["llm_calls_before_composition"] == 0 for r in records)
    in_scope_n = sum(1 for r in records if r["in_scope"])
    spot = next(r for r in records if r["qid"] == "A1")  # rule_of_law route
    parity = {"qid": "A1", "routed_topic": spot["routed_topic"], "routed_cos": spot["routed_theme_cos"],
              "universe": spot["universe"], "aligned": spot["aligned"]}
    print(f"\n[VERIFY] llm_calls_before_composition==0 for all 40 -> {'PASS' if all_zero else 'FAIL'}")
    print(f"[VERIFY] in_scope {in_scope_n}/40 (oos gate uncalibrated -> expect ~40; W3.x fact)")
    print(f"[VERIFY] parity A1: route={parity['routed_topic']} cos={parity['routed_cos']} "
          f"universe={parity['universe']} aligned={parity['aligned']}")

    out = {
        "anchor": "arch-baseline (new-arch: Haiku-out, soft-prior, RRF, dynamic cutoff)",
        "is_official_w3_3_comparator": True,
        "not_pilot_baseline_haiku_in_path": True,
        "frozen_set_sha256": FROZEN_SHA, "n_queries": len(records),
        "transport": transport, "embed_device": config.EMBED_DEVICE,
        "composer_model": config.COMPOSER_MODEL_ID,
        "config_defaults": {"LAMBDA": config.LAMBDA, "TAU": config.TAU, "RRF_K": config.RRF_K,
                            "MIN_K": config.MIN_K, "MAX_K": config.MAX_K,
                            "OUT_OF_SCOPE_THRESHOLD": config.OUT_OF_SCOPE_THRESHOLD,
                            "TOPIC_SOFTMAX_TEMPERATURE": config.TOPIC_SOFTMAX_TEMPERATURE},
        "stages_p50_p95_ms": summary,
        "ttft_ms": summary["composer_ttft_ms"], "total_e2e_ms": summary["total_ms"],
        "cost_per_query_usd": {"mean_cached": mean_cached, "mean_uncached_equiv": mean_uncached,
                               "prompt_caching": "present (voice card cache_control: ephemeral)"},
        "total_run_cost_usd_cached": total_cost,
        "cold_start": cold,
        "verify": {"llm_calls_before_composition_all_zero": all_zero,
                   "in_scope_count": in_scope_n, "out_of_scope_count": 40 - in_scope_n,
                   "parity_spotcheck": parity},
        "run_timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "queries": records,
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
                        encoding=config.OUTPUT_ENCODING)

    print("\n=== ARCH-BASELINE (warmed p50/p95, ms) ===")
    for s in stages:
        print(f"  {s:18} p50={summary[s]['p50']:>9}  p95={summary[s]['p95']:>9}")
    print(f"cost/query: cached=${mean_cached} uncached-equiv=${mean_uncached} | "
          f"total run (cached)=${total_cost}")
    print(f"transport={transport} embed_device={config.EMBED_DEVICE} n={len(records)} | "
          f"wrote {OUT_JSON.name} + {OUT_JSONL.name}")
    if not all_zero:
        print("STOP: a query made an LLM call before composition.", file=sys.stderr); return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
