"""
W2.4 self-checks (retrieval-only, $0): coverage, idempotency GATE, no-regression
GATE (flag OFF == arch-baseline-v2), temporal spot-check (flag ON).
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config, service, retrieval  # noqa: E402
OUT = ROOT / "eval" / "results" / "w2_4_date_index_selfcheck.json"
def did(c): return c.split("::")[0]


def main():
    allow = service._allowlist("v4")
    prov = json.loads((ROOT / "data/index/date_index_provenance.json").read_text(encoding="utf-8"))
    table = json.loads((ROOT / "data/index/date_index.json").read_text(encoding="utf-8"))

    # 1) COVERAGE
    print("=== COVERAGE ===")
    print(f"docs {prov['n_docs']} | dated {prov['dated']} | undated {prov['undated']}")
    print("precision:", prov["precision_counts"])
    print("by source-class x precision:", prov["by_source_class_precision"])
    print("undated doc_ids:", prov["undated_doc_ids"])

    # 2) IDEMPOTENCY GATE — rebuild, compare sha
    r = subprocess.run([sys.executable, str(ROOT / "scripts/build_date_index.py")], capture_output=True, text=True)
    resha = json.loads((ROOT / "data/index/date_index_provenance.json").read_text(encoding="utf-8"))["sha256"]
    idem = resha == prov["sha256"]
    print(f"\n=== IDEMPOTENCY GATE === rebuild sha == original: {idem} ({prov['sha256'][:12]})")
    if not idem:
        print("STOP: date-table hash changed on re-run.", file=sys.stderr); return 2

    # 3) NO-REGRESSION GATE — flag OFF, all 40 frozen queries vs arch_baseline_v2 retrieved_chunk_ids
    assert config.DATE_INDEX_ENABLED is False, "flag must default OFF"
    v2 = {q["qid"]: q for q in json.loads((ROOT / "arch_baseline_v2.json").read_text(encoding="utf-8"))["queries"]}
    Q = json.loads((ROOT / "reports/pilot-eval subset/draft_queries_v1.json").read_text(encoding="utf-8"))["queries"]
    mism = []
    for q in Q:
        got = [c for c, _, _ in retrieval.run(q["query"], allow)["retrieval"]["selected"]]
        exp = v2[q["id"]]["retrieved_chunk_ids"]
        if got != exp:
            mism.append({"qid": q["id"], "got": got, "exp": exp})
    noreg = not mism
    print(f"\n=== NO-REGRESSION GATE (flag OFF, 40q vs arch-baseline-v2) === byte-identical: {noreg}")
    if not noreg:
        print("STOP: retrieval changed with flag OFF ->", [m['qid'] for m in mism], file=sys.stderr); return 3

    # 4) TEMPORAL SPOT-CHECK — flag ON, an explicit-year query resolves to that year
    spot_q = "What did Chief Justice Panganiban write about the rule of law in 2016?"
    ti = retrieval.temporal_intent(spot_q)
    config.DATE_INDEX_ENABLED = False
    before = [c for c, _, _ in retrieval.run(spot_q, allow)["retrieval"]["selected"]]
    config.DATE_INDEX_ENABLED = True
    r_on = retrieval.run(spot_q, allow)["retrieval"]
    after = [c for c, _, _ in r_on["selected"]]
    config.DATE_INDEX_ENABLED = False
    def yrs(cids): return sorted({(table.get(did(c)) or {}).get("date_iso", "?")[:4] for c in cids})
    after_docs = [did(c) for c in after]
    all_2016 = all((table.get(d) or {}).get("date_iso", "").startswith("2016") for d in after_docs)
    print("\n=== TEMPORAL SPOT-CHECK (flag ON) ===")
    print(f"query: {spot_q}\n intent: {ti}")
    print(f" BEFORE (flag off) top docs: {[did(c) for c in before][:8]} years={yrs(before)}")
    print(f" AFTER  (flag on)  top docs: {after_docs[:8]} years={yrs(after)}")
    print(f" date_filter diag: {r_on['cutoff'].get('date_filter')}")
    print(f" ALL after-docs dated 2016: {all_2016}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "coverage": {"n_docs": prov["n_docs"], "dated": prov["dated"], "undated": prov["undated"],
                     "precision_counts": prov["precision_counts"],
                     "by_source_class_precision": prov["by_source_class_precision"],
                     "undated_doc_ids": prov["undated_doc_ids"]},
        "idempotency": {"sha256": prov["sha256"], "rebuild_sha256": resha, "stable": idem},
        "no_regression_flag_off": {"queries_checked": len(Q), "byte_identical": noreg, "mismatches": mism},
        "temporal_spotcheck_flag_on": {"query": spot_q, "intent": ti,
                                       "before_docs": [did(c) for c in before], "before_years": yrs(before),
                                       "after_docs": after_docs, "after_years": yrs(after),
                                       "date_filter_diag": r_on["cutoff"].get("date_filter"),
                                       "all_after_dated_2016": all_2016},
        "provenance": {"date_table_sha256": prov["sha256"], "git_commit": prov["git_commit"],
                       "DATE_INDEX_ENABLED_default": config.DATE_INDEX_ENABLED},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nSUMMARY: coverage {prov['dated']}/{prov['n_docs']} dated | idempotent {idem} | "
          f"no-regression {noreg} | temporal spot-check {all_2016}")
    print("wrote", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
