"""
W2.6 self-checks: no-regression GATE (flag OFF, verbatim), hard-cap=1 proof,
fire-rate over the anchor (from v2 envelopes, $0), and a live X33 expand demo.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config, service, retrieval  # noqa: E402
OUT = ROOT / "eval" / "results" / "w2_6_expand_report.json"


def stub_factory(cites, calls):
    def stub(query, selected, directives, client=None, on_text=None, top_k=None):
        calls.append({"n_selected": len(selected), "top_k": top_k})
        return {"answer": "stub prose.", "envelope": {"doc_ids_cited": list(cites)},
                "raw": "", "ttft_ms": None, "stop_reason": "end_turn", "degraded": False, "usage": None}
    return stub


def main():
    orig = service.compose_streamed
    report = {}

    # 1) NO-REGRESSION GATE — flag OFF: exactly ONE compose call, verbatim return
    calls = []
    service.compose_streamed = stub_factory(["CA001"], calls)
    config.EXPAND_ON_DEMAND_ENABLED = False
    r = service.compose_with_expand("q", [("CA003::c000", 0.0, {})], {"register": "x", "disclaimer": "", "date_note": ""})
    noreg = (len(calls) == 1 and "triggered" not in r and "expanded" not in r
             and r["envelope"]["doc_ids_cited"] == ["CA001"])
    print(f"[1] NO-REGRESSION (flag OFF): calls={len(calls)}, verbatim(no added keys)={'triggered' not in r} -> {'PASS' if noreg else 'FAIL'}")
    report["no_regression_flag_off"] = {"compose_calls": len(calls), "verbatim": noreg, "PASS": noreg}
    if not noreg:
        print("STOP: flag OFF changed behavior.", file=sys.stderr); service.compose_streamed = orig; return 2

    # 2) HARD-CAP=1 proof — flag ON, first pass EMPTY-cited -> triggers -> exactly 2 calls total, never more
    calls = []
    service.compose_streamed = stub_factory([], calls)          # always empty -> always "weak"
    config.EXPAND_ON_DEMAND_ENABLED = True
    config.EXPAND_TRIGGER_MIN_CITATIONS = 1                     # fire on empty
    r = service.compose_with_expand("q", [("CA003::c000", 0.0, {})], {"register": "x", "disclaimer": "", "date_note": ""})
    hardcap = (len(calls) == 2 and r["triggered"] and r["expanded"])
    retry_top_k = calls[1]["top_k"] if len(calls) > 1 else None
    print(f"[2] HARD-CAP=1: empty-cite fired the retry; total compose calls={len(calls)} (first + ONE retry), "
          f"retry top_k={retry_top_k} -> {'PASS' if hardcap else 'FAIL'}  (never loops even though retry also empty)")
    report["hard_cap_1"] = {"compose_calls_when_always_weak": len(calls), "retry_top_k": retry_top_k,
                            "triggered": r["triggered"], "expanded": r["expanded"], "PASS": hardcap}
    service.compose_streamed = orig
    config.EXPAND_ON_DEMAND_ENABLED = False
    config.EXPAND_TRIGGER_MIN_CITATIONS = 1

    # 3) FIRE-RATE over the 40-query anchor (deterministic trigger on the anchor's
    #    first-pass citations from arch_baseline_v2 — first-pass grounding is
    #    UNCHANGED by W2.6, so this is a valid $0 measurement).
    v2 = json.loads((ROOT / "arch_baseline_v2.json").read_text(encoding="utf-8"))["queries"]
    def cites(q): return len((q.get("envelope") or {}).get("doc_ids_cited") or [])
    fire1 = [q["qid"] for q in v2 if cites(q) < 1 or q.get("degraded")]     # default floor=1 (empty)
    fire2 = [q["qid"] for q in v2 if cites(q) < 2 or q.get("degraded")]     # sensitivity floor=2
    ceil = config.EXPAND_FIRE_RATE_CEILING
    price_in, price_out, price_cr = 3.0, 15.0, 0.30
    # per-retry cost estimate ~= one extra compose ~= mean cached cost/query from v2
    mean_cost = sum(q.get("cost_cached_usd", 0) for q in v2) / len(v2)
    for label, fire in (("floor=1(default,empty)", fire1), ("floor=2(sensitivity)", fire2)):
        rate = len(fire) / 40
        flag = "OVER ceiling -> UPSTREAM-RETRIEVAL SIGNAL" if rate > ceil else "within ceiling"
        print(f"[3] FIRE-RATE {label}: {len(fire)}/40 = {rate:.1%} ({flag}); "
              f"added composes={len(fire)}, est +${len(fire)*mean_cost:.4f} over the run")
    report["fire_rate"] = {
        "anchor": "arch-baseline-v2 first-pass envelopes (first-pass grounding unchanged by W2.6)",
        "ceiling": ceil, "mean_cost_per_compose_usd": round(mean_cost, 6),
        "floor_1_default": {"fire_qids": fire1, "rate": len(fire1) / 40, "added_composes": len(fire1),
                            "added_cost_usd": round(len(fire1) * mean_cost, 6),
                            "over_ceiling": len(fire1) / 40 > ceil},
        "floor_2_sensitivity": {"fire_qids": fire2, "rate": len(fire2) / 40, "added_composes": len(fire2),
                                "added_cost_usd": round(len(fire2) * mean_cost, 6),
                                "over_ceiling": len(fire2) / 40 > ceil,
                                "note": "many answers cite only 1 doc -> if this floor is chosen it is an "
                                        "UPSTREAM-RETRIEVAL coverage signal, not something to mask with retries"},
    }

    # 4) X33 LIVE demo — flag ON, forced trigger, real before/after citations
    allow = service._allowlist("v4")
    Q = {q["id"]: q for q in json.loads((ROOT / "reports/pilot-eval subset/draft_queries_v1.json").read_text(encoding="utf-8"))["queries"]}
    x33 = Q["X33"]
    rr = retrieval.run(x33["query"], allow)["retrieval"]
    directives = service._directives(x33["query"], retrieval.run(x33["query"], allow)["route"])
    transport = service._resolve_transport()
    config.EXPAND_ON_DEMAND_ENABLED = True
    config.EXPAND_TRIGGER_MIN_CITATIONS = 3     # demo floor: force the trigger on X33's low-cite first pass
    comp = service.compose_with_expand(x33["query"], rr["selected"], directives)
    before = (comp.get("first_pass", {}).get("envelope") or {}).get("doc_ids_cited") if comp.get("expanded") else \
             (comp.get("envelope") or {}).get("doc_ids_cited")
    after = (comp.get("envelope") or {}).get("doc_ids_cited") if comp.get("expanded") else None
    config.EXPAND_ON_DEMAND_ENABLED = False
    config.EXPAND_TRIGGER_MIN_CITATIONS = 1
    print(f"\n[4] X33 LIVE (flag ON, demo floor=3, transport={transport}):")
    print(f"    triggered={comp.get('triggered')} expanded={comp.get('expanded')}")
    print(f"    citations BEFORE (first pass): {before}")
    print(f"    citations AFTER  (expanded)  : {after}  envelope.expanded={comp.get('envelope',{}).get('expanded')}")
    report["x33_live_demo"] = {"transport": transport, "demo_floor": 3,
                               "triggered": comp.get("triggered"), "expanded": comp.get("expanded"),
                               "citations_before": before, "citations_after": after,
                               "envelope_expanded_flag": (comp.get("envelope") or {}).get("expanded")}

    report["config"] = {"EXPAND_ON_DEMAND_ENABLED_default": False, "EXPAND_TRIGGER_MIN_CITATIONS": 1,
                        "EXPAND_MAX_CHUNKS": config.EXPAND_MAX_CHUNKS, "EXPAND_FIRE_RATE_CEILING": ceil}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nSUMMARY: no-regression {report['no_regression_flag_off']['PASS']} | hard-cap=1 {report['hard_cap_1']['PASS']} | "
          f"fire-rate(default) {len(fire1)}/40 | X33 triggered={comp.get('triggered')}")
    print("wrote", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
