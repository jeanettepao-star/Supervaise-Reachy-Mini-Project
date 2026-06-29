"""
W1.7 Step 3 (preliminary centroids) + Step 1 (threshold recalibration).

Topic set = the 35-topic hand-curated taxonomy in build_topic_map.py (per the
W1.7 decision), with FRESH bge centroids (not the stale 35-topic centroids).

For each topic, centroid = unit-normalised mean of the embeddings of the
config.CENTROID_SOURCE_FIELDS:
  - label            : topic display_name
  - description      : topic definition
  - signature_phrases: the topic's curated matcher keywords + entities (the
                       phrases that define the topic; parsed as a list)
  - exemplar_chunks  : up to N_EXEMPLAR_CHUNKS chunks from the top member docs
                       (members = docs scored > 0 by the taxonomy matchers over
                       the FULL corpus); their vectors are pulled from
                       corpus_dense.npy (no re-embedding).

Persists CENTROIDS_PATH (n_topics x EMBED_DIM) + meta. Then samples the bge
cosine distributions (centroid-vs-centroid for merge; chunk-vs-nearest-centroid
for assignment/orphan) and PRINTS recommended TOPIC_MERGE_COSINE /
TOPIC_ASSIGN_MIN_COSINE. Does NOT run the merge (Step 4) — thresholds are
reviewed first.

Usage:  python scripts/build_centroids.py
"""
from __future__ import annotations

import datetime
import glob
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import config
sys.path.insert(0, str(PROJECT_ROOT / "app"))
import embeddings  # noqa: E402
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import build_topic_map as btm  # noqa: E402

CORPUS_ROOT = PROJECT_ROOT / "corpus"
CHUNK_INDEX = json.loads((CORPUS_ROOT / "index" / "chunk_index.json").read_text(encoding="utf-8"))["by_doc"]


def load_docs():
    docs = {}
    for tf in ("columns", "books", "speeches", "biography"):
        for p in glob.glob(str(CORPUS_ROOT / tf / "**" / "*.json"), recursive=True):
            d = json.loads(Path(p).read_text(encoding=config.FILE_ENCODING))
            docs[d["id"]] = d
    return docs


def pct(a, ps):
    return {f"p{p}": round(float(np.percentile(a, p)), 4) for p in ps}


