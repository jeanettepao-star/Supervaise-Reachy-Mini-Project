"""
OPS-2 C1 — $0 retrieval-only drift check vs the canonical v4 anchor.

Report-mode adaptation of verify_v4_transition.py: instead of hard-asserting
the ratified v4 numbers, it grades the live pipeline on the frozen 40-query
set vs v4 gold and RECORDS the recall deltas, so drift from (a) the batch-02
BM25/IDF rebuild, (b) the full-corpus re-embed pilot slice, and (c) the
full-corpus centroid rebuild can be measured and attributed.

Run once BEFORE Phase A/B on current artifacts (label C0_current_artifacts:
same dense+centroids as v4, post-batch-02 sparse -> isolates BM25-IDF drift)
and once AFTER (label C1_post_ops2 -> total drift). Results merge into
eval/results/ops2_c1_drift.json keyed by label.

Usage:  python scripts/run_ops2_c1.py <label>
"""
from __future__ import annotations
import csv, hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config, retrieval, service, embeddings  # noqa: E402
import sparse  # noqa: E402

RES = ROOT / "eval" / "results"
OUT = RES / "ops2_c1_drift.json"
SENT = {"OOS", "META", "GAP"}
# canonical arch-baseline-v4 C-baseline (N=34, verify_v4_transition.py)
V4 = {"1": 0.618, "5": 0.882, "chunks_sent": 0.941, "10": 0.971}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def softmax(x, t):
    z = x / max(t, 1e-6); z = z - z.max(); e = np.exp(z); return e / e.sum()


def main(label: str) -> int:
    # Load the resident model BEFORE any numpy/pickle heavy lifting: on this
    # env, torch model construction after BLAS work access-violates (the
    # exit-139 family). Model-first ordering is the safe pattern.
    embeddings.get_model()
    G = list(csv.DictReader(open(RES / "gold_reference_set.csv", encoding="utf-8-sig")))
    assert len(G) == 40 and sum(1 for r in G if r["scope_gold"] == "in") == 34
    allow = service._allowlist("v4")
    pm = json.loads((ROOT / "data/index/pilot_dense_meta.json").read_text(encoding="utf-8"))
    chunk_ids, doc_ids = pm["chunk_ids"], pm["doc_ids"]
    row_of = {c: i for i, c in enumerate(chunk_ids)}
    mat = np.load(ROOT / "data/index/pilot_dense.npy").astype(np.float32)
    cen = np.load(ROOT / "data/index/topic_centroids.npy").astype(np.float32)
    assert mat.shape == (827, config.EMBED_DIM) and cen.shape[0] == 34
    ksent = {r.get("qid") or r["query_id"]: r["chunks_sent"] for r in json.loads(
        (RES / "w3_2_PARTIAL_BC_v3_c1637cd.json").read_text(encoding="utf-8"))["per_query"]}
    chunk_cen = mat @ cen.T

    def replay_ranked(qv):
        dsims = mat @ qv
        drank = {chunk_ids[i]: k for k, i in enumerate(sorted(range(len(chunk_ids)), key=lambda i: -dsims[i]), 1)}
        return dsims, drank

    # ---- live smoke + replay parity (all 40) ----
    mism, scope_sig, live_cache = [], [], {}
    for r in G:
        qid = r["qid"]
        live = retrieval.run(r["query"], allow)
        lsel = [c for c, _, _ in live["retrieval"]["selected"]]
        qv = embeddings.embed_query(r["query"])
        live_cache[qid] = (live, qv)
        scope_sig.append((qid, r["scope_gold"], round(float(live["route"]["top_cosine"]), 4)))
        _, drank = replay_ranked(qv)
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
        score = {c: psim[c] + config.LAMBDA * float(chunk_cen[row_of[c]] @ rel) for c in rrf}
        ranked = sorted(rrf, key=lambda c: -score[c])
        sc = np.array([score[c] for c in ranked]); nm = softmax(sc, config.RETRIEVAL_SOFTMAX_TEMP)
        kept, cum = [], 0.0
        for c, m in zip(ranked, nm):
            kept.append(c); cum += float(m)
            if cum >= config.RETRIEVAL_TOP_P:
                break
        if len(kept) < config.RETRIEVAL_MIN_K:
            kept = ranked[:config.RETRIEVAL_MIN_K]
        live_cache[qid] = (ranked, kept, lsel)
        if kept != lsel:
            mism.append(qid)
    print(f"[live-vs-replay] {40 - len(mism)}/40 exact" + (f" — MISMATCH {mism}" if mism else ""))
    if mism:
        print("STOP: live path diverges from replay; grading would be unsound.", file=sys.stderr)
        return 2

    # ---- grade in-scope 34 vs v4 gold ----
    insc = [r for r in G if r["scope_gold"] == "in"]
    def gold_of(r): return [x.strip() for x in r["gold_source_docs"].split(";") if x.strip() and x.strip() not in SENT]
    per, hits = [], {k: 0 for k in ("1", "3", "5", "10", "sent")}
    for r in insc:
        qid = r["qid"]; gd = gold_of(r)
        ranked, _, _ = live_cache[qid]
        seen, rdocs = set(), []
        for c in ranked:
            d = doc_ids[row_of[c]]
            if d not in seen:
                seen.add(d); rdocs.append(d)
            if len(rdocs) >= 15:
                break
        row = {"qid": qid, "retrieved_docs": rdocs}
        for k in (1, 3, 5, 10):
            row[f"hit@{k}"] = any(d in gd for d in rdocs[:k]); hits[str(k)] += row[f"hit@{k}"]
        kq = ksent[qid]
        row["hit@sent"] = any(doc_ids[row_of[c]] in gd for c in ranked[:kq]); hits["sent"] += row["hit@sent"]
        per.append(row)
    n = len(insc)
    rec = {"1": round(hits["1"] / n, 3), "3": round(hits["3"] / n, 3),
           "5": round(hits["5"] / n, 3), "10": round(hits["10"] / n, 3),
           "chunks_sent": round(hits["sent"] / n, 3)}
    delta = {k: round(rec[k] - V4[k], 3) for k in V4}
    print(f"[{label}] recall @1/@5/@sent/@10 = {rec['1']}/{rec['5']}/{rec['chunks_sent']}/{rec['10']}")
    print(f"[{label}] delta vs v4 canon    = {delta['1']:+}/{delta['5']:+}/{delta['chunks_sent']:+}/{delta['10']:+}")

    entry = {
        "recall": rec, "delta_vs_v4": delta, "n": n, "live_vs_replay": "40/40 exact",
        "scope_signal": scope_sig,
        "artifacts": {
            "pilot_dense_sha16": _sha(ROOT / "data/index/pilot_dense.npy"),
            "topic_centroids_sha16": _sha(ROOT / "data/index/topic_centroids.npy"),
            "pilot_sparse_sha16": _sha(ROOT / "data/index/pilot_sparse.pkl"),
            "corpus_dense_model": json.loads((ROOT / "data/index/corpus_dense_meta.json")
                                             .read_text(encoding="utf-8"))["model_id"],
        },
        "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.strip(),
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "per_query": per,
    }
    doc = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {
        "anchor": "arch-baseline-v4 canonical C-baseline", "v4_expect": V4}
    doc[label] = entry
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} [{label}]")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: run_ops2_c1.py <label>", file=sys.stderr); sys.exit(1)
    sys.exit(main(sys.argv[1]))
