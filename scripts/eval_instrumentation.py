"""
Eval instrumentation for TABLE 1 (API cost/query) + TABLE 3 (compose latency).

Schema + row builders + guards. Compose harnesses import these to AUTO-POPULATE
the two per-query CSVs on their next run (see emit_from_records). Running this file
standalone emits EMPTY-but-valid CSV/JSON stubs with a SYNTHETIC self-test row that
proves the cost math (Table 1) and the ttfa = ttft + first-sentence-TTS math (Table 3)
WITHOUT any API call.

Rate constants are LOGGED per row + in the stub so pilot cost is reproducible if
pricing changes. NO API/composition here.
"""
from __future__ import annotations
import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "eval" / "results"

# Claude Sonnet 4.6 pricing, $/MTok — the 4 rate constants (logged, never silent).
RATES = {"input": 3.00, "cache_write_5m": 3.75, "cache_read": 0.30, "output": 15.00}
MODEL = "claude-sonnet-4-6"

COST_COLS = ["query_id", "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
             "output_tokens", "cost_base_input", "cost_cache_write", "cost_cache_read", "cost_output",
             "cost_total", "regime", "expanded", "rate_input", "rate_cache_write", "rate_cache_read",
             "rate_output", "model"]
COMPOSE_COLS = ["query_id", "t_request_build_ms", "ttft_ms", "t_stream_generation_ms", "t_total_compose_ms",
                "t_first_sentence_tts_ms", "ttfa_ms", "t_envelope_parse_ms", "output_tokens",
                "tokens_per_sec", "expanded", "t_expand_retry_ms", "transport", "degraded"]


def cost_row(qid, usage: dict, expanded: bool = False) -> dict:
    """usage buckets: input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens."""
    it = usage.get("input_tokens", usage.get("input", 0)) or 0
    cw = usage.get("cache_creation_input_tokens", usage.get("cache_write", 0)) or 0
    cr = usage.get("cache_read_input_tokens", usage.get("cache_read", 0)) or 0
    ot = usage.get("output_tokens", usage.get("output", 0)) or 0
    cb = it * RATES["input"] / 1e6
    cwc = cw * RATES["cache_write_5m"] / 1e6
    crc = cr * RATES["cache_read"] / 1e6
    oc = ot * RATES["output"] / 1e6
    return {"query_id": qid, "input_tokens": it, "cache_creation_input_tokens": cw,
            "cache_read_input_tokens": cr, "output_tokens": ot,
            "cost_base_input": round(cb, 6), "cost_cache_write": round(cwc, 6),
            "cost_cache_read": round(crc, 6), "cost_output": round(oc, 6),
            "cost_total": round(cb + cwc + crc + oc, 6),
            "regime": "cached" if cr > 0 else "uncached", "expanded": bool(expanded),
            "rate_input": RATES["input"], "rate_cache_write": RATES["cache_write_5m"],
            "rate_cache_read": RATES["cache_read"], "rate_output": RATES["output"], "model": MODEL}


def compose_row(qid, ttft_ms, t_total_compose_ms, output_tokens, transport, degraded,
                t_first_sentence_tts_ms=None, t_request_build_ms=None, t_envelope_parse_ms=None,
                expanded=False, t_expand_retry_ms=None) -> dict:
    gen = (t_total_compose_ms - ttft_ms) if (ttft_ms is not None and t_total_compose_ms is not None) else None
    ttfa = (ttft_ms + t_first_sentence_tts_ms) if (ttft_ms is not None and t_first_sentence_tts_ms is not None) else None
    tps = round(output_tokens / (gen / 1000.0), 2) if (gen and gen > 0 and output_tokens) else None
    return {"query_id": qid, "t_request_build_ms": t_request_build_ms, "ttft_ms": ttft_ms,
            "t_stream_generation_ms": round(gen, 1) if gen is not None else None,
            "t_total_compose_ms": t_total_compose_ms, "t_first_sentence_tts_ms": t_first_sentence_tts_ms,
            "ttfa_ms": round(ttfa, 1) if ttfa is not None else None,
            "t_envelope_parse_ms": t_envelope_parse_ms, "output_tokens": output_tokens,
            "tokens_per_sec": tps, "expanded": bool(expanded), "t_expand_retry_ms": t_expand_retry_ms,
            "transport": transport, "degraded": bool(degraded)}


