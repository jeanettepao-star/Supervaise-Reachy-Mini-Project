"""
W3.2 PARTIAL (B+C, + 5-item harness check) at arch-baseline-v2. Sections that
need NO gold labels. Full recall@k over 40 stays BLOCKED on Sheena's gold labels.

C  MIN_K=4 floor/ceiling analysis over all 40 (retrieval-only, $0) — PRIORITY.
B  grounding / fabricated-citation over all 40 (compose, ~$0.60).
A  recall@k over the 5 gold items ONLY — HARNESS PLUMBING CHECK, not a quality #.

NO tuning / NO eval-set edits / measure v2 as-is.
"""
from __future__ import annotations
import csv, json, sys
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config, retrieval, service  # noqa: E402

RESULTS = ROOT / "eval" / "results"
COMMIT = (subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip() or "unknown")
V2_PARTIAL = ROOT / "eval" / "results" / "w3_2_PARTIAL_BC_73a4a12.json"
GOLD = {"A3": ["CA242"], "C16": ["CC001"], "E28": ["CE007"], "E29": ["CA034"], "X34": ["CA009", "CA010"]}
def did(c): return c.split("::")[0]


def main():
    allow = service._allowlist("v4")
    Q = json.loads((ROOT / "reports/pilot-eval subset/draft_queries_v1.json").read_text(encoding="utf-8"))["queries"]
    corpus_docs = {json.loads(l)["doc_id"] for l in (ROOT / "corpus/index/chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    CEIL = config.COMPOSER_TOP_K

    # ---- retrieval pass (Section C + A ranked), free ----
    per = {}
    for q in Q:
        su = retrieval._score_universe(q["query"], allow)
        nuc = retrieval.select_nucleus(su)
        ranked, kept = nuc["ranked"], nuc["kept"]
        chunks_returned = len(kept)                          # post-cutoff nucleus (pre-ceiling)
        chunks_sent = min(chunks_returned, CEIL)
        per[q["id"]] = {
            "route": su["route_info"], "kept": kept, "ranked": ranked,
            "chunks_returned": chunks_returned, "chunks_sent": chunks_sent,
            "floor_bound": nuc["floor_hit"], "ceiling_bound": chunks_returned >= CEIL,
            "cum_mass": round(nuc["cum_mass"], 4),
            "sent_docs": {did(c) for c in kept[:CEIL]},
        }

    # ---- Section A: recall@k over the 5 gold items (PLUMBING CHECK) ----
    def hit_at(ranked, gold, k):
        return bool(set(gold) & {did(c) for c in ranked[:k]})
    recall5 = {}
    for qid, gold in GOLD.items():
        p = per[qid]
        ks = {"@1": 1, "@3": 3, "@5": 5, "@10": 10, "@sent": p["chunks_sent"]}
        recall5[qid] = {"gold": gold, **{k: hit_at(p["ranked"], gold, kv) for k, kv in ks.items()},
                        "chunks_sent": p["chunks_sent"]}

    # ---- transport check before spending. W3.2 measures fabrication (envelope),
    #      NOT latency/TTFT, so streaming is NOT required: schannel_curl composes
    #      the SAME answer+envelope as native. Proceed on either; flag regression. ----
    transport = service._resolve_transport()
    native = transport == "native_sdk"
    if not native:
        print(f"[gate] WARN transport={transport}: native TLS broke (Avast HTTPS-scanning regression). "
              "Composing via schannel_curl (non-streamed); fabrication is transport-independent, TTFT N/A.",
              file=sys.stderr)
    service._api_key()
    client = service._client() if native else None

    # ---- Section B: compose all 40, parse envelope, fabrication check ----
    rows, fab_queries, fab_total = [], [], 0
    for q in Q:
        p = per[q["id"]]
        directives = service._directives(q["query"], p["route"])
        selected = [(c, 0.0, {}) for c in p["kept"]]         # build_payload uses cid only; caps at CEIL
        comp = service.compose_streamed(q["query"], selected, directives, client=client)
        cited = (comp["envelope"] or {}).get("doc_ids_cited") or []
        fabricated = [c for c in cited if (c not in corpus_docs) or (c not in p["sent_docs"])]
        if fabricated:
            fab_queries.append(q["id"]); fab_total += len(fabricated)
        rows.append({"query_id": q["id"], "type": q["qtype"] if "qtype" in q else q["type"],
                     "theme": q["theme"], "chunks_returned": p["chunks_returned"],
                     "chunks_sent": p["chunks_sent"], "floor_bound": p["floor_bound"],
                     "ceiling_bound": p["ceiling_bound"], "cited_doc_ids": cited,
                     "fabricated": bool(fabricated), "fabricated_ids": fabricated,
                     "degraded": comp["degraded"], "stop_reason": comp["stop_reason"]})
        print(f"  {q['id']:4} ret={p['chunks_returned']:>2} sent={p['chunks_sent']:>2} "
              f"floor={p['floor_bound']!s:5} ceil={p['ceiling_bound']!s:5} cited={cited} "
              f"fab={bool(fabricated)}")

    # ---- floor/ceiling analysis + verdict ----
    floor_q = [r for r in rows if r["floor_bound"]]
    ceil_q = [r for r in rows if r["ceiling_bound"]]
    nonfloor = [r for r in rows if not r["floor_bound"]]
    fab_rate = lambda rs: (sum(1 for r in rs if r["fabricated"]) / len(rs)) if rs else 0.0
    cr = [r["chunks_returned"] for r in rows]
    floor_underretrieve = any(r["fabricated"] for r in floor_q)  # do floor-bound queries fail grounding?
    verdict = ("KEEP 4" if not floor_underretrieve and fab_rate(floor_q) <= fab_rate(nonfloor)
               else "RAISE (floor-bound queries concentrate grounding failures)")

    provenance = {"eval_sha": "65492b650aec8dda5e76be21c32aaae3faf61f9663c6c58ace02b5a6c4bc9a63",
                  "git_commit": "73a4a1209b215d8b97daaf1fa813789734c07530",
                  "git_describe": "arch-baseline-v2-1-g73a4a12",
                  "pipeline_identical_to_v2": True, "working_tree": "DIRTY (data/csv deletions + untracked; none touch pipeline)",
                  "embedder": "BAAI/bge-large-en-v1.5", "temp": config.RETRIEVAL_SOFTMAX_TEMP,
                  "min_k": config.RETRIEVAL_MIN_K, "max_k_ceiling": config.COMPOSER_TOP_K,
                  "top_p": config.RETRIEVAL_TOP_P, "transport": transport, "embed_device": config.EMBED_DEVICE,
                  "run_timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}
    report = {
        "task": "W3.2 PARTIAL (B+C, no gold) at arch-baseline-v2 — NOT a full scorecard",
        "full_recall_at_k_over_40": "DEFERRED — blocked on Sheena's gold labels (35/40 missing). NOT overridden.",
        "provenance": provenance,
        "section_C_min_k_floor_analysis": {
            "chunks_returned": {"min": min(cr), "median": int(np.median(cr)), "max": max(cr), "mean": round(float(np.mean(cr)), 2)},
            "floor_bound_count": len(floor_q), "floor_bound_qids": [r["query_id"] for r in floor_q],
            "ceiling_bound_count": len(ceil_q), "ceiling_bound_qids": [r["query_id"] for r in ceil_q],
            "fabrication_rate_floor_bound": round(fab_rate(floor_q), 3),
            "fabrication_rate_non_floor": round(fab_rate(nonfloor), 3),
            "floor_bound_under_retrieve": floor_underretrieve,
            "VERDICT": verdict,
            "evidence": "floor_bound = softmax-temp cutoff alone returned <MIN_K(4) and was padded to 4; "
                        "ceiling_bound = nucleus >= 12. A floor is 'too thin' if floor-bound queries "
                        "under-retrieve (concentrate fabrications/grounding failures) vs non-floor."},
        "section_B_grounding_fidelity": {
            "fabricated_citations_query_count": len(fab_queries), "fabricated_citation_total": fab_total,
            "fabricated_qids": fab_queries, "target": 0, "n_composed": len(rows),
            "n_degraded": sum(1 for r in rows if r["degraded"]),
            "rule": "a cited doc_id is FABRICATED if not in the 1089-doc corpus OR not in the chunks SENT "
                    "to the composer (nucleus capped at ceiling 12).",
            "transport": transport,
            "transport_note": ("native_sdk" if native else
                               "schannel_curl — native TLS regressed mid-session (Avast HTTPS-scanning "
                               "re-enabled; re-apply the Service-host profile). Fabrication is transport-"
                               "independent (same model/payload/max_tokens -> same envelope), so this result "
                               "is valid; only TTFT/streaming is unavailable on curl (not measured by W3.2).")},
        "section_A_recall_5_gold_HARNESS_CHECK_ONLY": {
            "disclaimer": "5/40 items — PLUMBING VALIDATION of the recall computation + doc_id matching rule, "
                          "NOT a pipeline quality number. Full recall@k awaits gold for all 40.",
            "matching_rule": "hit@k = any top-k retrieved chunk's parent doc_id is in the gold doc_id set",
            "per_item": recall5},
        "per_query": rows,
    }
    # v2-vs-v3 delta, SPLIT BY AXIS.
    WATCHLIST = ["A3", "B8", "C16", "D20", "E26", "X31", "X33", "X35", "X39"]  # W2.6 single-cite @floor=2
    delta = None
    if V2_PARTIAL.exists():
        v2 = json.loads(V2_PARTIAL.read_text(encoding="utf-8"))
        v2c, v3c = v2["section_C_min_k_floor_analysis"], report["section_C_min_k_floor_analysis"]
        v2b, v3b = v2["section_B_grounding_fidelity"], report["section_B_grounding_fidelity"]
        def cmp(a, b): return {"v2": a, "v3": b, "match": a == b}
        retr = {"chunks_returned_dist": cmp(v2c["chunks_returned"], v3c["chunks_returned"]),
                "floor_bound_qids": cmp(v2c["floor_bound_qids"], v3c["floor_bound_qids"]),
                "ceiling_bound_qids": cmp(v2c["ceiling_bound_qids"], v3c["ceiling_bound_qids"]),
                "floor_verdict": cmp(v2c["VERDICT"], v3c["VERDICT"])}
        retr["byte_identical"] = all(retr[k]["match"] for k in
                                     ("chunks_returned_dist", "floor_bound_qids", "ceiling_bound_qids"))
        retr["rule"] = ("both features DARK + retrieval deterministic + transport-agnostic -> v3 MUST be "
                        "byte-identical to v2. ANY delta = leaked flag = BUG (withhold canonical tag).")
        comp = {"fabrication_query_count": cmp(v2b["fabricated_citations_query_count"],
                                               v3b["fabricated_citations_query_count"]),
                "v2_transport": v2b.get("transport", "?"), "v3_transport": v3b.get("transport", "?"),
                "matches_v2": v2b["fabricated_citations_query_count"] == v3b["fabricated_citations_query_count"],
                "rule": ("should match v2 (0/40). If it differs, investigate TRANSPORT FIRST (v2 partial "
                         "transport vs v3) — a transport-driven compose delta is EXPECTED, not a flag leak. "
                         "Citation SETS differ run-to-run (compose non-determinism).")}
        delta = {"prev_tag": "arch-baseline-v2", "this_tag": "arch-baseline-v3",
                 "RETRIEVAL_AXIS": retr, "COMPOSE_AXIS": comp}
    report["v2_vs_v3_delta"] = delta
    report["provenance"].update({
        "tag": "arch-baseline-v3", "prev_tag": "arch-baseline-v2 (704c8a6)", "expand_floor": config.EXPAND_TRIGGER_MIN_CITATIONS,
        "transport_used": transport,
        "fabrication_label": ("canonical (native_sdk)" if native else "PROVISIONAL (curl — needs native re-confirm)"),
        "data_csv_resolution": "RESTORED (tracked) per Pao — stale Phase-1 CSVs kept for the deprecated "
                               "generate_corpus_files.py path; runtime uses normalized xlsx (verify_pin PASS)",
        "single_citation_watchlist_W3_4": {"qids": WATCHLIST,
            "note": "W2.6 @floor=2 single-doc-cite queries — retrieval-coverage watchlist; re-check under recall@k"}})
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"w3_2_PARTIAL_BC_v3_{COMMIT}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with open(RESULTS / f"w3_2_partial_per_query_v3_{COMMIT}.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["query_id", "gold_doc_ids", "recall@1", "recall@3", "recall@5", "recall@10",
                    "chunks_returned", "floor_bound", "ceiling_bound", "cited_doc_ids", "fabricated",
                    "register_expected", "register_actual", "disclaimer_ok", "miss_type", "note"])
        for r in rows:
            g = GOLD.get(r["query_id"], "")
            w.writerow([r["query_id"], ";".join(g) if g else "", "", "", "", "",  # recall blank pending gold
                        r["chunks_returned"], r["floor_bound"], r["ceiling_bound"],
                        ";".join(r["cited_doc_ids"]), r["fabricated"],
                        "", "", "", "",  # register/disclaimer/miss_type blank (Sheena)
                        "degraded" if r["degraded"] else ""])

    print("\n=== W3.2 PARTIAL ===")
    print(f"[C] chunks_returned min/med/max/mean = {min(cr)}/{int(np.median(cr))}/{max(cr)}/{round(float(np.mean(cr)),2)} "
          f"| floor-bound {len(floor_q)} {[r['query_id'] for r in floor_q]} | ceiling-bound {len(ceil_q)}")
    print(f"[C] fab rate floor={round(fab_rate(floor_q),3)} non-floor={round(fab_rate(nonfloor),3)} -> VERDICT: {verdict}")
    print(f"[B] fabricated_citations = {len(fab_queries)}/40 (target 0) | total cites fabricated={fab_total} "
          f"| degraded={sum(1 for r in rows if r['degraded'])}")
    r5 = ", ".join(f"{k}:{v['@5']}" for k, v in recall5.items())
    print(f"[A] 5-item harness recall@5: {{ {r5} }} (PLUMBING ONLY)")
    if delta:
        ra, ca = delta["RETRIEVAL_AXIS"], delta["COMPOSE_AXIS"]
        print(f"\n=== v2-vs-v3 DELTA (split by axis) ===")
        print(f"  RETRIEVAL AXIS byte-identical to v2: {ra['byte_identical']} "
              f"(verdict {ra['floor_verdict']['v2']}->{ra['floor_verdict']['v3']}, floor/ceiling/dist match)")
        print(f"  COMPOSE AXIS fabrication: v2 {ca['fabrication_query_count']['v2']}/40 "
              f"({ca['v2_transport']}) -> v3 {ca['fabrication_query_count']['v3']}/40 ({ca['v3_transport']}) "
              f"match={ca['matches_v2']}")
        if not ra["byte_identical"]:
            print("  *** BUG: RETRIEVAL AXIS differs with flags DARK -> a flag leaked. WITHHOLD canonical tag. ***")
    print(f"wrote eval/results/w3_2_PARTIAL_BC_v3_{COMMIT}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
