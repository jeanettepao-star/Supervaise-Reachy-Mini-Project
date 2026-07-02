"""
W2.3 — verify + formalize prompt caching (cache-boundary correctness).

Phase 1 (structure/leak) + Phase 2 (stability from existing runs) are FREE.
Phase 3 is a TINY live probe (3 calls, small max_tokens): same query twice
(creation -> read) + a DIFFERENT query on the shared prefix (read). A per-run
nonce is appended to the STATIC prefix ONLY to guarantee a cold cache for the
demonstration (identical across all 3 calls, so it isn't per-query leakage); the
real prefix's caching across all 40 is already proven by Phase 2.

Usage:  python scripts/run_w2_3_cache_probe.py
"""
from __future__ import annotations
import json, sys, datetime
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
import config, service, retrieval  # noqa: E402

OUT = ROOT / "w2_3_cache_report.json"
SONNET_CACHE_MIN_TOK = 1024   # Anthropic min cacheable prefix for Claude Sonnet 4.x (Haiku=2048)


def _usage(u):
    return {"input": getattr(u, "input_tokens", 0),
            "cache_creation": getattr(u, "cache_creation_input_tokens", 0),
            "cache_read": getattr(u, "cache_read_input_tokens", 0),
            "output": getattr(u, "output_tokens", 0)}