# ---- GUARDS (bake into the compose harness) ----
def assert_single_transport(transports) -> str:
    """A run MUST use ONE transport; curl TTFT != native TTFT and must never be averaged."""
    uniq = sorted(set(transports))
    if len(uniq) > 1:
        raise SystemExit(f"[GUARD] TRANSPORT FLIPPED MID-RUN {uniq} — curl/native latencies must not be "
                         f"pooled. Re-run on a single transport (preflight_transport.py).")
    return uniq[0] if uniq else "unknown"


def latency_rows_excluding_degraded(rows):
    """degraded (graceful-degradation / billing / timeout fallback) EXCLUDED from percentiles."""
    keep = [r for r in rows if not r.get("degraded")]
    return keep, [r["query_id"] for r in rows if r.get("degraded")]


def _write_csv(path, cols, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


def emit_from_records(recs, transport):
    """AUTO-POPULATE hook: call from a compose harness with its per-query records
    (each having usage, composer_ttft_ms, composer_ms, output tokens, degraded)."""
    assert_single_transport([transport] * len(recs))
    cost = [cost_row(r["qid"], r["usage"], expanded=(r.get("envelope") or {}).get("expanded", False)) for r in recs]
    comp = [compose_row(r["qid"], r.get("composer_ttft_ms"), r.get("composer_ms"),
                        r["usage"].get("output", 0), transport, r.get("degraded", False),
                        expanded=(r.get("envelope") or {}).get("expanded", False)) for r in recs]
    _write_csv(RES / "cost_per_query.csv", COST_COLS, cost)
    _write_csv(RES / "compose_latency_per_query.csv", COMPOSE_COLS, comp)
    return cost, comp


def _self_test_and_stub():
    # synthetic token counts (uncached regime) — prove the cost math, no API
    syn_usage = {"input_tokens": 3500, "cache_creation_input_tokens": 0,
                 "cache_read_input_tokens": 4596, "output_tokens": 400}
    cr = cost_row("SELFTEST", syn_usage, expanded=False)
    expect = round(3500*3/1e6 + 4596*0.30/1e6 + 400*15/1e6, 6)
    assert cr["cost_total"] == expect, (cr["cost_total"], expect)
    # synthetic compose — prove ttfa = ttft + first-sentence-tts
    cm = compose_row("SELFTEST", ttft_ms=1500.0, t_total_compose_ms=9500.0, output_tokens=400,
                     transport="native_sdk", degraded=False, t_first_sentence_tts_ms=90.0)
    assert cm["ttfa_ms"] == 1590.0 and cm["t_stream_generation_ms"] == 8000.0, cm

    _write_csv(RES / "cost_per_query.csv", COST_COLS, [cr])
    _write_csv(RES / "compose_latency_per_query.csv", COMPOSE_COLS, [cm])
    (RES / "cost_per_query_STUB.json").write_text(json.dumps({
        "table": "TABLE 1 — API cost/query (schema + stub; AUTO-POPULATES on next compose run)",
        "columns": COST_COLS, "rate_constants": RATES, "model": MODEL,
        "aggregate_spec": ["mean", "p50", "p95", "total_40", "cached_regime_total", "uncached_regime_total"],
        "pilot_cost_caveat": "PILOT honest cost = UNCACHED (sporadic traffic > 5-min cache TTL per W2.3). "
                             "The cached_regime_total applies ONLY under sustained load; never quote cached "
                             "savings without this caveat.",
        "self_test_row": cr, "self_test_expected_total": expect, "api_spend_usd": 0.0,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RES / "compose_latency_STUB.json").write_text(json.dumps({
        "table": "TABLE 3 — compose latency (schema + stub; AUTO-POPULATES on next compose run)",
        "columns": COMPOSE_COLS, "ttfa_definition": "ttfa_ms = ttft_ms + t_first_sentence_tts_ms",
        "guards": {"single_transport": "assert_single_transport() — one transport/run; curl != native, never pooled",
                   "degraded_excluded": "latency_rows_excluding_degraded() — degraded rows OUT of percentiles"},
        "aggregate_spec": ["p50/p95/mean per stage", "transport stated", "degraded_count reported separately + excluded"],
        "self_test_row": cm, "api_spend_usd": 0.0,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("[selftest] cost math OK: total", cr["cost_total"], "== expected", expect,
          "| ttfa math OK: ttfa", cm["ttfa_ms"], "= ttft 1500 + tts 90")
    print("wrote cost_per_query.csv + compose_latency_per_query.csv (header + synthetic self-test row)")
    print("wrote cost_per_query_STUB.json + compose_latency_STUB.json")


if __name__ == "__main__":
    _self_test_and_stub()
