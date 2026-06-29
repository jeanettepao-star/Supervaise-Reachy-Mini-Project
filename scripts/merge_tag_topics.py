"""
W1.7 Steps 4-5 — merge centroids, full-corpus orphan scan, tag the pilot subset.

Reads the (A2-fixed) 35-topic centroids, merges pairs > TOPIC_MERGE_COSINE into a
final topic set, scans the full corpus for orphaned content below
TOPIC_ASSIGN_MIN_COSINE, and tags the 95 pilot docs. Config-driven; no new
literals. Persists: merged centroids + meta, orphan review list, pilot tag map.

NOTE: the orphan FLOOR is only "locked" if the known orphans (GC006/CA330) fall
below it — this script reports their cosines; the caller gates on that.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import config

REPORTS = PROJECT_ROOT / "reports"
PRE_CENTROIDS = PROJECT_ROOT / "data" / "index" / "topic_centroids_premerge.npy"


def main() -> int:
    cen = np.load(config.CENTROIDS_PATH).astype(np.float32)
    meta = json.loads(Path(config.CENTROIDS_META_PATH).read_text(encoding="utf-8"))
    ids = meta["topic_ids"]
    n = len(ids)

    # ---- STEP 4a: merge pairs > TOPIC_MERGE_COSINE (union-find) ----
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    cc = cen @ cen.T
    merged_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            if cc[i, j] > config.TOPIC_MERGE_COSINE:
                merged_pairs.append((round(float(cc[i, j]), 4), ids[i], ids[j]))
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    final_ids, final_cen, final_members = [], [], []
    for root, idxs in sorted(groups.items(), key=lambda kv: min(kv[1])):
        members = [ids[k] for k in idxs]
        c = np.mean(cen[idxs], axis=0); c = c / np.linalg.norm(c)
        final_cen.append(c.astype(np.float32))
        final_ids.append("+".join(members) if len(members) > 1 else members[0])
        final_members.append(members)
    final_cen = np.stack(final_cen)
    print(f"[merge] {len(merged_pairs)} pair(s) > {config.TOPIC_MERGE_COSINE}: "
          f"{[(p[1], p[2]) for p in merged_pairs]} -> {n} -> {len(final_ids)} topics")

    # ---- load corpus_dense for the scans ----
    cmeta = json.loads(Path(config.CORPUS_DENSE_META_PATH).read_text(encoding="utf-8"))
    cmat = np.load(config.CORPUS_DENSE_PATH).astype(np.float32)
    row = {cid: i for i, cid in enumerate(cmeta["chunk_ids"])}
    by_doc = json.loads((PROJECT_ROOT / "corpus" / "index" / "chunk_index.json").read_text(encoding="utf-8"))["by_doc"]
    sims_all = cmat @ final_cen.T                    # [n_chunks, n_final]

    def doc_affinity(did):
        rows = [row[c] for c in by_doc.get(did, []) if c in row]
        if not rows:
            return None
        return sims_all[rows].max(axis=0)             # per-topic best-chunk

    floor = config.TOPIC_ASSIGN_MIN_COSINE

    # ---- STEP 4b: full-corpus orphan scan (chunk + doc level) ----
    chunk_nearest = sims_all.max(axis=1)
    n_chunk_orphan = int((chunk_nearest < floor).sum())
    doc_orphans = []
    for did in by_doc:
        aff = doc_affinity(did)
        if aff is None:
            continue
        nn = float(aff.max())
        if nn < floor:
            doc_orphans.append({"doc_id": did, "doc_nearest": round(nn, 4),
                                "nearest_topic": final_ids[int(aff.argmax())]})
    doc_orphans.sort(key=lambda d: d["doc_nearest"])

    # known-orphan validation
    known = {}
    for did in ("GC006", "CA330"):
        aff = doc_affinity(did)
        if aff is not None:
            known[did] = {"doc_nearest": round(float(aff.max()), 4),
                          "nearest_topic": final_ids[int(aff.argmax())],
                          "caught_by_floor": bool(aff.max() < floor)}
    print(f"[orphan] floor={floor} | chunk-level orphans={n_chunk_orphan}/{len(chunk_nearest)} "
          f"| doc-level orphans={len(doc_orphans)}/{len(by_doc)}")
    for k, v in known.items():
        print(f"[orphan] KNOWN {k}: doc_nearest={v['doc_nearest']} -> {v['nearest_topic']} "
              f"| caught={v['caught_by_floor']}")

    # ---- STEP 5: tag the 95 pilot docs ----
    pilot = [l.split(",")[0].strip() for l in
             (PROJECT_ROOT / "reports" / "pilot-eval subset" / "pilot_subset_frozen_v4.csv")
             .read_text(encoding="utf-8-sig").splitlines()
             if not l.startswith("#") and not l.startswith("doc_id")]
    tags = {}
    tag_dist = {}
    pilot_orphans = []
    for did in pilot:
        aff = doc_affinity(did)
        if aff is None:
            pilot_orphans.append({"doc_id": did, "reason": "no chunks"})
            continue
        order = np.argsort(-aff)[:config.MAX_TOPIC_TAGS]
        kept = [(final_ids[int(k)], round(float(aff[k]), 4)) for k in order if aff[k] >= floor]
        if not kept:
            pilot_orphans.append({"doc_id": did, "doc_nearest": round(float(aff.max()), 4),
                                  "nearest_topic": final_ids[int(aff.argmax())]})
            continue
        tags[did] = {"primary": kept[0][0], "primary_cos": kept[0][1],
                     "secondary": [k[0] for k in kept[1:]]}
        for t, _ in kept:
            tag_dist[t] = tag_dist.get(t, 0) + 1

    # ---- persist ----
    if not PRE_CENTROIDS.exists():
        np.save(PRE_CENTROIDS, cen)   # keep the 35-topic pre-merge for provenance
    np.save(config.CENTROIDS_PATH, final_cen)
    meta.update({"n_topics": len(final_ids), "topic_ids": final_ids,
                 "merged_from": {fid: m for fid, m in zip(final_ids, final_members) if len(m) > 1},
                 "merged_pairs": merged_pairs, "premerge_n_topics": n,
                 "merge_cosine": config.TOPIC_MERGE_COSINE,
                 "assign_floor": floor, "assign_floor_locked": all(v["caught_by_floor"] for v in known.values()),
                 "known_orphan_validation": known, "build_date": datetime.date.today().isoformat()})
    Path(config.CENTROIDS_META_PATH).write_text(
        json.dumps(meta, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n", encoding=config.OUTPUT_ENCODING)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "w1_7_orphan_review.json").write_text(json.dumps({
        "floor": floor, "granularity": "doc-level (max over a doc's chunks); chunk-level count also reported",
        "n_chunk_orphans": n_chunk_orphan, "n_doc_orphans": len(doc_orphans),
        "known_orphan_validation": known, "doc_orphans": doc_orphans[:200],
    }, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n", encoding=config.OUTPUT_ENCODING)
    (REPORTS / "w1_7_pilot_topic_tags.json").write_text(json.dumps({
        "n_pilot": len(pilot), "n_tagged": len(tags), "n_orphaned": len(pilot_orphans),
        "tag_distribution": dict(sorted(tag_dist.items(), key=lambda kv: -kv[1])),
        "orphaned_pilot_docs": pilot_orphans, "tags": tags,
    }, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n", encoding=config.OUTPUT_ENCODING)

    print(f"[tag] pilot {len(tags)}/{len(pilot)} tagged, {len(pilot_orphans)} orphaned")
    print("[tag] distribution:", dict(sorted(tag_dist.items(), key=lambda kv: -kv[1])))
    if pilot_orphans:
        print("[tag] ORPHANED pilot docs:", pilot_orphans)
    print(f"[persist] merged centroids ({len(final_ids)}) + meta; orphan_review + pilot_topic_tags in reports/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
