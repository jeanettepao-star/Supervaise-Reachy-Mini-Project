"""
$0 MiniLM BAKE-OFF PREP — decision evidence for Dok's embedder + topology call.

Builds PARALLEL MiniLM artifacts (bakeoff_* names; the production bge index and
config are NEVER touched), replays the retrieval-only path in MiniLM space, and
grades against v4 gold with the SAME method as w3_2_REGRADE_v3_v4gold.json
(scope-aware, N=34, hit@k over deduped parent-doc ranks). Plus latency (GPU+CPU,
cold/warm) and footprint. No API, no composition, no full-corpus re-embed.

Usage:
  python scripts/run_bakeoff_minilm.py            # full bake-off (also spawns benches)
  python scripts/run_bakeoff_minilm.py --bench sentence-transformers/all-MiniLM-L6-v2 cpu
"""
from __future__ import annotations
import ctypes, json, statistics, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402

RES = ROOT / "eval" / "results"
IDX = ROOT / "data" / "index"
MINILM = "sentence-transformers/all-MiniLM-L6-v2"
BGE = "BAAI/bge-large-en-v1.5"
SENT = {"OOS", "META", "GAP"}
CANON = {"1": 0.735, "3": 0.941, "5": 0.971, "10": 0.971}   # bge canonical (regrade artifact)
CLUSTER = ["A2", "A4", "B10", "C17", "C18", "D23", "E28", "E29"]


def rss_mb() -> float:
    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),
                                             ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / (1024 * 1024)


def load_queries():
    import csv
    G = list(csv.DictReader(open(RES / "gold_reference_set.csv", encoding="utf-8-sig")))
    return G