def main() -> int:
    fields = config.CENTROID_SOURCE_FIELDS
    print(f"[centroids] CENTROID_SOURCE_FIELDS = {fields}")
    docs = load_docs()
    print(f"[centroids] full corpus docs: {len(docs)}")

    # corpus_dense for exemplar-chunk vectors
    cmeta = json.loads(Path(config.CORPUS_DENSE_META_PATH).read_text(encoding="utf-8"))
    cmat = np.load(config.CORPUS_DENSE_PATH).astype(np.float32)
    row_of = {cid: i for i, cid in enumerate(cmeta["chunk_ids"])}

    # score every doc against every topic (full-corpus member assignment)
    hay = {did: btm._doc_haystack(d) for did, d in docs.items()}
    members = {}   # topic_id -> [doc_id] ranked by score desc
    for t in btm.TAXONOMY:
        scored = [(btm.score_topic(t, hay[did]), did) for did in docs]
        scored = sorted([(s, d) for s, d in scored if s > 0], key=lambda sd: (-sd[0], sd[1]))
        members[t["id"]] = [d for _, d in scored]

    # collect field texts to embed (label/description/signature_phrases)
    texts, owner = [], []   # parallel: owner = (topic_id, field)
    for t in btm.TAXONOMY:
        if "label" in fields:
            texts.append(t["display_name"]); owner.append((t["id"], "label"))
        if "description" in fields:
            texts.append(t["definition"]); owner.append((t["id"], "description"))
        if "signature_phrases" in fields:
            for ph in list(t["matchers"]["keywords"]) + list(t["matchers"].get("entities", [])):
                texts.append(ph); owner.append((t["id"], "sig"))
    print(f"[centroids] embedding {len(texts)} taxonomy field texts on {config.EMBED_DEVICE} ...")
    fvecs = embeddings.embed_documents(texts)
    by_topic_field = {}
    for (tid, f), v in zip(owner, fvecs):
        by_topic_field.setdefault(tid, []).append(v)

    # assemble centroids
    topic_ids = [t["id"] for t in btm.TAXONOMY]
    centroids = np.zeros((len(topic_ids), config.EMBED_DIM), dtype=np.float32)
    cmeta_rows = []
    for i, t in enumerate(btm.TAXONOMY):
        vecs = list(by_topic_field.get(t["id"], []))
        n_exemplar = 0
        if "exemplar_chunks" in fields:
            seen = []
            for did in members[t["id"]]:
                for cid in CHUNK_INDEX.get(did, [])[:1]:   # one chunk per member doc
                    if cid in row_of:
                        seen.append(row_of[cid])
                if len(seen) >= config.N_EXEMPLAR_CHUNKS:
                    break
            seen = seen[:config.N_EXEMPLAR_CHUNKS]
            n_exemplar = len(seen)
            vecs.extend(cmat[r] for r in seen)
        if not vecs:
            continue
        c = np.mean(np.stack(vecs), axis=0)
        n = np.linalg.norm(c)
        centroids[i] = c / n if n > 0 else c
        cmeta_rows.append({"topic_id": t["id"], "display_name": t["display_name"],
                           "tier": t["tier"], "theme_anchor": t["theme_anchor"],
                           "n_members": len(members[t["id"]]), "n_exemplar_chunks": n_exemplar,
                           "n_field_vecs": len(vecs)})

    config.CENTROIDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.save(config.CENTROIDS_PATH, centroids)
    Path(config.CENTROIDS_META_PATH).write_text(json.dumps({
        "model_id": config.EMBED_MODEL_ID, "dim": config.EMBED_DIM,
        "backend": config.EMBED_BACKEND, "n_topics": len(topic_ids),
        "centroid_source_fields": fields, "n_exemplar_chunks": config.N_EXEMPLAR_CHUNKS,
        "build_date": datetime.date.today().isoformat(),
        "topic_ids": topic_ids, "topics": cmeta_rows,
    }, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n", encoding=config.OUTPUT_ENCODING)
    print(f"[centroids] wrote {config.CENTROIDS_PATH.name} {centroids.shape}")

    # ---- STEP 1: distributions ----
    # centroid-vs-centroid (off-diagonal upper triangle)
    cc = centroids @ centroids.T
    iu = np.triu_indices(len(topic_ids), k=1)
    pair_cos = cc[iu]
    # chunk-vs-nearest-centroid (full corpus)
    sims = cmat @ centroids.T            # [n_chunks, n_topics]
    nearest = sims.max(axis=1)           # [n_chunks]
    # doc-vs-nearest (max over a doc's chunks)
    doc_near = []
    for did, cids in CHUNK_INDEX.items():
        rows = [row_of[c] for c in cids if c in row_of]
        if rows:
            doc_near.append(float(sims[rows].max()))
    doc_near = np.array(doc_near)

    print("\n=== STEP 1 — bge cosine distributions ===")
    print("centroid-vs-centroid pairs (n=%d): max=%.4f" % (len(pair_cos), pair_cos.max()),
          pct(pair_cos, [50, 90, 95, 99]))
    top_pairs = sorted(zip(pair_cos, zip(*iu)), reverse=True)[:8]
    print("  top pairs:")
    for c, (a, b) in top_pairs:
        print("    %.4f  %s  ~  %s" % (c, topic_ids[a], topic_ids[b]))
    print("chunk-vs-nearest-centroid (n=%d):" % len(nearest), pct(nearest, [1, 5, 10, 25, 50, 75]))
    print("doc-vs-nearest-centroid (n=%d):" % len(doc_near), pct(doc_near, [1, 5, 10, 25, 50, 75]))

    # ---- recommended thresholds ----
    merge_rec = round(float(np.percentile(pair_cos, 99)), 3)
    assign_rec = round(float(np.percentile(nearest, 5)), 3)
    print("\n=== RECOMMENDED (review before merge) ===")
    print("  TOPIC_MERGE_COSINE  ~ %.3f  (p99 of centroid-pair cosines; above = genuine dup)" % merge_rec)
    print("  TOPIC_ASSIGN_MIN_COSINE ~ %.3f  (p5 of chunk-nearest; below = orphaned)" % assign_rec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
