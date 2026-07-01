"""
W2.2 Phase 3 — SMALL PAID probe (~9 queries) proving payload slimming end-to-end.
Runs the slim payload (COMPOSER_TOP_K via env, set to 6) and compares REAL usage
to the STORED w2_1_baseline numbers for the SAME ids (no re-run of the old side).

Apples-to-apples: same composer (W2.1), same device (cuda), same warm protocol,
same 1s inter-query pacing as w2_1. ONLY the payload differs (6 vs 12 chunks).

Usage:  CJ_COMPOSER_TOP_K=6 python scripts/run_w2_2_probe.py
"""
from __future__ import annotations
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
import config, retrieval, service, embeddings  # noqa: E402
from run_arch_baseline import gates  # noqa: E402  (G1 frozen-sha / G2 native_sdk / G3 pin+loads)
from run_baseline import _cost, PRICE  # noqa: E402

FREE = Path(r"C:\Users\ASUS\AppData\Local\Temp\claude\C--Reachy-Mini-Project-2026\e80bfca1-5d2e-4d39-b4fb-01f94945a1d3\scratchpad\w2_2_free.json")
OUT = ROOT / "w2_2_payload_report.json"
# 1-2 per theme A-E + case A3 + long-reflective C15 + multi X37 (+ date X34, +A1 parity).
# E28 is the STRESS test: its grounding doc CE007 sits at rank 5 -> must survive top_k=6.
PROBE = ["A1", "A3", "B10", "C15", "D20", "E28", "E29", "X37", "X34"]
def did(c): return c.split("::")[0]


def run_one(client, allow, q):
    r = retrieval.run(q["query"], allow)
    tt, route, rr = r["timing"], r["route"], r["retrieval"]
    directives = service._directives(q["query"], route)
    t0 = time.perf_counter()
    comp = service.compose_streamed(q["query"], rr["selected"], directives, client=client)
    composer_ms = round((time.perf_counter() - t0) * 1000, 1)
    u = comp["usage"]
    usage = {"input": getattr(u, "input_tokens", 0), "output": getattr(u, "output_tokens", 0),
             "cache_write": getattr(u, "cache_creation_input_tokens", 0),
             "cache_read": getattr(u, "cache_read_input_tokens", 0)} if u else {}
    router_ms = round(tt["embed_query_ms"] + tt["route_centroids_ms"], 1)
    total = round(tt["input_gate_ms"] + router_ms + tt["retrieve_rrf_cutoff_ms"] + composer_ms, 1)
    exp = q.get("expected_grounding_doc_ids") or []
    kept_docs = {did(c) for c, _, _ in rr["selected"][:config.COMPOSER_TOP_K]}
    env = comp["envelope"] or {}
    cited = env.get("doc_ids_cited") or []
    return {"qid": q["id"], "type": q["type"], "theme": q["theme"],
            "n_chunks_payload": min(len(rr["selected"]), config.COMPOSER_TOP_K),
            "input_tok": usage.get("input", 0), "output_tok": usage.get("output", 0),
            "cache_read": usage.get("cache_read", 0),
            "ttft_ms": comp["ttft_ms"], "total_ms": total, "composer_ms": composer_ms,
            "cost_cached_usd": round(_cost(u), 6) if u else 0.0,
            "stop_reason": comp["stop_reason"], "degraded": comp["degraded"],
            "llm_calls_before_composition": r["llm_calls_before_composition"],
            "in_scope": route["in_scope"], "routed_topic": route["top_topic"],
            "exp_docs": exp, "exp_in_slim_payload": [e for e in exp if e in kept_docs],
            "grounding_lost": [e for e in exp if e not in kept_docs],
            "envelope_doc_ids_cited": cited,
            "envelope_cites_real": all(c in kept_docs for c in cited) if cited else None}


