"""
OPS-2 Phase B — full-corpus centroid rebuild (34 topics, production order).

Same recipe as the production centroids (member_chunk_mean, the bake-off
regime ratified at arch-baseline-v4) but computed over the FULL corpus_dense
matrix instead of the 827-chunk pilot slice:

  centroid(topic) = unit-normalised mean of ALL chunks of the topic's member
  docs (topic_map.json doc_ids; composite "a+b" ids union their members).
  Zero-member topics fall back to the global mean vector (flagged).

Preserves the production topic order from topic_centroids_meta.json so
retrieval row alignment is untouched. Archives the current (pilot-scoped)
centroids to _archived_pilotmm_* before overwriting.

Usage:  python scripts/build_centroids_fullcorpus.py
"""
from __future__ import annotations

import datetime
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402
import embeddings  # noqa: E402  (unused directly; imported for the DLL-order guard)
import numpy as np  # noqa: E402

IDX = ROOT / "data" / "index"


def main() -> int:
    cmeta = json.loads((IDX / "corpus_dense_meta.json").read_text(encoding="utf-8"))
    assert cmeta["model_id"] == config.EMBED_MODEL_ID and cmeta["dim"] == config.EMBED_DIM, \
        f"corpus_dense is {cmeta['model_id']}/{cmeta['dim']} — run Phase A first"
    mat = np.load(IDX / "corpus_dense.npy").astype(np.float32)
    chunk_ids = cmeta["chunk_ids"]
    assert mat.shape == (len(chunk_ids), config.EMBED_DIM)

    pmeta = json.loads((IDX / "topic_centroids_meta.json").read_text(encoding="utf-8"))
    topic_ids = pmeta["topic_ids"]                       # 34, production order
    assert len(topic_ids) == 34

    tmap = json.loads((ROOT / "corpus/voice/topic_map.json").read_text(encoding="utf-8"))["topics"]
    members = {t["id"]: set(t["doc_ids"]) for t in (tmap.values() if isinstance(tmap, dict) else tmap)}

    rows_of_doc: dict[str, list[int]] = {}
    for i, cid in enumerate(chunk_ids):
        rows_of_doc.setdefault(cid.split("::")[0], []).append(i)

    gmean = mat.mean(axis=0); gmean /= np.linalg.norm(gmean)
    cen = np.zeros((len(topic_ids), config.EMBED_DIM), dtype=np.float32)
    topics_meta, thin, fallback = [], [], []
    for i, tid in enumerate(topic_ids):
        docs = set()
        for sub in tid.split("+"):
            docs |= members.get(sub, set())
        rows = [r for d in sorted(docs) for r in rows_of_doc.get(d, [])]
        if rows:
            v = mat[rows].mean(axis=0)
            cen[i] = v / np.linalg.norm(v)
        else:
            cen[i] = gmean
            fallback.append(tid)
        if len(rows) < 3:
            thin.append((tid, len(rows)))
        topics_meta.append({"topic_id": tid, "n_member_docs": len(docs),
                            "n_member_chunks": len(rows),
                            "gmean_fallback": not rows})

    # separation: mean pairwise cosine, old (pilot-scoped) vs new (full-corpus)
    old = np.load(IDX / "topic_centroids.npy").astype(np.float32)
    def sep(C):
        S = C @ C.T; iu = np.triu_indices(len(C), 1)
        return round(float(S[iu].mean()), 4)
    old_new_diag = [round(float(old[i] @ cen[i]), 4) for i in range(len(topic_ids))]

    # archive current production centroids, then overwrite
    shutil.copy2(IDX / "topic_centroids.npy", IDX / "_archived_pilotmm_topic_centroids.npy")
    shutil.copy2(IDX / "topic_centroids_meta.json", IDX / "_archived_pilotmm_topic_centroids_meta.json")
    np.save(IDX / "topic_centroids.npy", cen)
    (IDX / "topic_centroids_meta.json").write_text(json.dumps({
        "model_id": config.EMBED_MODEL_ID, "dim": config.EMBED_DIM,
        "backend": config.EMBED_BACKEND, "n_topics": len(topic_ids),
        "centroid_source_fields": [
            "member_chunk_mean over FULL corpus (OPS-2 Phase B; generalises the bake-off recipe "
            "from the 827-chunk pilot slice to all corpus chunks)"],
        "n_corpus_chunks": len(chunk_ids),
        "build_date": datetime.date.today().isoformat(),
        "corpus_dense_build_date": cmeta["build_date"],
        "gmean_fallback_topics": fallback,
        "thin_topics_lt3_chunks": thin,
        "separation_mean_pairwise_cos": {"old_pilot_scoped": sep(old), "new_full_corpus": sep(cen)},
        "old_vs_new_same_topic_cos": dict(zip(topic_ids, old_new_diag)),
        "topic_ids": topic_ids, "topics": topics_meta,
    }, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n", encoding=config.OUTPUT_ENCODING)

    print(f"[phase-b] wrote topic_centroids.npy {cen.shape} (full-corpus member-mean)")
    print(f"[phase-b] gmean fallback topics: {fallback or 'NONE'}")
    print(f"[phase-b] thin (<3 member chunks): {thin or 'NONE'}")
    print(f"[phase-b] separation old={sep(old)} new={sep(cen)} "
          f"| same-topic old~new cos: min={min(old_new_diag)} median={sorted(old_new_diag)[17]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