def bench(model_id: str, device: str):
    """Subprocess mode: query-embed latency (cold-first vs warm) + params + RSS delta."""
    G = load_queries()
    rss0 = rss_mb()
    from sentence_transformers import SentenceTransformer
    t0 = time.perf_counter()
    m = SentenceTransformer(model_id, device=device)
    load_s = round(time.perf_counter() - t0, 2)
    rss1 = rss_mb()
    prefix = config.EMBED_QUERY_PREFIX if model_id == BGE else ""
    def enc(q):
        t = time.perf_counter()
        m.encode([prefix + q], normalize_embeddings=True, show_progress_bar=False)
        return (time.perf_counter() - t) * 1000
    same = [enc("What is the rule of law?") for _ in range(20)]      # cold-first, warm-rest
    anchors = [enc(r["query"]) for r in G]
    params = sum(p.numel() for p in m._first_module().auto_model.parameters())
    def pct(v, p): return round(sorted(v)[min(int(len(v) * p), len(v) - 1)], 1)
    out = {"model": model_id, "device": device, "model_load_s": load_s,
           "rss_delta_mb": round(rss1 - rss0, 1), "params_millions": round(params / 1e6, 1),
           "same_query_20x": {"cold_first_ms": round(same[0], 1),
                              "warm_rest_ms": {"p50": pct(same[1:], .5), "p95": pct(same[1:], .95),
                                               "mean": round(statistics.mean(same[1:]), 1)}},
           "anchor_40": {"p50": pct(anchors, .5), "p95": pct(anchors, .95),
                         "mean": round(statistics.mean(anchors), 1)}}
    print("BENCH_JSON:" + json.dumps(out))


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--bench":
        return bench(sys.argv[2], sys.argv[3])

    import csv
    from sentence_transformers import SentenceTransformer
    import sparse  # lexical arm, embedder-independent

    pm = json.loads((IDX / "pilot_dense_meta.json").read_text(encoding="utf-8"))
    chunk_ids, doc_ids = pm["chunk_ids"], pm["doc_ids"]
    assert len(chunk_ids) == 827
    txt = {}
    for ln in (ROOT / "corpus/index/chunks.jsonl").read_text(encoding="utf-8").splitlines():
        if ln.strip():
            c = json.loads(ln); txt[c["chunk_id"]] = c["text"]
    texts = [txt[c] for c in chunk_ids]

    # ---- 1-2: parallel MiniLM embeddings (chunks + queries), never touching bge ----
    print("[bakeoff] embedding 827 pilot chunks + 40 queries with MiniLM (local cache, GPU)...")
    mm = SentenceTransformer(MINILM, device=config.EMBED_DEVICE)
    mat = mm.encode(texts, normalize_embeddings=True, batch_size=64,
                    show_progress_bar=False).astype(np.float32)          # no doc prefix (symmetric model)
    G = load_queries()
    qmat = mm.encode([r["query"] for r in G], normalize_embeddings=True,
                     show_progress_bar=False).astype(np.float32)          # no query prefix for MiniLM
    np.save(IDX / "bakeoff_minilm_dense.npy", mat)
    chunk_sha = hashlib.sha256("\n".join(sorted(chunk_ids)).encode()).hexdigest()
    (IDX / "bakeoff_minilm_meta.json").write_text(json.dumps({
        "model_id": MINILM, "dim": int(mat.shape[1]), "n_chunks": len(chunk_ids),
        "normalize": True, "prefixes": "none (symmetric model; bge uses query prefix — noted)",
        "chunk_set_sha256": chunk_sha, "parallel_artifact": "NEVER wired into production",
        "built": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 3: MiniLM centroids = mean of member PILOT chunks (topic_map doc_ids) ----
    cmeta = json.loads((IDX / "topic_centroids_meta.json").read_text(encoding="utf-8"))
    topic_ids = cmeta["topic_ids"]                                     # 34, production order
    tmap = json.loads((ROOT / "corpus/voice/topic_map.json").read_text(encoding="utf-8"))["topics"]
    members = {tid: set(t["doc_ids"]) for tid, t in
               ((t["id"], t) for t in (tmap.values() if isinstance(tmap, dict) else tmap))}
    row_of = {c: i for i, c in enumerate(chunk_ids)}
    cen = np.zeros((len(topic_ids), mat.shape[1]), dtype=np.float32)
    thin = []
    gmean = mat.mean(axis=0); gmean /= np.linalg.norm(gmean)
    for i, tid in enumerate(topic_ids):
        docs = set()
        for sub in tid.split("+"):
            docs |= members.get(sub, set())
        rows = [row_of[c] for c in chunk_ids if doc_ids[row_of[c]] in docs]
        if len(rows) < 3:
            thin.append((tid, len(rows)))
        if rows:
            v = mat[rows].mean(axis=0); cen[i] = v / np.linalg.norm(v)
        else:
            cen[i] = gmean                                            # flagged neutral fallback
    np.save(IDX / "bakeoff_minilm_centroids.npy", cen)

    # bge centroids (production) + bge member-mean (like-for-like separation)
    bge_cen = np.load(IDX / "topic_centroids.npy").astype(np.float32)
    bge_mat = np.load(IDX / "pilot_dense.npy").astype(np.float32)
    bge_mm = np.zeros_like(bge_cen)
    for i, tid in enumerate(topic_ids):
        docs = set()
        for sub in tid.split("+"):
            docs |= members.get(sub, set())
        rows = [row_of[c] for c in chunk_ids if doc_ids[row_of[c]] in docs]
        v = bge_mat[rows].mean(axis=0) if rows else bge_mat.mean(axis=0)
        bge_mm[i] = v / np.linalg.norm(v)
    def sep(C):
        S = C @ C.T; iu = np.triu_indices(len(C), 1)
        return round(float(S[iu].mean()), 4)
    separation = {"bge_production_fieldbuilt": sep(bge_cen), "bge_member_mean_likeforlike": sep(bge_mm),
                  "minilm_member_mean": sep(cen),
                  "note": "higher mean pairwise cosine = blurrier dimensions. Production bge centroids "
                          "were field+exemplar-built (topic_centroids_meta centroid_source_fields), so "
                          "the member-mean rows are the like-for-like comparison.",
                  "thin_topics_lt3_pilot_members": thin}

    # ---- 4-5: retrieval-only replay in MiniLM space, graded like the regrade ----
    allow = set(l.split(",")[0].strip() for l in
                (ROOT / "reports/pilot-eval subset/pilot_subset_frozen_v4.csv")
                .read_text(encoding="utf-8-sig").splitlines()
                if not l.startswith("#") and not l.startswith("doc_id"))
    K, LAM = config.RRF_K, config.LAMBDA
    chunk_cen = mat @ cen.T
    canon_pq = {r["qid"]: r for r in json.loads(
        (RES / "w3_2_REGRADE_v3_v4gold.json").read_text(encoding="utf-8"))["per_query"]}

    def softmax(x, t):
        z = x / max(t, 1e-6); z = z - z.max(); e = np.exp(z); return e / e.sum()

    rows_out, diffs = [], []
    for gi, r in enumerate(G):
        qid, scope = r["qid"], r["scope_gold"]
        gd = [d.strip() for d in (r["gold_source_docs"] or "").split(";") if d.strip() and d.strip() not in SENT]
        qv = qmat[gi]
        didx = [i for i, d in enumerate(doc_ids) if d in allow]
        dsims = mat @ qv
        drank = {chunk_ids[i]: k for k, i in enumerate(sorted(didx, key=lambda i: -dsims[i]), 1)}
        sranked = sparse.sparse_score(r["query"], allowlist=allow, k=len(chunk_ids))
        srank = {cid: k for k, (cid, s) in enumerate([(c, s) for c, s in sranked if s > 0], 1)}
        rrf = {c: 1.0 / (K + drank[c]) + (1.0 / (K + srank[c]) if c in srank else 0.0) for c in drank}
        mx, mn = max(rrf.values()), min(rrf.values())
        psim = {c: (rrf[c] - mn) / (mx - mn) if mx > mn else 1.0 for c in rrf}
        rcos = cen @ qv
        rel = softmax(rcos, config.TOPIC_SOFTMAX_TEMPERATURE)
        if rcos.max() < config.OUT_OF_SCOPE_THRESHOLD:
            rel = np.full_like(rel, 1.0 / len(rel))
        aff = {c: float(chunk_cen[row_of[c]] @ rel) for c in rrf}
        score = {c: psim[c] + LAM * aff[c] for c in rrf}
        ranked = sorted(rrf, key=lambda c: -score[c])
        # dedup parent docs in rank order (SAME grading basis as the canonical regrade)
        seen, rdocs = set(), []
        for c in ranked:
            d = doc_ids[row_of[c]]
            if d not in seen:
                seen.add(d); rdocs.append(d)
            if len(rdocs) >= 15:
                break
        row = {"qid": qid, "scope_gold": scope, "gold": gd, "retrieved_docs": rdocs}
        if scope == "in":
            for k in (1, 3, 5, 10):
                row[f"hit@{k}"] = any(d in gd for d in rdocs[:k])
            row["best_gold_rank"] = next((i + 1 for i, d in enumerate(rdocs) if d in gd), None)
            cp = canon_pq[qid]
            if bool(cp.get("hit@5")) != row["hit@5"] or bool(cp.get("hit@1")) != row["hit@1"]:
                diffs.append({"qid": qid, "bge_hit@1": cp.get("hit@1"), "minilm_hit@1": row["hit@1"],
                              "bge_hit@5": cp.get("hit@5"), "minilm_hit@5": row["hit@5"],
                              "bge_best_rank": cp.get("best_gold_rank"), "minilm_best_rank": row["best_gold_rank"]})
        rows_out.append(row)

    insc = [x for x in rows_out if x["scope_gold"] == "in"]
    mini_recall = {str(k): round(sum(1 for x in insc if x[f"hit@{k}"]) / len(insc), 3) for k in (1, 3, 5, 10)}
    b9 = next(x for x in rows_out if x["qid"] == "B9")
    cluster_cmp = [{"qid": q, "bge_best_rank": canon_pq[q].get("best_gold_rank"),
                    "minilm_best_rank": next(x for x in rows_out if x["qid"] == q).get("best_gold_rank"),
                    "minilm_hit@1": next(x for x in rows_out if x["qid"] == q).get("hit@1")}
                   for q in CLUSTER]

    print(f"[bakeoff] MiniLM recall@1/3/5/10 = {mini_recall} (N={len(insc)}) vs bge {CANON}")
    print(f"[bakeoff] B9 (bge sole coverage miss): minilm best_gold_rank={b9.get('best_gold_rank')} hit@5={b9.get('hit@5')}")
    print(f"[bakeoff] hit@1-or-@5 diffs: {len(diffs)}")

    # ---- 7: latency benches (4 subprocess combos, labeled) ----
    benches = {}
    for mid, dev in [(MINILM, "cuda"), (MINILM, "cpu"), (BGE, "cuda"), (BGE, "cpu")]:
        print(f"[bench] {mid.split('/')[-1]} on {dev} ...")
        p = subprocess.run([sys.executable, __file__, "--bench", mid, dev],
                           capture_output=True, text=True, timeout=1200)
        line = next((l for l in p.stdout.splitlines() if l.startswith("BENCH_JSON:")), None)
        benches[f"{mid.split('/')[-1]}|{dev}"] = json.loads(line[11:]) if line else {"error": p.stderr[-300:]}

    # ---- 8: footprint ----
    def cache_size_mb(name):
        base = Path.home() / ".cache/huggingface/hub" / name
        return round(sum(f.stat().st_size for f in base.rglob("*") if f.is_file()) / 1e6, 1) if base.exists() else None
    vec = lambda n, d: round(n * d * 4 / 1e6, 2)
    footprint = {
        "minilm": {"params_M": benches.get("all-MiniLM-L6-v2|cpu", {}).get("params_millions"),
                   "disk_mb": cache_size_mb("models--sentence-transformers--all-MiniLM-L6-v2"),
                   "rss_delta_mb_cpu": benches.get("all-MiniLM-L6-v2|cpu", {}).get("rss_delta_mb"),
                   "vectors_827_mb": vec(827, mat.shape[1]), "vectors_8887_mb": vec(8887, mat.shape[1])},
        "bge_large": {"params_M": benches.get("bge-large-en-v1.5|cpu", {}).get("params_millions"),
                      "disk_mb": cache_size_mb("models--BAAI--bge-large-en-v1.5"),
                      "rss_delta_mb_cpu": benches.get("bge-large-en-v1.5|cpu", {}).get("rss_delta_mb"),
                      "vectors_827_mb": vec(827, 1024), "vectors_8887_mb": vec(8887, 1024)}}

    out = {
        "task": "$0 MiniLM bake-off prep (decision input for Dok; NOT a switch)",
        "production_untouched": f"config embedder stays {BGE}; bakeoff_* artifacts parallel-only",
        "method": {"grading": "identical to w3_2_REGRADE_v3_v4gold.json — scope-aware, N=34, hit@k over "
                              "deduped parent-doc ranks; BM25/RRF/soft-prior/nucleus params unchanged",
                   "minilm_prefixes": "none (symmetric model); bge uses its query prefix — a modeling "
                                      "difference inherent to the models, not an unfairness",
                   "centroids": "MiniLM = member-pilot-chunk means (topic_map doc_ids; merged ids unioned); "
                                "production bge centroids are field+exemplar-built — like-for-like member-mean "
                                "bge separation also reported"},
        "recall_side_by_side": {"bge_large_canonical": CANON, "minilm_measured": mini_recall,
                                "N": len(insc)},
        "per_query_diffs_hit1_or_hit5": diffs,
        "B9_check": {"bge": "coverage miss (gold never retrieved)",
                     "minilm_best_gold_rank": b9.get("best_gold_rank"), "minilm_hit@5": b9.get("hit@5")},
        "rank_cluster_check": cluster_cmp,
        "centroid_separation_mean_pairwise_cos": separation,
        "latency_benches": benches,
        "footprint": footprint,
        "recommendation_frame": "NOT a decision. Frame for Dok: bge-large if HOST-SIDE topology "
                                "(recall is canonical, RAM/latency irrelevant off-device); "
                                "MiniLM-or-quantized-bge if ON-DEVICE (CM4), given the recall delta and "
                                "CPU/footprint numbers above.",
        "provenance": {"commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                                capture_output=True, text=True).stdout.strip(),
                       "api_spend_usd": 0.0,
                       "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")},
        "per_query": rows_out,
    }
    (RES / "bakeoff_minilm_vs_bge.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    print("[bakeoff] wrote eval/results/bakeoff_minilm_vs_bge.json — md brief is written by the caller")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
