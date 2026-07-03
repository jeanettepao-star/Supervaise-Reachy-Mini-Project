"""
W2.x-TOPP — evaluate the top-p (nucleus) retrieval cutoff over the frozen 40-set.
RETRIEVAL-ONLY (no API). Grounding guard + chunks-kept distribution vs old flat-12.
"""
from __future__ import annotations
import json, sys, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config, service, retrieval  # noqa: E402

OUT = ROOT / "reports" / "pilot-eval subset" / "w2_topp_report.json"
def did(c): return c.split("::")[0]


def main():
    allow = service._allowlist("v4")
    Q = json.loads((ROOT / "reports/pilot-eval subset/draft_queries_v1.json").read_text(encoding="utf-8"))["queries"]
    rows, losses = [], []
    for q in Q:
        r = retrieval.run(q["query"], allow)
        rr = r["retrieval"]; cut = rr["cutoff"]
        kept = [c for c, _, _ in rr["selected"]]
        kept_docs = {did(c) for c in kept}
        exp = q.get("expected_grounding_doc_ids") or []
        lost = [e for e in exp if e not in kept_docs]
        if lost:
            losses.append({"qid": q["id"], "lost": lost, "n_kept": cut["n_kept"]})
        rows.append({"qid": q["id"], "type": q["type"], "theme": q["theme"],
                     "n_kept": cut["n_kept"], "cum_mass": cut["cum_mass"],
                     "floor_hit": cut["min_k_floor_hit"],
                     "exp": exp, "exp_in_kept": [e for e in exp if e in kept_docs], "lost": lost,
                     "llm_pre": r["llm_calls_before_composition"]})

    nk = [r["n_kept"] for r in rows]
    dist = {"min": min(nk), "median": int(statistics.median(nk)), "max": max(nk),
            "mean": round(statistics.mean(nk), 2),
            "min_k_floor_hits": sum(1 for r in rows if r["floor_hit"]),
            "old_flat": config.MAX_K}
    report = {
        "task": "W2.x-TOPP nucleus retrieval cutoff",
        "config": {"RETRIEVAL_TOP_P": config.RETRIEVAL_TOP_P, "RETRIEVAL_MIN_K": config.RETRIEVAL_MIN_K,
                   "normalization": "score_i / sum(max(score,0)) over the ranked candidate universe; "
                                    "score = passage_sim(min-max RRF) + LAMBDA*topic_affinity",
                   "retired_as_selection_gate": ["MAX_K", "MIN_K", "TAU"],
                   "MAX_K_still_used_by": "COMPOSER_TOP_K default (composer-side, out of scope) + baseline snapshots"},
        "frozen_set_sha256": "65492b65...", "n_queries": len(rows),
        "grounding_guard": {"losses": losses, "PASS": not losses},
        "distribution_chunks_kept": dist,
        "per_query": rows,
        "llm_calls_before_composition_all_zero": all(r["llm_pre"] == 0 for r in rows),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
                   encoding=config.OUTPUT_ENCODING)

    print(f"n={len(rows)} | TOP_P={config.RETRIEVAL_TOP_P} MIN_K={config.RETRIEVAL_MIN_K}")
    print(f"chunks kept: min={dist['min']} median={dist['median']} max={dist['max']} mean={dist['mean']} "
          f"| MIN_K-floor hits={dist['min_k_floor_hits']} | old flat={dist['old_flat']}")
    print(f"grounding guard: {'PASS (0 losses)' if not losses else 'FAIL: ' + str(losses)}")
    print(f"llm_pre==0 all: {report['llm_calls_before_composition_all_zero']}")
    print("per-query n_kept:", {r["qid"]: r["n_kept"] for r in rows})
    print("wrote", OUT.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
