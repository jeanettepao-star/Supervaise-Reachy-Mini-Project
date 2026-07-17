"""
OPS-2 Phase D — full-corpus orphan census (docs with chunks but NO topic in
topic_map.json), analysed against the NEW full-corpus centroids.

For each orphan doc: doc vector = unit-mean of its chunk vectors (from the
Phase-A corpus_dense), nearest production centroid + cosine. Reference
distribution = member docs' cosine to their OWN topic centroid; an orphan is
"adoptable" into an existing topic if its nearest cosine clears the member
p25, else it lands in the "needs-new-topic" pool, which is greedily clustered
by doc-doc cosine to suggest candidate new topics.

Writes eval/results/ops2_orphan_census.json (data). The human-readable
proposal (taxonomy_expansion_PROPOSAL.md) is authored from this output.
No taxonomy changes are applied.

Usage:  python scripts/run_ops2_orphan_census.py
"""
from __future__ import annotations

import datetime
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402
import embeddings  # noqa: E402  (DLL-order guard)
import numpy as np  # noqa: E402

IDX = ROOT / "data" / "index"
RES = ROOT / "eval" / "results"


def load_titles() -> dict[str, str]:
    titles = {}
    for tf in ("columns", "books", "speeches", "biography"):
        for p in glob.glob(str(ROOT / "corpus" / tf / "**" / "*.json"), recursive=True):
            d = json.loads(Path(p).read_text(encoding=config.FILE_ENCODING))
            titles[d["id"]] = d.get("title") or ""
    return titles


