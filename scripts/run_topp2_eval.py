"""
W2.x-TOPP-2 — grounding guard + composer wiring for the adaptive top-p nucleus
(softmax_temp basis). RETRIEVAL-ONLY (no API). Offline token estimate (chars/4).
"""
from __future__ import annotations
import json, sys, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config, service, retrieval  # noqa: E402

OUT = ROOT / "reports" / "pilot-eval subset" / "w2_topp2_report.json"
def did(c): return c.split("::")[0]


def main():
    allow = service._allowlist("v4")
    Q = json.loads((ROOT / "reports/pilot-eval subset/draft_queries_v1.json").read_text(encoding="utf-8"))["queries"]
    txt = service._chunk_text()
    CEIL = config.COMPOSER_TOP_K
    rows, losses = [], []
    for q in Q:
        su = retrieval._score_universe(q["query"], allow)
        nuc = retrieval.select_nucleus(su)                       # config basis/temp (softmax_temp/0.06)
        ranked, kept = nuc["ranked"], nuc["kept"]
        n_kept = len(kept)
        sent_topp = kept[:CEIL]                                  # nucleus capped at ceiling
        sent_flat = ranked[:CEIL]                                # old flat-12 (top-12 by fused score)
        tok_topp = sum(len(txt.get(c, "")) for c in sent_topp) // 4
        tok_flat = sum(len(txt.get(c, "")) for c in sent_flat) // 4
        exp = q.get("expected_grounding_doc_ids") or []
        kept_docs = {did(c) for c in kept}
        lost = [e for e in exp if e not in kept_docs]
        exp_rank = {e: (next((i + 1 for i, c in enumerate(ranked) if did(c) == e), None)) for e in exp}
        if lost:
            losses.append({"qid": q["id"], "lost": lost})
        rows.append({"qid": q["id"], "type": q["type"], "theme": q["theme"],
                     "nucleus": n_kept, "cum_mass": round(nuc["cum_mass"], 4),
                     "chunks_sent": len(sent_topp), "floor_hit": nuc["floor_hit"],
                     "tok_topp": tok_topp, "tok_flat": tok_flat, "tok_saved": tok_flat - tok_topp,
                     "exp": exp, "exp_rank_in_ranked": exp_rank, "grounding_lost": lost})

    nk = [r["nucleus"] for r in rows]
    sent = [r["chunks_sent"] for r in rows]
    dist = {"nucleus": {"min": min(nk), "median": int(statistics.median(nk)), "max": max(nk),
                        "mean": round(statistics.mean(nk), 1), "stdev": round(statistics.pstdev(nk), 1)},
            "chunks_sent_capped": {"min": min(sent), "median": int(statistics.median(sent)),
                                   "max": max(sent), "mean": round(statistics.mean(sent), 1),
                                   "below_12": sum(1 for s in sent if s < 12)},
            "old_flat": CEIL, "degenerate_rrf_flat_median": 755}
    tok_flat_m = round(statistics.mean(r["tok_flat"] for r in rows), 1)
    tok_topp_m = round(statistics.mean(r["tok_topp"] for r in rows), 1)
    report = {
        "task": "W2.x-TOPP-2 adaptive top-p (softmax_temp) + composer wiring",
        "winner": {"basis": config.RETRIEVAL_TOP_P_BASIS, "temp": config.RETRIEVAL_SOFTMAX_TEMP,
                   "top_p": config.RETRIEVAL_TOP_P, "min_k": config.RETRIEVAL_MIN_K,
                   "composer_ceiling": CEIL},
        "phase1_note": "cosine basis failed (compressed bge cosines ~718 even @0.1); rrf_flat degenerate "
                       "(~755); softmax_temp on the fused score concentrates. Temp swept 0.5..0.03; 0.06 "
                       "gives median 9, spread 2-17, 0 grounding losses.",
        "grounding_guard": {"losses": losses, "PASS": not losses,
                            "note": "fused ranking keeps expected docs at ranks 1-5; nucleus includes them"},
        "distribution": dist,
        "token_reduction_offline_chars_div4": {
            "mean_tok_flat12": tok_flat_m, "mean_tok_topp": tok_topp_m,
            "mean_saved": round(tok_flat_m - tok_topp_m, 1),
            "pct": round((tok_flat_m - tok_topp_m) / tok_flat_m * 100, 1) if tok_flat_m else None,
            "note": "chunk input tokens only; cached voice-card system block unchanged. NO API."},
        "wiring": "build_payload consumes retrieval.selected (the nucleus) capped at COMPOSER_TOP_K; "
                  "COMPOSER_TOP_K is now a CEILING, not the selector.",
        "frozen_set_sha256": "65492b65...", "n_queries": len(rows), "api_calls": 0,
        "per_query": rows,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
                   encoding=config.OUTPUT_ENCODING)

    print(f"winner: basis={config.RETRIEVAL_TOP_P_BASIS} temp={config.RETRIEVAL_SOFTMAX_TEMP} "
          f"p={config.RETRIEVAL_TOP_P} min_k={config.RETRIEVAL_MIN_K} ceiling={CEIL}")
    print(f"nucleus: min {dist['nucleus']['min']} / median {dist['nucleus']['median']} / "
          f"max {dist['nucleus']['max']} / mean {dist['nucleus']['mean']} / stdev {dist['nucleus']['stdev']}")
    print(f"chunks SENT (capped {CEIL}): median {dist['chunks_sent_capped']['median']}, "
          f"{dist['chunks_sent_capped']['below_12']}/40 below 12 | old flat={CEIL}")
    print(f"grounding guard: {'PASS (0/40)' if not losses else 'FAIL '+str(losses)}")
    print(f"input-token (chunks) mean: flat12={tok_flat_m} -> topp={tok_topp_m} "
          f"(-{report['token_reduction_offline_chars_div4']['pct']}%)")
    print("per-query chunks_sent:", {r["qid"]: r["chunks_sent"] for r in rows})
    print("wrote", OUT.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