def main():
    allow = service._allowlist("v4")
    qs = ["What is the rule of law?", "What is the Prosperity Fund for MSMEs?",
          "Describe your childhood in Sampaloc.", "When was the South China Sea arbitral award issued?"]
    systems, payloads, chunkids, llm_pre = [], [], [], []
    for q in qs:
        r = retrieval.run(q, allow)
        systems.append(service._composer_system())
        payloads.append(service.build_payload(q, r["retrieval"]["selected"], service._directives(q, r["route"])))
        chunkids.append([c for c, _, _ in r["retrieval"]["selected"]])
        llm_pre.append(r["llm_calls_before_composition"])

    today = datetime.date.today().isoformat()
    ident = all(s == systems[0] for s in systems)
    leaks = []
    for i, q in enumerate(qs):
        if q in systems[0]: leaks.append(f"q{i} query-text")
        if any(cid in systems[0] for cid in chunkids[i]): leaks.append(f"q{i} chunk_ids")
    if today in systems[0]: leaks.append("date")

    phase1 = {
        "assembly": "system=[{text: Voice Card + W2.1 composer directives, cache_control: ephemeral}] "
                    "(STATIC) ; user message = build_payload(chunks + lean directives + date_note + query) "
                    "(VARIABLE).",
        "order_static_first_variable_last": True,
        "static_prefix_query_independent": "query" not in service._composer_system.__code__.co_varnames,
        "static_prefix_byte_identical_across_queries": ident,
        "static_prefix_chars": len(systems[0]),
        "breakpoint": "cache_control on the SINGLE (last) static system block -> entire static prefix cached; "
                      "no mid-prefix breakpoint.",
        "leak_check": {"leaks_found": leaks, "PASS": not leaks,
                       "per_query_values_in_variable_section": {
                           "query_text_in_payload": all(qs[i] in payloads[i] for i in range(len(qs))),
                           "chunk_ids_in_payload": all(chunkids[i][0] in payloads[i] for i in range(len(qs)))}},
    }

    # ---- Phase 2 ----
    phase2 = {}
    for fn in ("arch_baseline.json", "w2_1_baseline.json"):
        d = json.loads((ROOT / fn).read_text(encoding="utf-8"))
        cr = [q["usage"]["cache_read"] for q in d["queries"]]
        cw = [q["usage"].get("cache_write", 0) for q in d["queries"]]
        inp = [q["usage"]["input"] for q in d["queries"]]
        out = [q["usage"]["output"] for q in d["queries"]]
        cached_tok = cr[0]
        # cost/query: cached (as recorded) vs uncached-equiv (cache_read repriced at full input)
        PRICE_IN, PRICE_OUT, PRICE_CR = 3.0, 15.0, 0.30
        cached_cost = np.mean([(inp[i] * PRICE_IN + out[i] * PRICE_OUT + cr[i] * PRICE_CR) / 1e6
                               for i in range(len(cr))])
        uncached_cost = np.mean([((inp[i] + cr[i]) * PRICE_IN + out[i] * PRICE_OUT) / 1e6
                                 for i in range(len(cr))])
        phase2[fn] = {
            "cache_read_unique": sorted(set(cr)), "stable": len(set(cr)) == 1,
            "cache_write_unique": sorted(set(cw)), "cached_prefix_tokens": cached_tok,
            "min_size_ok": cached_tok >= SONNET_CACHE_MIN_TOK,
            "uncached_input_mean_tok": round(float(np.mean(inp))),
            "cost_per_query_usd": {"cached": round(float(cached_cost), 6),
                                   "uncached_equiv": round(float(uncached_cost), 6)},
        }

    # ---- Phase 3: live probe (nonce-forced cold cache) ----
    nonce = datetime.datetime.now().isoformat()
    sysp = service._composer_system() + f"\n<!-- w2_3 cache probe nonce {nonce} -->"
    rA = retrieval.run(qs[0], allow); pA = service.build_payload(qs[0], rA["retrieval"]["selected"], service._directives(qs[0], rA["route"]))
    rB = retrieval.run(qs[1], allow); pB = service.build_payload(qs[1], rB["retrieval"]["selected"], service._directives(qs[1], rB["route"]))
    client = service._client()

    def call(payload, label):
        resp = client.messages.create(
            model=config.COMPOSER_MODEL_ID, max_tokens=32,
            system=[{"type": "text", "text": sysp, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": payload}])
        u = _usage(resp.usage)
        print(f"  {label}: creation={u['cache_creation']} read={u['cache_read']} input={u['input']}")
        return u

    print("=== PHASE 3 live probe (nonce-forced cold prefix) ===")
    c1 = call(pA, "call1 (query A, expect CREATION)")
    c2 = call(pA, "call2 (query A again, expect READ)")
    c3 = call(pB, "call3 (query B, DIFFERENT query, expect READ on shared prefix)")
    PRICE_IN, PRICE_OUT, PRICE_CR, PRICE_CW = 3.0, 15.0, 0.30, 3.75
    spend = sum((c["input"] * PRICE_IN + c["output"] * PRICE_OUT +
                 c["cache_read"] * PRICE_CR + c["cache_creation"] * PRICE_CW) / 1e6
                for c in (c1, c2, c3))
    phase3 = {
        "nonce_note": "nonce appended to STATIC prefix ONLY to force a cold cache for the demo; "
                      "identical across all 3 calls -> not per-query leakage.",
        "call1_query_A": c1, "call2_query_A_repeat": c2, "call3_query_B_different": c3,
        "creation_then_read": c1["cache_creation"] > 0 and c2["cache_read"] > 0,
        "shared_prefix_across_queries": c3["cache_read"] > 0,
        "spend_usd": round(spend, 6),
    }

    report = {
        "task": "W2.3 prompt-cache boundary verification",
        "frozen_set_sha256": "65492b65...", "composer_model": config.COMPOSER_MODEL_ID,
        "sonnet_cache_min_tokens": SONNET_CACHE_MIN_TOK,
        "phase1_structure_and_leak": phase1,
        "phase2_existing_run_evidence": phase2,
        "phase3_live_probe": phase3,
        "ttl_reality_note": ("Anthropic default cache TTL ~5 min. Pilot traffic is sporadic, so the "
                             "cache likely EXPIRES between visitors -> the pilot's REAL per-query cost "
                             "is the UNCACHED figure. The CACHED figure applies only under steady/"
                             "production traffic (calls within 5 min of each other)."),
        "llm_calls_before_composition_all_zero": all(x == 0 for x in llm_pre),
        "total_spend_usd": round(spend, 6),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
                   encoding=config.OUTPUT_ENCODING)
    print(f"\nPhase1 leak PASS: {phase1['leak_check']['PASS']} | static prefix {phase1['static_prefix_chars']} chars")
    print(f"Phase2 cache_read stable: arch={phase2['arch_baseline.json']['stable']} "
          f"w2_1={phase2['w2_1_baseline.json']['stable']} | prefix {phase2['w2_1_baseline.json']['cached_prefix_tokens']} tok "
          f">= {SONNET_CACHE_MIN_TOK} min: {phase2['w2_1_baseline.json']['min_size_ok']}")
    w = phase2["w2_1_baseline.json"]["cost_per_query_usd"]
    print(f"Cost/query (w2_1): cached ${w['cached']}  uncached ${w['uncached_equiv']}  "
          f"(pilot real ~= uncached; production ~= cached)")
    print(f"Phase3: creation->read {phase3['creation_then_read']} | shared-prefix {phase3['shared_prefix_across_queries']}")
    print(f"[COST] probe spend = ${round(spend,6)}  | llm_pre==0: {report['llm_calls_before_composition_all_zero']}")
    print(f"wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
