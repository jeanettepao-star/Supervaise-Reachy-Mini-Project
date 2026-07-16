"""
EMBEDDER TRANSITION VERIFY — bge-base promotion (arch-baseline-v4). $0 retrieval-only.

6. Live-pipeline smoke: 40 anchor queries through retrieval.run(); assert the ranked
   selection matches an independent replay from the promoted arrays (exact chunk ids).
7. $0 regrade vs v4 gold: expect recall@1/5/sent/10 = 0.618/0.882/0.941/0.971
   (the NEW canonical C-baseline; -2.9pts @sent vs bge-large is the RATIFIED trade).
9. OOS scope-signal distribution in the new space (signal side only).

Writes eval/results/arch_baseline_v4_retrieval.json.
"""
from __future__ import annotations
import csv, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config, retrieval, service, embeddings  # noqa: E402

RES = ROOT / "eval" / "results"
SENT = {"OOS", "META", "GAP"}
EXPECT = {"1": 0.618, "5": 0.882, "chunks_sent": 0.941, "10": 0.971}


def main():
    assert config.EMBED_MODEL_ID == "BAAI/bge-base-en-v1.5" and config.EMBED_DIM == 768
    G = list(csv.DictReader(open(RES / "gold_reference_set.csv", encoding="utf-8-sig")))
    assert sum(1 for r in G if r["scope_gold"] == "in") == 34
    allow = service._allowlist("v4")
    pm = json.loads((ROOT / "data/index/pilot_dense_meta.json").read_text(encoding="utf-8"))
    chunk_ids, doc_ids = pm["chunk_ids"], pm["doc_ids"]
    row_of = {c: i for i, c in enumerate(chunk_ids)}
    mat = np.load(ROOT / "data/index/pilot_dense.npy").astype(np.float32)
    cen = np.load(ROOT / "data/index/topic_centroids.npy").astype(np.float32)
    assert mat.shape == (827, 768) and cen.shape == (34, 768)
    ksent = {r.get("qid") or r["query_id"]: r["chunks_sent"] for r in json.loads(
        (RES / "w3_2_PARTIAL_BC_v3_c1637cd.json").read_text(encoding="utf-8"))["per_query"]}
    import sparse

    def softmax(x, t):
        z = x / max(t, 1e-6); z = z - z.max(); e = np.exp(z); return e / e.sum()

    # ---- 6. live smoke vs independent replay (same query vector both sides) ----
    mism, live_sel = [], {}
    scope_sig = []
    for r in G:
        qid = r["qid"]
        live = retrieval.run(r["query"], allow)
        lsel = [c for c, _, _ in live["retrieval"]["selected"]]
        live_sel[qid] = lsel
        scope_sig.append((qid, r["scope_gold"], live["route"]["top_cosine"], live["route"]["in_scope"]))
        # replay: same math from the promoted arrays, using the LIVE query vector
        qv = embeddings.embed_query(r["query"])
        dsims = mat @ qv
        drank = {chunk_ids[i]: k for k, i in enumerate(sorted(range(827), key=lambda i: -dsims[i]), 1)}
        sr = sparse.sparse_score(r["query"], allowlist=allow, k=len(chunk_ids))
        srank = {cid: k for k, (cid, s) in enumerate([(c, s) for c, s in sr if s > 0], 1)}
        K = config.RRF_K
        rrf = {c: 1.0 / (K + drank[c]) + (1.0 / (K + srank[c]) if c in srank else 0.0) for c in drank}
        mx, mn = max(rrf.values()), min(rrf.values())
        psim = {c: (rrf[c] - mn) / (mx - mn) if mx > mn else 1.0 for c in rrf}
        rcos = cen @ qv
        rel = softmax(rcos, config.TOPIC_SOFTMAX_TEMPERATURE)
        if rcos.max() < config.OUT_OF_SCOPE_THRESHOLD:
            rel = np.full_like(rel, 1.0 / len(rel))
        chunk_cen = mat @ cen.T
        score = {c: psim[c] + config.LAMBDA * float(chunk_cen[row_of[c]] @ rel) for c in rrf}
        ranked = sorted(rrf, key=lambda c: -score[c])
        # nucleus (same params)
        sc = np.array([score[c] for c in ranked]); nm = softmax(sc, config.RETRIEVAL_SOFTMAX_TEMP)
        kept, cum = [], 0.0
        for c, m in zip(ranked, nm):
            kept.append(c); cum += float(m)
            if cum >= config.RETRIEVAL_TOP_P:
                break
        if len(kept) < config.RETRIEVAL_MIN_K:
            kept = ranked[:config.RETRIEVAL_MIN_K]
        if kept != lsel:
            mism.append(qid)
    print(f"[6] live-vs-replay: {40 - len(mism)}/40 exact match" + (f" — MISMATCH {mism}" if mism else ""))
    if mism:
        print("STOP: live path diverges from replay.", file=sys.stderr); return 2

    # ---- 7. grade the LIVE selections (C-baseline) ----
    insc = [r for r in G if r["scope_gold"] == "in"]
    def gold_of(r): return [x.strip() for x in r["gold_source_docs"].split(";") if x.strip() and x.strip() not in SENT]
    per, rec_hits = [], {k: 0 for k in ("1", "3", "5", "10", "sent")}
    for r in insc:
        qid = r["qid"]; gd = gold_of(r)
        # full ranked docs: recompute ranked from live run again (selected is the nucleus;
        # for @10 grading use the replay ranked list — identical per check above)
        live = retrieval.run(r["query"], allow)
        # dedup docs from the FULL ranked ordering (use score-ordered selected + rest via replay basis):
        qv = embeddings.embed_query(r["query"])
        dsims = mat @ qv
        drank = {chunk_ids[i]: k for k, i in enumerate(sorted(range(827), key=lambda i: -dsims[i]), 1)}
        sr = sparse.sparse_score(r["query"], allowlist=allow, k=len(chunk_ids))
        srank = {cid: k for k, (cid, s) in enumerate([(c, s) for c, s in sr if s > 0], 1)}
        K = config.RRF_K
        rrf = {c: 1.0 / (K + drank[c]) + (1.0 / (K + srank[c]) if c in srank else 0.0) for c in drank}
        mx, mn = max(rrf.values()), min(rrf.values())
        psim = {c: (rrf[c] - mn) / (mx - mn) if mx > mn else 1.0 for c in rrf}
        rcos = cen @ qv; rel = softmax(rcos, config.TOPIC_SOFTMAX_TEMPERATURE)
        chunk_cen = mat @ cen.T
        score = {c: psim[c] + config.LAMBDA * float(chunk_cen[row_of[c]] @ rel) for c in rrf}
        ranked = sorted(rrf, key=lambda c: -score[c])
        seen, rdocs = set(), []
        for c in ranked:
            d = doc_ids[row_of[c]]
            if d not in seen:
                seen.add(d); rdocs.append(d)
            if len(rdocs) >= 15:
                break
        row = {"qid": qid, "retrieved_docs": rdocs}
        for k in (1, 3, 5, 10):
            row[f"hit@{k}"] = any(d in gd for d in rdocs[:k]); rec_hits[str(k)] += row[f"hit@{k}"]
        kq = ksent[qid]
        row["hit@sent"] = any(doc_ids[row_of[c]] in gd for c in ranked[:kq]); rec_hits["sent"] += row["hit@sent"]
        per.append(row)
    n = len(insc)
    rec = {"1": round(rec_hits["1"] / n, 3), "3": round(rec_hits["3"] / n, 3),
           "5": round(rec_hits["5"] / n, 3), "10": round(rec_hits["10"] / n, 3),
           "chunks_sent": round(rec_hits["sent"] / n, 3)}
    ok = all(abs(rec[k] - EXPECT[k]) < 1e-9 for k in EXPECT)
    print(f"[7] C-baseline recall @1/@5/@sent/@10 = {rec['1']}/{rec['5']}/{rec['chunks_sent']}/{rec['10']} "
          f"| matches bake-off C: {ok}")
    if not ok:
        print(f"STOP: numbers differ from ratified bake-off C {EXPECT}", file=sys.stderr); return 3

    # ---- 9. OOS scope-signal distribution (new space) ----
    from collections import defaultdict
    by = defaultdict(list)
    for qid, scope, cos, ins in scope_sig:
        b = "in" if scope == "in" else ("out" if scope == "out" else ("meta" if scope == "meta" else "gap"))
        by[b].append((qid, cos, ins))
    print("[9] scope signal (query->nearest-centroid cos, bge-base space):")
    for b in ("in", "out", "meta", "gap"):
        cs = sorted(c for _, c, _ in by[b])
        print(f"    {b:4} n={len(by[b])} min={cs[0]:.4f} max={cs[-1]:.4f} | all in_scope flags True: "
              f"{all(i for _, _, i in by[b])}")
    out_vals = {q: round(c, 4) for q, c, _ in by["out"]}
    print(f"    OUT probes: {out_vals} (gate at {config.OUT_OF_SCOPE_THRESHOLD} stays loose/inert by design; "
          "composer-decline owns OOS — re-verify rides with DEBT-2)")

    (RES / "arch_baseline_v4_retrieval.json").write_text(json.dumps({
        "anchor": "arch-baseline-v4 (embedder = bge-base-en-v1.5, ratified by Dok)",
        "recall_C_baseline": rec, "n": n,
        "note": "-2.9pts @chunks-sent vs bge-large is the RATIFIED trade; recovery belongs to W3.3/W3.4",
        "live_vs_replay": "40/40 exact", "scope_signal": {b: [(q, round(c, 4)) for q, c, _ in by[b]] for b in by},
        "provenance": {"ratified_by": "Dok", "bakeoff_evidence": "bakeoff_FINAL_for_dok.md @ 2ca0255",
                       "rollback": "restore data/index/_archived_bgelarge_* over production names + revert config EMBED_MODEL_ID/EMBED_DIM",
                       "commit_before": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                                       capture_output=True, text=True).stdout.strip(),
                       "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")},
        "per_query": per}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote eval/results/arch_baseline_v4_retrieval.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