def main() -> int:
    cmeta = json.loads((IDX / "corpus_dense_meta.json").read_text(encoding="utf-8"))
    assert cmeta["model_id"] == config.EMBED_MODEL_ID, "run Phase A first"
    mat = np.load(IDX / "corpus_dense.npy").astype(np.float32)
    chunk_ids = cmeta["chunk_ids"]
    tmeta = json.loads((IDX / "topic_centroids_meta.json").read_text(encoding="utf-8"))
    assert "FULL corpus" in tmeta["centroid_source_fields"][0], "run Phase B first"
    cen = np.load(IDX / "topic_centroids.npy").astype(np.float32)
    topic_ids = tmeta["topic_ids"]
    # gmean-fallback centroids ARE the corpus mean — every generic doc scores
    # ~0.95 against them, so they act as universal attractors. Exclude them
    # from nearest-topic / adoption math (they are not semantic homes).
    fallback = set(tmeta.get("gmean_fallback_topics", []))
    valid = np.array([tid not in fallback for tid in topic_ids])

    tmap = json.loads((ROOT / "corpus/voice/topic_map.json").read_text(encoding="utf-8"))["topics"]
    tlist = tmap.values() if isinstance(tmap, dict) else tmap
    topic_of_doc: dict[str, list[str]] = {}
    for t in tlist:
        for d in t["doc_ids"]:
            topic_of_doc.setdefault(d, []).append(t["id"])

    rows_of_doc: dict[str, list[int]] = {}
    for i, cid in enumerate(chunk_ids):
        rows_of_doc.setdefault(cid.split("::")[0], []).append(i)
    all_docs = sorted(rows_of_doc)
    titles = load_titles()

    def doc_vec(d):
        v = mat[rows_of_doc[d]].mean(axis=0)
        n = np.linalg.norm(v)
        return v / n if n > 0 else v

    dvecs = {d: doc_vec(d) for d in all_docs}

    # production topic index (composite ids cover their sub-ids)
    prod_index_of = {}
    for i, tid in enumerate(topic_ids):
        for sub in tid.split("+"):
            prod_index_of[sub] = i

    # reference: member doc vs OWN topic centroid
    member_cos = []
    for d in all_docs:
        tids = topic_of_doc.get(d)
        if not tids:
            continue
        own = [float(dvecs[d] @ cen[prod_index_of[t]]) for t in tids if t in prod_index_of]
        if own:
            member_cos.append(max(own))
    member_cos = np.array(member_cos)
    p5 = float(np.percentile(member_cos, 5))

    # census — adoptable bar = member p5 (an orphan at least as close to an
    # existing centroid as the weakest 5% of curated members)
    orphans = [d for d in all_docs if d not in topic_of_doc]
    rows = []
    for d in orphans:
        sims = np.where(valid, cen @ dvecs[d], -1.0)
        j = int(np.argmax(sims))
        rows.append({"doc_id": d, "title": titles.get(d, ""),
                     "n_chunks": len(rows_of_doc[d]),
                     "nearest_topic": topic_ids[j], "nearest_cos": round(float(sims[j]), 4),
                     "adoptable": bool(sims[j] >= p5)})
    adoptable = [r for r in rows if r["adoptable"]]
    pool = [r for r in rows if not r["adoptable"]]

    # k-means over the needs-new-topic pool (greedy single-linkage chains into
    # one blob in bge-base's compressed cosine range — measured 2026-07-17).
    # k chosen by silhouette sweep; clusters labelled downstream by titles.
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    pool_ids = [r["doc_id"] for r in pool]
    V = np.stack([dvecs[d] for d in pool_ids])
    best = None
    for k in (6, 9, 12, 15, 18, 21):
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(V)
        sil = float(silhouette_score(V, km.labels_, metric="cosine"))
        if best is None or sil > best[1]:
            best = (k, sil, km)
    k_best, sil_best, km = best
    clusters = []
    for ci in range(k_best):
        idx = [i for i, l in enumerate(km.labels_) if l == ci]
        c = V[idx].mean(axis=0); c /= np.linalg.norm(c)
        # order members by centrality; nearest existing topic of the cluster centre
        idx.sort(key=lambda i: -float(V[i] @ c))
        near = np.where(valid, cen @ c, -1.0)
        j = int(np.argmax(near))
        clusters.append({"n": len(idx),
                         "nearest_existing_topic": topic_ids[j],
                         "nearest_existing_cos": round(float(near[j]), 4),
                         "docs": [pool_ids[i] for i in idx]})
    clusters.sort(key=lambda c: -c["n"])

    out = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "corpus": {"docs_with_chunks": len(all_docs), "chunks": len(chunk_ids)},
        "census": {"topic_members": len(all_docs) - len(orphans), "orphans": len(orphans),
                   "orphan_rate": round(len(orphans) / len(all_docs), 3)},
        "member_own_topic_cos": {"p5": round(p5, 4),
                                 "p25": round(float(np.percentile(member_cos, 25)), 4),
                                 "p50": round(float(np.percentile(member_cos, 50)), 4)},
        "adoptable_into_existing": {"n": len(adoptable), "bar": round(p5, 4),
                                    "by_topic": {}},
        "needs_new_topic": {"n": len(pool),
                            "kmeans": {"k": k_best, "silhouette_cosine": round(sil_best, 4)},
                            "clusters": [{**c, "docs": [{"doc_id": d, "title": titles.get(d, "")}
                                                        for d in c["docs"]]} for c in clusters]},
        "orphan_rows": rows,
    }
    by_topic: dict[str, list] = {}
    for r in adoptable:
        by_topic.setdefault(r["nearest_topic"], []).append(
            {"doc_id": r["doc_id"], "title": r["title"], "cos": r["nearest_cos"]})
    out["adoptable_into_existing"]["by_topic"] = dict(
        sorted(by_topic.items(), key=lambda kv: -len(kv[1])))

    (RES / "ops2_orphan_census.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[phase-d] docs={len(all_docs)} members={len(all_docs) - len(orphans)} "
          f"orphans={len(orphans)} ({out['census']['orphan_rate']:.1%})")
    print(f"[phase-d] adoptable(existing topics, cos>=p5={p5:.3f}): {len(adoptable)} "
          f"| needs-new-topic: {len(pool)} | kmeans k={k_best} sil={sil_best:.3f} "
          f"sizes {[c['n'] for c in clusters[:8]]}")
    print("wrote eval/results/ops2_orphan_census.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
