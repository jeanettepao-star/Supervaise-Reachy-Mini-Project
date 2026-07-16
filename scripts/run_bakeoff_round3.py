"""
$0 BAKE-OFF ROUND 3 — four-candidate embedder evidence for Dok's ratification.

A bge-large fp32 (canonical, carried) · B MiniLM (round-2, carried/reloaded)
C bge-base-en-v1.5 768d (NEW, full parallel build) · D bge-large dynamic-int8
(NEW, torch-native quantize_dynamic on Linear layers, CPU — the CM4 case).

NEW METRIC all candidates: recall@chunks-sent — graded at each query's canonical
v3 chunks_sent (median 9, range 4-12; from w3_2_PARTIAL_BC_v3_c1637cd.json), i.e.
what the composer actually sees. Doc-dedup recall@{1,3,5,10} same as canonical.

$0, local. Production untouched; artifacts under bakeoff_*. Pilot 827 only.
Frozen-file discipline: content-aware gold check before scoring; N=34 asserted.

Usage: python scripts/run_bakeoff_round3.py
       python scripts/run_bakeoff_round3.py --bench <model_id> <device> [int8]
"""
from __future__ import annotations
import csv, ctypes, json, statistics, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402

RES = ROOT / "eval" / "results"
IDX = ROOT / "data" / "index"
BGE_L, BGE_B, MINILM = "BAAI/bge-large-en-v1.5", "BAAI/bge-base-en-v1.5", "sentence-transformers/all-MiniLM-L6-v2"
SENTINELS = {"OOS", "META", "GAP"}
CLUSTER = ["A2", "A4", "B10", "C17", "C18", "D23", "E28", "E29"]
CANON_A = {"1": 0.735, "3": 0.941, "5": 0.971, "10": 0.971}


def rss_mb():
    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),
                                                  ctypes.byref(pmc), pmc.cb)
    return (pmc.WorkingSetSize / 1048576) if ok else None


def load_model(model_id, device, int8=False):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(model_id, device=device)
    if int8:
        import torch
        am = m._first_module().auto_model
        m._first_module().auto_model = torch.quantization.quantize_dynamic(
            am, {torch.nn.Linear}, dtype=torch.qint8)
    return m


def qprefix(model_id):
    return config.EMBED_QUERY_PREFIX if model_id.startswith("BAAI/bge") else ""