def main():
    assert config.COMPOSER_TOP_K < config.MAX_K, \
        f"probe expects a SLIM COMPOSER_TOP_K (<{config.MAX_K}); set CJ_COMPOSER_TOP_K=6"
    queries, transport = gates()
    byid = {q["id"]: q for q in queries}
    probe_qs = [byid[i] for i in PROBE]
    allow = service._allowlist("v4")
    client = service._client()

    # warm (cold-start separate)
    t0 = time.perf_counter(); embeddings.get_model(); cold = round((time.perf_counter() - t0) * 1000, 1)
    run_one(client, allow, {"id": "w1", "type": "warm", "theme": "A", "query": "What is the rule of law?"})
    run_one(client, allow, {"id": "w2", "type": "warm", "theme": "B", "query": "Tell me about liberty and prosperity."})
    print(f"[cold-start] model_load={cold}ms (excluded) | COMPOSER_TOP_K={config.COMPOSER_TOP_K}")

    recs = []
    for i, q in enumerate(probe_qs):
        rec = run_one(client, allow, q)
        recs.append(rec)
        print(f"  {q['id']:4} chunks={rec['n_chunks_payload']} in_tok={rec['input_tok']:>5} "
              f"ttft={str(rec['ttft_ms']):>7} total={rec['total_ms']:>8} "
              f"grnd_lost={rec['grounding_lost']} cites_real={rec['envelope_cites_real']} "
              f"llm_pre={rec['llm_calls_before_composition']}")
        if i < len(probe_qs) - 1:
            time.sleep(1.0)  # match w2_1 pacing (apples-to-apples)

    # compare to STORED w2_1 (lean/12) numbers for the same ids — no re-run
    w21 = {q["qid"]: q for q in json.loads((ROOT / "w2_1_baseline.json").read_text(encoding="utf-8"))["queries"]}
    comp_rows = []
    for r in recs:
        o = w21.get(r["qid"], {})
        oi = (o.get("usage") or {}).get("input", None)
        comp_rows.append({"qid": r["qid"],
                          "input_tok_old12": oi, "input_tok_slim6": r["input_tok"],
                          "input_tok_delta": (r["input_tok"] - oi) if oi is not None else None,
                          "ttft_old": o.get("composer_ttft_ms"), "ttft_slim": r["ttft_ms"],
                          "total_old": o.get("total_ms"), "total_slim": r["total_ms"],
                          "cost_old": o.get("cost_cached_usd"), "cost_slim": r["cost_cached_usd"]})

    def dmean(k_new, k_old):
        pairs = [(c[k_new], c[k_old]) for c in comp_rows if c[k_old] is not None and c[k_new] is not None]
        return (round(float(np.mean([n for n, _ in pairs])), 4),
                round(float(np.mean([o for _, o in pairs])), 4))
    in_new, in_old = dmean("input_tok_slim6", "input_tok_old12")
    cost_new, cost_old = dmean("cost_slim", "cost_old")
    ttft_new, ttft_old = dmean("ttft_slim", "ttft_old")
    tot_new, tot_old = dmean("total_slim", "total_old")

    total_cost = round(sum(r["cost_cached_usd"] for r in recs), 6)
    all_zero = all(r["llm_calls_before_composition"] == 0 for r in recs)
    losses = [(r["qid"], r["grounding_lost"]) for r in recs if r["grounding_lost"]]
    cite_fail = [r["qid"] for r in recs if r["envelope_cites_real"] is False]

    free = json.loads(FREE.read_text(encoding="utf-8"))
    report = {
        "task": "W2.2 payload slimming", "frozen_set_sha256": "65492b65...",
        "transport": transport, "embed_device": config.EMBED_DEVICE,
        "pacing": "1.0s inter-query (matches w2_1_baseline; apples-to-apples)",
        "slim_config": {"COMPOSER_TOP_K": config.COMPOSER_TOP_K,
                        "COMPOSER_CHUNK_CHAR_BUDGET": config.COMPOSER_CHUNK_CHAR_BUDGET,
                        "COMPOSER_SIGNATURE_PALETTE": config.COMPOSER_SIGNATURE_PALETTE,
                        "default_top_k_is_behavior_preserving": config.MAX_K},
        "excluded_from_payload": ["stances", "decision_framework_signals", "target_audience",
                                  "register_markers", "one_paragraph_summary",
                                  "signature_phrases (optional palette, default OFF)"],
        "phase2_free_accounting_all40": free,
        "phase3_probe": {
            "ids": PROBE,
            "rationale": "1-2/theme A-E + case A3 + long-reflective C15 + multi X37 + date X34 "
                         "+ A1 parity; E28 is the rank-5 grounding stress test.",
            "per_query": recs,
            "vs_stored_w2_1_lean12": comp_rows,
            "mean_input_tok": {"old_12": in_old, "slim_6": in_new,
                               "reduction_tok": round(in_old - in_new, 1),
                               "reduction_pct": round((in_old - in_new) / in_old * 100, 1) if in_old else None},
            "mean_cost_cached_usd": {"old_12": cost_old, "slim_6": cost_new,
                                     "reduction_pct": round((cost_old - cost_new) / cost_old * 100, 1) if cost_old else None},
            "mean_ttft_ms": {"old_12": ttft_old, "slim_6": ttft_new},
            "mean_total_ms": {"old_12": tot_old, "slim_6": tot_new},
            "probe_run_cost_usd": total_cost},
        "quality_guard": {"grounding_losses": losses, "grounding_PASS": not losses,
                          "envelope_cites_unreal": cite_fail,
                          "llm_calls_before_composition_all_zero": all_zero},
        "cold_start_ms": cold,
        "run_timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
                   encoding=config.OUTPUT_ENCODING)
    print(f"\n=== PROBE ({len(recs)}q) slim(top_k={config.COMPOSER_TOP_K}) vs stored w2_1 lean(12) ===")
    print(f"  input tok/q: {in_old:.0f} -> {in_new:.0f}  (-{(in_old-in_new)/in_old*100:.1f}%)")
    print(f"  cost/q     : ${cost_old:.5f} -> ${cost_new:.5f}  (-{(cost_old-cost_new)/cost_old*100:.1f}%)")
    print(f"  TTFT/q ms  : {ttft_old:.0f} -> {ttft_new:.0f}")
    print(f"  total/q ms : {tot_old:.0f} -> {tot_new:.0f}")
    print(f"[GUARD] grounding losses={losses or 0} | envelope cites-unreal={cite_fail or 0} | "
          f"llm_pre==0 all: {all_zero}")
    print(f"[COST] probe run = ${total_cost}  | wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
