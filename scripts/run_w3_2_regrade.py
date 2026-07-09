"""
W3.2 RE-GRADE — $0, NO re-run. Recompute scope-aware recall@k for the EXISTING
arch-baseline-v3 retrieval (captured retrieved_docs) against Sheena's CORRECTED
v4 gold. Retrieval unchanged; only the answer key changed. No API/retrieval/compose.
"""
from __future__ import annotations
import csv, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "eval" / "results" / "gold_reference_set.csv"
V3_FULL = ROOT / "eval" / "results" / "w3_2_FULL_v3_c1637cd.json"
SENT = {"OOS", "META", "GAP"}
LOWCONF = {"B10", "C14", "C17", "C18", "D24", "X40"}
W21_OLDGOLD = {1: 0.433, 3: 0.733, 5: 0.807, 10: 0.821}   # w2.1 (MIN_K=3) + OLD gold, from prior task


def main():
    G = list(csv.DictReader(open(GOLD, encoding="utf-8-sig")))
    assert len(G) == 40, f"expected 40 gold rows, got {len(G)}"
    assert all((r.get("retrieved_docs") or "").strip() for r in G), "some qids lack retrieved_docs -> STOP"

    def gold_of(r): return [d.strip() for d in (r["gold_source_docs"] or "").split(";") if d.strip() and d.strip() not in SENT]
    def retr_of(r): return [d.strip() for d in (r["retrieved_docs"] or "").split(";") if d.strip()]

    insc = [r for r in G if r["scope_gold"] == "in"]           # recall denominator (34)
    rows = []
    for r in G:
        qid, scope = r["qid"], r["scope_gold"]
        gd, rd = gold_of(r), retr_of(r)
        rec = {"qid": qid, "scope_gold": scope, "qtype": r["qtype"], "gold_confidence": r["gold_confidence"],
               "gold_v4": gd, "retrieved_docs": rd, "in_denominator": scope == "in"}
        if scope == "in":
            def hit(k): return any(d in gd for d in rd[:k])
            best = next((i + 1 for i, d in enumerate(rd) if d in gd), None)
            rec.update({f"hit@{k}": hit(k) for k in (1, 3, 5, 10)})
            rec["best_gold_rank"] = best
            rec["retrieved_at_all"] = best is not None
        rows.append(rec)

    def recall(k): return round(sum(1 for r in rows if r["in_denominator"] and r[f"hit@{k}"]) / len(insc), 3)
    rk = {k: recall(k) for k in (1, 3, 5, 10)}

    # recall@1 split
    r1_miss = [r for r in rows if r["in_denominator"] and not r["hit@1"]]
    ranking = [(r["qid"], r["best_gold_rank"]) for r in r1_miss if r["retrieved_at_all"]]
    coverage = [r["qid"] for r in r1_miss if not r["retrieved_at_all"]]
    a4 = next(r for r in rows if r["qid"] == "A4"); e28 = next(r for r in rows if r["qid"] == "E28")

    # carry forward (DO NOT recompute) from the v3 FULL run
    v3 = json.loads(V3_FULL.read_text(encoding="utf-8"))
    carried = {
        "fabrication": f"{v3['C_grounding']['fabricated_citations']}/40 (carried from v3 run — pipeline identical)",
        "empty_cited_in_scope": f"{len(v3['C_grounding']['coverage_empty_cited_qids'])} (carried)",
        "MIN_K_verdict": v3["E_min_k_verdict"]["VERDICT"] + " (carried; recall-backed on v3)",
        "OOS": "gate inert at threshold %.2f (never declines); X35 declined by composer, X36 did NOT (carried)"
               % v3["D_scope_behavior"]["oos_threshold"],
        "note": "grounding/MIN_K/OOS are RETRIEVAL/COMPOSE outcomes unchanged by a gold re-grade; carried verbatim.",
    }
    lowconf_miss = [r["qid"] for r in rows if r["in_denominator"] and not r["hit@5"] and r["qid"] in LOWCONF]

    three_way = {str(k): {
        "w2_1_MINK3__old_gold": W21_OLDGOLD[k],
        "w2_1_MINK3__v4_gold__SHEENA": "n/a — Sheena-owned (w2.1 retrieved_docs not in this repo; xlsx absent)",
        "v3_MINK4_topP__v4_gold__CANONICAL": rk[k]} for k in (1, 3, 5, 10)}

    report = {
        "task": "W3.2 RE-GRADE (v3 retrieval + v4-corrected gold) — $0, NO re-run",
        "method": "REGRADE-no-rerun: retrieved_docs READ from gold_reference_set.csv (the v3 canonical retrieval "
                  "capture — confirmed authentic: A4 CA377@rank3, E28 CE007@rank4, B9 gold not retrieved). "
                  "NOTE: the task named w3_2_full_per_query.csv but that CSV has no retrieved_docs column; the "
                  "ranked retrieved_docs live in gold_reference_set.csv. No retrieval/composition/API run.",
        "provenance": {"source_artifact": "eval/results/gold_reference_set.csv (retrieved_docs = v3 capture)",
                       "gold": "gold_reference_set.csv (v4-corrected)", "pipeline": "arch-baseline-v3 / c1637cd",
                       "method": "REGRADE-no-rerun", "api_spend_usd": 0.0,
                       "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")},
        "A_canonical_recall": {"recall_at_k": rk, "denominator_N": len(insc),
                               "denominator_qids": sorted(r["qid"] for r in insc),
                               "excluded_gap": [r["qid"] for r in G if "gap" in r["scope_gold"].lower()],
                               "matching_rule": "hit@k = any of top-k retrieved doc_ids in gold_source_docs (v4)"},
        "B_recall1_split": {"recall@1": rk[1], "misses": len(r1_miss),
                            "ranking_retrieved_but_lower": ranking,
                            "coverage_not_retrieved": coverage,
                            "A4_now_hit": {"gold": a4["gold_v4"], "best_rank": a4["best_gold_rank"], "hit@3": a4["hit@3"]},
                            "E28_now_hit": {"gold": e28["gold_v4"], "best_rank": e28["best_gold_rank"], "hit@5": e28["hit@5"]},
                            "B9_sole_coverage_miss": "B9" in coverage},
        "C_three_way_comparison": {"note": "each cell labeled pipeline+gold to avoid apples-to-oranges; the "
                                           "CANONICAL baseline is the v3+v4-gold column.", "table": three_way},
        "D_carried_forward_not_recomputed": carried,
        "E_low_confidence_caveat": {"missed_at5_lowconf": lowconf_miss,
                                    "note": "verify gold (low-confidence, SME-confirm pending) — do NOT attribute to pipeline"},
        "per_query": rows,
    }
    RES = ROOT / "eval" / "results"
    (RES / "w3_2_REGRADE_v3_v4gold.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with open(RES / "w3_2_regrade_per_query.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["qid", "scope_gold", "gold_v4", "retrieved_docs", "hit@1", "hit@3", "hit@5", "hit@10",
                    "in_denominator", "best_gold_rank", "miss_type"])
        for r in rows:
            w.writerow([r["qid"], r["scope_gold"], ";".join(r["gold_v4"]), ";".join(r["retrieved_docs"]),
                        r.get("hit@1", ""), r.get("hit@3", ""), r.get("hit@5", ""), r.get("hit@10", ""),
                        r["in_denominator"], r.get("best_gold_rank", ""), ""])  # miss_type blank for Sheena

    print("=== W3.2 RE-GRADE (v3 retrieval + v4 gold, $0 no re-run) ===")
    print(f"CANONICAL recall@1/3/5/10 = {rk[1]}/{rk[3]}/{rk[5]}/{rk[10]} | denominator N={len(insc)} (in-scope; X33/X39 GAP excluded)")
    print(f"recall@1 split: ranking={ranking} | coverage(not-retrieved)={coverage}")
    print(f"A4 now hit: gold {a4['gold_v4']} @rank {a4['best_gold_rank']} (hit@3={a4['hit@3']}) | "
          f"E28: gold {e28['gold_v4']} @rank {e28['best_gold_rank']} (hit@5={e28['hit@5']}) | B9 sole coverage miss: {'B9' in coverage}")
    print("three-way recall@k:")
    for k in (1, 3, 5, 10):
        print(f"  @{k}: w2.1+old-gold {W21_OLDGOLD[k]} | w2.1+v4-gold (Sheena) n/a | v3+v4-gold CANONICAL {rk[k]}")
    print(f"carried fwd: {carried['fabrication']}; MIN_K {carried['MIN_K_verdict']}")
    print(f"low-conf misses@5: {lowconf_miss or 'none'}")
    print("wrote eval/results/w3_2_REGRADE_v3_v4gold.json + w3_2_regrade_per_query.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