def bench(model_id, device, int8):
    G = list(csv.DictReader(open(RES / "gold_reference_set.csv", encoding="utf-8-sig")))
    r0 = rss_mb()
    t0 = time.perf_counter(); m = load_model(model_id, device, int8)
    load_s = round(time.perf_counter() - t0, 2)
    m.encode(["warm"], normalize_embeddings=True, show_progress_bar=False)  # materialize
    r1 = rss_mb()
    pre = qprefix(model_id)
    def enc(q):
        t = time.perf_counter()
        m.encode([pre + q], normalize_embeddings=True, show_progress_bar=False)
        return (time.perf_counter() - t) * 1000
    same = [enc("What is the rule of law?") for _ in range(20)]
    anchors = [enc(r["query"]) for r in G]
    params = sum(p.numel() for p in m._first_module().auto_model.parameters())
    def pct(v, p): return round(sorted(v)[min(int(len(v) * p), len(v) - 1)], 1)
    print("BENCH_JSON:" + json.dumps({
        "model": model_id + ("+int8" if int8 else ""), "device": device, "model_load_s": load_s,
        "rss_after_load_mb": (round(r1 - r0, 1) if (r0 is not None and r1 is not None) else "MEASUREMENT_FAILED"),
        "params_millions": round(params / 1e6, 1),
        "same_query_20x": {"cold_first_ms": round(same[0], 1),
                           "warm_rest_ms": {"p50": pct(same[1:], .5), "p95": pct(same[1:], .95)}},
        "anchor_40": {"p50": pct(anchors, .5), "p95": pct(anchors, .95)}}))


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--bench":
        return bench(sys.argv[2], sys.argv[3], len(sys.argv) > 4 and sys.argv[4] == "int8")
    import sparse

    # ---- frozen-file discipline ----
    d = subprocess.run(["git", "diff", "--ignore-cr-at-eol", "--", "eval/results/gold_reference_set.csv"],
                       cwd=ROOT, capture_output=True, text=True)
    assert not d.stdout.strip(), "GOLD CONTENT DRIFT — STOP"
    G = list(csv.DictReader(open(RES / "gold_reference_set.csv", encoding="utf-8-sig")))
    assert sum(1 for r in G if r["scope_gold"] == "in") == 34, "N != 34 — STOP"
    print("[pre] gold content-intact; N=34")

    pm = json.loads((IDX / "pilot_dense_meta.json").read_text(encoding="utf-8"))
    chunk_ids, doc_ids = pm["chunk_ids"], pm["doc_ids"]
    row_of = {c: i for i, c in enumerate(chunk_ids)}
    txt = {}
    for ln in (ROOT / "corpus/index/chunks.jsonl").read_text(encoding="utf-8").splitlines():
        if ln.strip():
            c = json.loads(ln); txt[c["chunk_id"]] = c["text"]
    texts = [txt[c] for c in chunk_ids]
    allow = set(l.split(",")[0].strip() for l in
                (ROOT / "reports/pilot-eval subset/pilot_subset_frozen_v4.csv")
                .read_text(encoding="utf-8-sig").splitlines()
                if not l.startswith("#") and not l.startswith("doc_id"))
    ksent = {r.get("qid") or r["query_id"]: r["chunks_sent"] for r in json.loads(
        (RES / "w3_2_PARTIAL_BC_v3_c1637cd.json").read_text(encoding="utf-8"))["per_query"]}
    canon_pq = {r["qid"]: r for r in json.loads(
        (RES / "w3_2_REGRADE_v3_v4gold.json").read_text(encoding="utf-8"))["per_query"]}
    tmap = json.loads((ROOT / "corpus/voice/topic_map.json").read_text(encoding="utf-8"))["topics"]
    members = {t["id"]: set(t["doc_ids"]) for t in (tmap.values() if isinstance(tmap, dict) else tmap)}
    topic_ids = json.loads((IDX / "topic_centroids_meta.json").read_text(encoding="utf-8"))["topic_ids"]

    def gold_of(r):
        return [x.strip() for x in (r["gold_source_docs"] or "").split(";") if x.strip() and x.strip() not in SENTINELS]

    # sparse ranks are embedder-independent: compute ONCE per query
    print("[pre] computing 40 sparse rankings once...")
    sparse_ranks = {}
    for r in G:
        sr = sparse.sparse_score(r["query"], allowlist=allow, k=len(chunk_ids))
        sparse_ranks[r["qid"]] = {cid: k for k, (cid, s) in enumerate([(c, s) for c, s in sr if s > 0], 1)}

    def member_centroids(mat):
        cen = np.zeros((len(topic_ids), mat.shape[1]), dtype=np.float32)
        gm = mat.mean(axis=0); gm /= np.linalg.norm(gm)
        for i, tid in enumerate(topic_ids):
            docs = set().union(*(members.get(s, set()) for s in tid.split("+")))
            rows = [row_of[c] for c in chunk_ids if doc_ids[row_of[c]] in docs]
            if rows:
                v = mat[rows].mean(axis=0); cen[i] = v / np.linalg.norm(v)
            else:
                cen[i] = gm
        return cen

    def softmax(x, t):
        z = x / max(t, 1e-6); z = z - z.max(); e = np.exp(z); return e / e.sum()

    def replay(mat, qvecs, cen):
        """Per-query ranked chunk list (full pipeline math, sparse cached)."""
        chunk_cen = mat @ cen.T
        out = {}
        didx = list(range(len(chunk_ids)))          # allowlist == pilot (all 827)
        for gi, r in enumerate(G):
            qv = qvecs[gi]
            dsims = mat @ qv
            drank = {chunk_ids[i]: k for k, i in enumerate(sorted(didx, key=lambda i: -dsims[i]), 1)}
            srank = sparse_ranks[r["qid"]]
            K = config.RRF_K
            rrf = {c: 1.0 / (K + drank[c]) + (1.0 / (K + srank[c]) if c in srank else 0.0) for c in drank}
            mx, mn = max(rrf.values()), min(rrf.values())
            psim = {c: (rrf[c] - mn) / (mx - mn) if mx > mn else 1.0 for c in rrf}
            rcos = cen @ qv
            rel = softmax(rcos, config.TOPIC_SOFTMAX_TEMPERATURE)
            if rcos.max() < config.OUT_OF_SCOPE_THRESHOLD:
                rel = np.full_like(rel, 1.0 / len(rel))
            score = {c: psim[c] + config.LAMBDA * float(chunk_cen[row_of[c]] @ rel) for c in rrf}
            out[r["qid"]] = sorted(rrf, key=lambda c: -score[c])
        return out

    def grade(ranked_chunks_by_qid):
        rows, per = [], {}
        for r in G:
            qid = r["qid"]; gd = gold_of(r)
            rc = ranked_chunks_by_qid[qid]
            seen, rdocs = set(), []
            for c in rc:
                dd = doc_ids[row_of[c]]
                if dd not in seen:
                    seen.add(dd); rdocs.append(dd)
                if len(rdocs) >= 15:
                    break
            row = {"qid": qid, "scope": r["scope_gold"]}
            if r["scope_gold"] == "in":
                for k in (1, 3, 5, 10):
                    row[f"hit@{k}"] = any(x in gd for x in rdocs[:k])
                kq = ksent[qid]
                row["hit@sent"] = any(doc_ids[row_of[c]] in gd for c in rc[:kq])
                row["k_sent"] = kq
                row["best_rank"] = next((i + 1 for i, x in enumerate(rdocs) if x in gd), None)
            rows.append(row); per[qid] = row
        insc = [x for x in rows if x["scope"] == "in"]
        rec = {str(k): round(sum(1 for x in insc if x[f"hit@{k}"]) / len(insc), 3) for k in (1, 3, 5, 10)}
        rec["chunks_sent"] = round(sum(1 for x in insc if x["hit@sent"]) / len(insc), 3)
        return rec, per

    def cen_stats(C):
        S = C @ C.T; iu = np.triu_indices(len(C), 1); v = S[iu]
        return {"mean": round(float(v.mean()), 4), "p5": round(float(np.percentile(v, 5)), 4),
                "p95": round(float(np.percentile(v, 95)), 4)}

    results, per_all, dims = {}, {}, {}

    # ---- A: canonical bge-large. recall@k carried; recall@chunks-sent from arch_v2 chunk ids ----
    av2 = {q["qid"]: q for q in json.loads((ROOT / "arch_baseline_v2.json").read_text(encoding="utf-8"))["queries"]}
    a_hits = []
    for r in G:
        if r["scope_gold"] != "in":
            continue
        gd = gold_of(r); kq = ksent[r["qid"]]
        sent_chunks = av2[r["qid"]]["retrieved_chunk_ids"][:kq]
        a_hits.append(any(doc_ids[row_of[c]] in gd for c in sent_chunks if c in row_of))
    results["A_bge_large_fp32"] = {**CANON_A, "chunks_sent": round(sum(a_hits) / len(a_hits), 3),
                                   "source": "canonical regrade + arch_baseline_v2 chunk ids"}

    # ---- B: MiniLM — reload saved chunks/centroids; re-encode 40 queries ----
    print("[B] MiniLM replay (saved matrix; queries re-encoded)...")
    mmat = np.load(IDX / "bakeoff_minilm_dense.npy")
    mcen = np.load(IDX / "bakeoff_minilm_centroids.npy")
    mm = load_model(MINILM, config.EMBED_DEVICE)
    mq = mm.encode([r["query"] for r in G], normalize_embeddings=True, show_progress_bar=False).astype(np.float32)
    del mm
    rec, per = grade(replay(mmat, mq, mcen)); results["B_minilm_384"] = rec; per_all["B"] = per
    dims["B"] = mmat.shape[1]; cen_B = mcen

    # ---- C: bge-base — full parallel build (GPU); RESUME from saved matrix if present ----
    print("[C] bge-base build + replay (GPU)...")
    mb = load_model(BGE_B, config.EMBED_DEVICE)
    if (IDX / "bakeoff_bgebase_dense.npy").exists():
        print("[C] resume: loading saved chunk matrix")
        cmat = np.load(IDX / "bakeoff_bgebase_dense.npy").astype(np.float32)
    else:
        cmat = mb.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False).astype(np.float32)
    cq = mb.encode([qprefix(BGE_B) + r["query"] for r in G], normalize_embeddings=True,
                   show_progress_bar=False).astype(np.float32)
    del mb
    ccen = member_centroids(cmat)
    np.save(IDX / "bakeoff_bgebase_dense.npy", cmat); np.save(IDX / "bakeoff_bgebase_centroids.npy", ccen)
    (IDX / "bakeoff_bgebase_meta.json").write_text(json.dumps({
        "model_id": BGE_B, "dim": int(cmat.shape[1]), "n_chunks": len(chunk_ids), "normalize": True,
        "prefixes": "bge query prefix on queries; none on docs (same recipe as production bge)",
        "parallel_artifact": "NEVER wired into production"}, indent=2) + "\n", encoding="utf-8")
    rec, per = grade(replay(cmat, cq, ccen)); results["C_bge_base_768"] = rec; per_all["C"] = per
    dims["C"] = cmat.shape[1]; cen_C = ccen

    # ---- D: bge-large dynamic int8 (CPU) — quantize, verify, embed ----
    print("[D] bge-large int8 (torch dynamic, CPU): verify + embed 827 chunks — the slow part...")
    md = load_model(BGE_L, "cpu", int8=True)
    # cosine sanity vs fp32 production vectors on 10 sample chunks
    sample = list(range(0, 827, 83))[:10]
    fp32 = np.load(IDX / "pilot_dense.npy").astype(np.float32)
    qv10 = md.encode([texts[i] for i in sample], normalize_embeddings=True, batch_size=4,
                     show_progress_bar=False).astype(np.float32)
    sims10 = [float(qv10[j] @ fp32[i]) for j, i in enumerate(sample)]
    int8_fidelity = round(float(np.mean(sims10)), 4)
    print(f"[D] int8-vs-fp32 cosine on 10 chunks: mean {int8_fidelity} (expect >0.99)")
    if (IDX / "bakeoff_bgelarge_int8_dense.npy").exists():
        print("[D] resume: loading saved int8 chunk matrix")
        dmat = np.load(IDX / "bakeoff_bgelarge_int8_dense.npy").astype(np.float32)
        d_embed_min = "resumed(saved)"
    else:
        t0 = time.perf_counter()
        dmat = md.encode(texts, normalize_embeddings=True, batch_size=8, show_progress_bar=False).astype(np.float32)
        d_embed_min = round((time.perf_counter() - t0) / 60, 1)
    dq = md.encode([qprefix(BGE_L) + r["query"] for r in G], normalize_embeddings=True,
                   show_progress_bar=False).astype(np.float32)
    del md
    dcen = member_centroids(dmat)
    np.save(IDX / "bakeoff_bgelarge_int8_dense.npy", dmat); np.save(IDX / "bakeoff_bgelarge_int8_centroids.npy", dcen)
    (IDX / "bakeoff_bgelarge_int8_meta.json").write_text(json.dumps({
        "model_id": BGE_L + " + torch quantize_dynamic(Linear, qint8), CPU", "dim": 1024,
        "int8_vs_fp32_cosine_10chunks": int8_fidelity, "chunk_embed_minutes_cpu": d_embed_min,
        "parallel_artifact": "NEVER wired into production"}, indent=2) + "\n", encoding="utf-8")
    rec, per = grade(replay(dmat, dq, dcen)); results["D_bge_large_int8"] = rec; per_all["D"] = per
    dims["D"] = 1024; cen_D = dcen

    # ---- diffs vs A + B9/cluster for C and D ----
    def diffs_vs_A(per):
        out = []
        for qid, row in per.items():
            if row["scope"] != "in":
                continue
            cp = canon_pq[qid]
            if bool(cp.get("hit@5")) != row["hit@5"]:
                out.append({"qid": qid, "A_hit@5": cp.get("hit@5"), "cand_hit@5": row["hit@5"],
                            "A_best_rank": cp.get("best_gold_rank"), "cand_best_rank": row["best_rank"]})
        return out
    analysis = {}
    for cand in ("C", "D"):
        per = per_all[cand]
        analysis[cand] = {"hit5_diffs_vs_A": diffs_vs_A(per),
                          "B9": {"best_rank": per["B9"]["best_rank"], "hit@5": per["B9"]["hit@5"]},
                          "cluster": [{"qid": q, "A_best_rank": canon_pq[q].get("best_gold_rank"),
                                       "cand_best_rank": per[q]["best_rank"], "hit@1": per[q]["hit@1"]}
                                      for q in CLUSTER]}

    # ---- centroid stats (per-model; NOT cross-comparable) ----
    bge_cen_prod = np.load(IDX / "topic_centroids.npy").astype(np.float32)
    centroid_stats = {"A_production_fieldbuilt": cen_stats(bge_cen_prod),
                      "B_minilm_member_mean": cen_stats(cen_B),
                      "C_bgebase_member_mean": cen_stats(cen_C),
                      "D_bgelarge_int8_member_mean": cen_stats(cen_D),
                      "caveat": "mean pairwise cosine is NOT comparable across models (bge compresses "
                                "the cosine range); per-model p5-p95 given as context.",
                      "zero_member_topics_neutral_fallback": ["death_penalty_and_echegaray",
                                                              "honors_received", "robot_identity_meta"]}

    # ---- benches: C cuda+cpu, D int8-cpu; A/B carried from round 2 ----
    benches = {}
    for mid, dev, q8 in [(BGE_B, "cuda", False), (BGE_B, "cpu", False), (BGE_L, "cpu", True)]:
        tag = f"{mid.split('/')[-1]}{'+int8' if q8 else ''}|{dev}"
        print(f"[bench] {tag} ...")
        cmd = [sys.executable, __file__, "--bench", mid, dev] + (["int8"] if q8 else [])
        p = subprocess.run(cmd, capture_output=True, timeout=1800)
        line = next((l for l in p.stdout.decode("utf-8", "replace").splitlines()
                     if l.startswith("BENCH_JSON:")), None)
        benches[tag] = json.loads(line[11:]) if line else {"error": p.stderr.decode("utf-8", "replace")[-300:]}
    r2 = json.loads((RES / "bakeoff_minilm_vs_bge.json").read_text(encoding="utf-8"))["latency_benches"]
    benches.update({f"CARRIED_r2|{k}": v for k, v in r2.items()})

    vec = lambda n, d: round(n * d * 4 / 1e6, 2)
    footprint = {
        "A_bge_large_fp32": {"params_M": 335.1, "fp32_ram_est_mb": 1340, "disk_mb": "see r2 artifact",
                             "vec827_mb": vec(827, 1024), "vec8887_mb": vec(8887, 1024)},
        "B_minilm": {"params_M": 22.7, "fp32_ram_est_mb": 91,
                     "vec827_mb": vec(827, 384), "vec8887_mb": vec(8887, 384)},
        "C_bge_base": {"params_M": benches.get("bge-base-en-v1.5|cpu", {}).get("params_millions"),
                       "fp32_ram_est_mb": 437, "vec827_mb": vec(827, 768), "vec8887_mb": vec(8887, 768)},
        "D_bge_large_int8": {"params_M": 335.1,
                             "ram_est_mb": "~400-500 (int8 Linear weights ~1/4 of the ~1.2GB Linear share + fp32 rest)",
                             "disk": "runtime-quantized from the fp32 snapshot (no separate artifact)",
                             "vec827_mb": vec(827, 1024), "vec8887_mb": vec(8887, 1024)},
    }

    out = {"task": "$0 bake-off ROUND 3 (A fp32 / B MiniLM / C bge-base / D bge-large-int8)",
           "production_untouched": True, "grading": "canonical method, repaired v4 gold, N=34; "
           "recall@chunks-sent graded at each query's canonical v3 chunks_sent (median 9, range 4-12)",
           "recall": results, "analysis_C_D": analysis, "int8_fidelity_cos10": int8_fidelity,
           "centroid_stats": centroid_stats, "latency_benches": benches, "footprint": footprint,
           "provenance": {"commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                                   capture_output=True, text=True).stdout.strip(),
                          "api_spend_usd": 0.0,
                          "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")},
           "per_query": {k: v for k, v in per_all.items()}}
    (RES / "bakeoff_round3.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n=== ROUND 3 recall (N=34) ===")
    for k, v in results.items():
        print(f"  {k:22} @1={v['1']} @5={v['5']} @sent={v['chunks_sent']} @10={v['10']}")
    print(f"int8 fidelity: {int8_fidelity} | D chunk-embed: {d_embed_min} min CPU")
    print("wrote eval/results/bakeoff_round3.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
