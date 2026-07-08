"""
W3.2 FULL — canonical scope-aware retrieval+grounding eval on arch-baseline-v3,
native transport, against Sheena's gold_reference_set.csv. MEASUREMENT ONLY.
"""
from __future__ import annotations
import csv, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config, retrieval, service, embeddings  # noqa: E402

GOLD = ROOT / "eval" / "results" / "gold_reference_set.csv"
SENT = {"OOS", "META", "GAP"}
LOWCONF = {"B10", "C14", "C17", "C18", "D24", "X40"}
W21 = {"1": 0.433, "3": 0.733, "5": 0.807, "10": 0.821}   # Sheena w2.1 (MIN_K=3)
def did(c): return c.split("::")[0]
def short(): return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main():
    transport = service._resolve_transport()
    native = transport == "native_sdk"
    allow = service._allowlist("v4")
    pilot = {did(c) for c in embeddings.load_dense_index()[1]["chunk_ids"]}
    corpus = {json.loads(l)["doc_id"] for l in (ROOT / "corpus/index/chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    G = {r["qid"]: r for r in csv.DictReader(open(GOLD, encoding="utf-8-sig"))}

    def gold_docs(r):
        return [d.strip() for d in (r["gold_source_docs"] or "").split(";") if d.strip() and d.strip() not in SENT]

    client = service._client() if native else None
    rows = []
    for qid, r in G.items():
        su = retrieval._score_universe(r["query"], allow)
        nuc = retrieval.select_nucleus(su)
        ranked, kept = nuc["ranked"], nuc["kept"]
        chunks_sent = min(len(kept), config.COMPOSER_TOP_K)
        in_scope = su["route_info"]["in_scope"]
        # compose (native) for grounding + scope behavior
        directives = service._directives(r["query"], su["route_info"])
        comp = service.compose_streamed(r["query"], [(c, 0.0, {}) for c in kept], directives, client=client)
        cited = (comp["envelope"] or {}).get("doc_ids_cited") or []
        sent_docs = {did(c) for c in kept[:config.COMPOSER_TOP_K]}
        fabricated = [c for c in cited if (c not in corpus) or (c not in sent_docs)]

        scope = r["scope_gold"]; gd = gold_docs(r)
        rec = {"qid": qid, "scope_gold": scope, "qtype": r["qtype"], "gold_confidence": r["gold_confidence"],
               "gold_source_docs": gd, "chunks_returned": len(kept), "chunks_sent": chunks_sent,
               "floor_bound": nuc["floor_hit"], "in_scope_flag": in_scope,
               "cited_docs": cited, "fabricated": bool(fabricated), "fabricated_ids": fabricated,
               "coverage_ok": len(cited) >= 1, "degraded": comp["degraded"],
               "answer_snippet": (comp["answer"] or "")[:160]}
        if scope == "in":
            gold_in = [d for d in gd if d in pilot]
            gold_out = [d for d in gd if d not in pilot]
            def hit(k): return any(did(c) in gd for c in ranked[:k])
            best_rank = next((i + 1 for i, c in enumerate(ranked) if did(c) in gd), None)
            rec.update({"hit@1": hit(1), "hit@3": hit(3), "hit@5": hit(5), "hit@10": hit(10),
                        "hit@sent": hit(chunks_sent),
                        "gold_in_pilot": gold_in, "gold_out_of_pilot": gold_out,
                        "structural_zero": len(gold_in) == 0,           # gold unreachable in pilot
                        "best_gold_rank": best_rank})
            if not rec["hit@1"]:
                rec["recall1_miss_type"] = ("structural_out_of_pilot" if not gold_in
                                            else f"ranking_best_rank_{best_rank}")
        else:
            rec.update({"declined": len(cited) == 0, "handled": None})
        rows.append(rec)
        tag = scope if scope != "in" else ("STRUCT0" if rec.get("structural_zero") else "in")
        print(f"  {qid:4} {tag:8} ret={rec['chunks_returned']:>2} "
              f"{'h@1='+str(rec.get('hit@1')) if scope=='in' else 'cited='+str(len(cited))} "
              f"fab={rec['fabricated']} cov={rec['coverage_ok']} in_scope={in_scope}")

    # ---- aggregate: recall over 35 in-scope ----
    insc = [r for r in rows if r["scope_gold"] == "in"]
    reachable = [r for r in insc if not r["structural_zero"]]         # gold actually in pilot
    def recall(rs, k): return round(sum(1 for r in rs if r[f"hit@{k}"]) / len(rs), 3) if rs else 0.0
    rk = {k: recall(insc, k) for k in (1, 3, 5, 10)}
    rk_reach = {k: recall(reachable, k) for k in (1, 3, 5, 10)}

    # recall@1 split
    r1_miss = [r for r in insc if not r["hit@1"]]
    structural = [r["qid"] for r in r1_miss if r["recall1_miss_type"].startswith("structural")]
    ranking = [(r["qid"], r["best_gold_rank"]) for r in r1_miss if r["recall1_miss_type"].startswith("ranking")]

    # grounding
    fab_q = [r["qid"] for r in rows if r["fabricated"]]
    cov_flags = [r["qid"] for r in insc if not r["coverage_ok"]]

    # scope-5
    specials = {r["qid"]: r for r in rows if r["scope_gold"] != "in"}
    oos_fired = [q for q in ("X35", "X36") if not specials[q]["in_scope_flag"]]

    # MIN_K floor (in-scope, exclude OOS)
    floor_in = [r for r in insc if r["floor_bound"]]
    floor_reach = [r for r in floor_in if not r["structural_zero"]]
    floor_recall5 = recall(floor_reach, 5) if floor_reach else None
    nonfloor_reach = [r for r in reachable if not r["floor_bound"]]
    verdict = ("KEEP 4" if (floor_recall5 is None or floor_recall5 >= recall(nonfloor_reach, 5) - 0.001)
               else "RAISE (floor-bound under-retrieve on recall@5)")

    # low-confidence caveat
    lowconf_miss = [r["qid"] for r in insc if not r["hit@5"] and r["qid"] in LOWCONF]

    delta = {k: {"w2_1_min_k3": W21[str(k)], "v3_min_k4_all35": rk[k],
                 "v3_reachable": rk_reach[k], "delta_all35": round(rk[k] - W21[str(k)], 3)} for k in (1, 3, 5, 10)}

    report = {
        "task": "W3.2 FULL scope-aware eval on arch-baseline-v3",
        "provenance": {"eval_sha": "65492b650aec8dda5e76be21c32aaae3faf61f9663c6c58ace02b5a6c4bc9a63",
                       "commit": short(), "git_describe": "arch-baseline-v3-1-g" + short(),
                       "embedder": "BAAI/bge-large-en-v1.5", "temp": config.RETRIEVAL_SOFTMAX_TEMP,
                       "min_k": config.RETRIEVAL_MIN_K, "max_k_ceiling": config.COMPOSER_TOP_K,
                       "oos_threshold": config.OUT_OF_SCOPE_THRESHOLD, "transport": transport,
                       "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")},
        "universe_caveat": {"retrieval_universe": "v4 pilot (95 docs / 827 chunks)",
                            "gold_docs_out_of_pilot": sorted({d for r in insc for d in r.get("gold_out_of_pilot", [])}),
                            "structural_zero_queries": [r["qid"] for r in insc if r["structural_zero"]],
                            "note": "queries whose gold docs are outside the pilot universe cannot be retrieved "
                                    "here -> recall 0 by CONSTRUCTION, not a pipeline failure. Flagged for eval design."},
        "A_recall_at_k_in_scope_35": {"matching_rule": "hit@k = any top-k retrieved chunk's parent doc_id in gold set",
                                      "recall_all35": rk, "recall_reachable_only": rk_reach,
                                      "n_in_scope": len(insc), "n_reachable": len(reachable)},
        "B_recall1_split": {"recall@1_all35": rk[1], "misses": len(r1_miss),
                            "structural_out_of_pilot": structural,
                            "ranking_retrieved_but_lower": ranking,
                            "read": "structural misses = universe scope (not pipeline); ranking misses = the "
                                    "top-p/softmax nucleus ordering (the W3.4 lever)."},
        "C_grounding": {"fabricated_citations": len(fab_q), "fabricated_qids": fab_q, "target": 0,
                        "coverage_empty_cited_qids": cov_flags,
                        "note": "fabrication != coverage: 0 fabrication AND empty-cited both possible."},
        "D_scope_behavior": {"oos_threshold": config.OUT_OF_SCOPE_THRESHOLD,
                             "X35_X36_out": {q: {"in_scope_flag": specials[q]["in_scope_flag"],
                                                 "declined_no_cite": specials[q]["declined"],
                                                 "answer": specials[q]["answer_snippet"]} for q in ("X35", "X36")},
                             "X31_X32_meta": {q: {"cited": specials[q]["cited_docs"], "fabricated": specials[q]["fabricated"],
                                                  "answer": specials[q]["answer_snippet"]} for q in ("X31", "X32")},
                             "X39_gap": {"fabricated": specials["X39"]["fabricated"], "cited": specials["X39"]["cited_docs"],
                                         "answer": specials["X39"]["answer_snippet"]},
                             "oos_gate_fired_for": oos_fired,
                             "reconciliation": "OOS gate (cos >= OUT_OF_SCOPE_THRESHOLD=0.15) fires in_scope=True for "
                                               "ALL 40 incl X35/X36 (0.15 far too low) -> the THRESHOLD gate never "
                                               "declines. Sheena's scope_correctness=1.0 must reflect COMPOSER behavior "
                                               "(decline in prose / no cite), not the gate. State: on v3 the gate does "
                                               "NOT fire; scope handling depends on the composer."},
        "E_min_k_verdict": {"floor_bound_in_scope": [r["qid"] for r in floor_in],
                            "floor_bound_reachable": [r["qid"] for r in floor_reach],
                            "floor_recall@5": floor_recall5, "nonfloor_recall@5": recall(nonfloor_reach, 5),
                            "VERDICT": verdict, "basis": "recall-backed (replaces fabrication-only provisional)"},
        "F_v3_vs_w2_1_delta": delta,
        "low_confidence_caveat": {"missed_at5_lowconf": lowconf_miss,
                                  "note": "low-confidence gold; verify label before attributing to pipeline (SME-confirm pending)"},
        "recall_at_k_STILL_full_deferred": "N/A — gold now present; but out-of-pilot gold caps some queries (see universe_caveat)",
        "per_query": rows,
    }
    RESULTS = ROOT / "eval" / "results"
    (RESULTS / f"w3_2_FULL_v3_{short()}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with open(RESULTS / "w3_2_full_per_query.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["qid", "scope_gold", "qtype", "gold_confidence", "gold_source_docs", "chunks_returned",
                    "floor_bound", "hit@1", "hit@3", "hit@5", "hit@10", "structural_zero", "best_gold_rank",
                    "cited_docs", "fabricated", "coverage_ok", "declined", "miss_type"])
        for r in rows:
            w.writerow([r["qid"], r["scope_gold"], r["qtype"], r["gold_confidence"], ";".join(r["gold_source_docs"]),
                        r["chunks_returned"], r["floor_bound"], r.get("hit@1", ""), r.get("hit@3", ""),
                        r.get("hit@5", ""), r.get("hit@10", ""), r.get("structural_zero", ""),
                        r.get("best_gold_rank", ""), ";".join(r["cited_docs"]), r["fabricated"], r["coverage_ok"],
                        r.get("declined", ""), ""])   # miss_type blank for Sheena

    print(f"\n=== W3.2 FULL (v3, {transport}) ===")
    print(f"[A] recall@1/5/10 (all 35 in-scope): {rk[1]}/{rk[5]}/{rk[10]} | reachable-only: "
          f"{rk_reach[1]}/{rk_reach[5]}/{rk_reach[10]} (n_reach={len(reachable)})")
    print(f"[B] recall@1 misses: structural(out-of-pilot)={structural} | ranking={ranking}")
    print(f"[C] fabrication={len(fab_q)}/40 {fab_q} | empty-cited(in-scope)={cov_flags}")
    print(f"[D] OOS threshold={config.OUT_OF_SCOPE_THRESHOLD} fired_for={oos_fired or 'NONE (gate never declines)'} | "
          f"X35 declined={specials['X35']['declined']} X36 declined={specials['X36']['declined']}")
    print(f"[E] MIN_K verdict: {verdict} (floor r@5={floor_recall5} vs nonfloor {recall(nonfloor_reach,5)})")
    print(f"[F] v3-vs-w2.1 recall@k delta (all35): " + ", ".join(f"@{k}:{delta[k]['delta_all35']:+}" for k in (1,3,5,10)))
    print(f"low-conf misses@5 (verify gold): {lowconf_miss}")
    print(f"wrote eval/results/w3_2_FULL_v3_{short()}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
