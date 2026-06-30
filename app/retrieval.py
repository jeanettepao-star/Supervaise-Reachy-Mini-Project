"""
W1.8 — deterministic retrieval path (NO pre-composition LLM round-trip).

Assembles W1.5 (dense bge index), W1.6 (BM25 sparse), W1.7 (34-topic centroids)
into a single config-driven path:

  embed query (resident bge, GPU) ──▶ soft-prior router (cosine vs 34 centroids
  ──softmax──▶ relevance; OUT_OF_SCOPE_THRESHOLD decides in/out — BIASES, never
  GATES) ──▶ hybrid retrieve (dense + BM25 over the SAME pilot universe, RRF
  fused) ──▶ score = passage_sim + LAMBDA·topic_affinity ──▶ dynamic cutoff
  (score ≥ TAU·top_score, bounded MIN_K..MAX_K).

Every knob is read from config.py. A weak/empty prior falls through to global
retrieval within the universe (the orphaned-content guard — GC006 pattern).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config
sys.path.insert(0, str(_REPO_ROOT / "app"))
import embeddings  # noqa: E402
import sparse  # noqa: E402

# ---- resident singletons ----
_CENTROIDS = None    # (matrix [n_topics,dim], meta)
_PILOT = None        # (matrix [n_chunks,dim], chunk_ids, doc_ids, chunk_centroid_sims)


def _load_centroids():
    global _CENTROIDS
    if _CENTROIDS is None:
        m = json.loads(Path(config.CENTROIDS_META_PATH).read_text(encoding="utf-8"))
        _CENTROIDS = (np.load(config.CENTROIDS_PATH).astype(np.float32), m)
    return _CENTROIDS


def _load_pilot():
    """Pilot dense matrix + the precomputed chunk→centroid sims (for topic_affinity)."""
    global _PILOT
    if _PILOT is None:
        mat, meta = embeddings.load_dense_index()
        cen, _ = _load_centroids()
        _PILOT = (mat.astype(np.float32), meta["chunk_ids"], meta["doc_ids"], mat @ cen.T)
    return _PILOT


def _softmax(x, temp):
    z = x / max(temp, 1e-6)
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


import re as _re
_IDENTITY_RE = _re.compile(
    r"\b(are you (an?\s+)?(ai|robot|real|human|machine|bot)|is this (an?\s+)?(ai|robot)|"
    r"who (made|built|are you)|are you (really\s+)?(cj|chief justice|panganiban)|"
    r"how (do|were) you (work|made|built))\b", _re.I)


def input_gate(query: str) -> dict:
    """Deterministic LOCAL input gate (the new-arch replacement for the removed
    Haiku gate — ZERO LLM). Flags empty input and identity probes; everything
    else is corpus-routed. Scope is informational here (the centroid router +
    OUT_OF_SCOPE_THRESHOLD do the real in/out decision)."""
    q = (query or "").strip()
    if not q:
        return {"scope": "empty"}
    if _IDENTITY_RE.search(q):
        return {"scope": "identity_probe"}
    return {"scope": "in_corpus"}


def route(query: str, qv: np.ndarray | None = None) -> dict:
    """Centroid soft prior. Returns relevance over the 34 topics + in/out scope.
    Theme BIASES retrieval (via topic_affinity); it never gates."""
    cen, meta = _load_centroids()
    if qv is None:
        qv = embeddings.embed_query(query)
    cos = cen @ qv                                   # [n_topics]
    relevance = _softmax(cos, config.TOPIC_SOFTMAX_TEMPERATURE)
    top = int(cos.argmax())
    in_scope = bool(cos[top] >= config.OUT_OF_SCOPE_THRESHOLD)   # P3: provisional floor
    order = np.argsort(-cos)[:config.MAX_TOPIC_TAGS]
    return {
        "relevance": relevance, "cos": cos, "qv": qv,
        "top_topic": meta["topic_ids"][top], "top_cosine": round(float(cos[top]), 4),
        "in_scope": in_scope,
        "routed_topics": [(meta["topic_ids"][i], round(float(cos[i]), 4)) for i in order],
    }


def retrieve(query: str, allowlist_doc_ids: set, route_info: dict | None = None) -> dict:
    """Hybrid dense+sparse RRF over ONE universe (the allowlist), biased by the
    soft prior. Returns selected chunks (dynamic cutoff) + diagnostics."""
    mat, chunk_ids, doc_ids, chunk_cen_sims = _load_pilot()
    if route_info is None:
        route_info = route(query)
    qv = route_info["qv"]

    # ---- P2: candidate universes — dense over the pilot chunks; sparse filtered
    #      to the SAME doc set. Assert they align before fusing. ----
    dense_idx = [i for i, d in enumerate(doc_ids) if d in allowlist_doc_ids]
    dense_set = {chunk_ids[i] for i in dense_idx}
    sparse_ranked = sparse.sparse_score(query, allowlist=allowlist_doc_ids, k=len(chunk_ids))
    sparse_set = {cid for cid, _ in sparse_ranked}
    assert dense_set == sparse_set, (
        f"RRF universe mismatch: dense={len(dense_set)} sparse={len(sparse_set)}")
    universe = dense_set
    n = len(universe)

    # ---- dense ranking (cosine over the universe) ----
    dsims = mat @ qv
    dense_rows = sorted(dense_idx, key=lambda i: -dsims[i])
    dense_rank = {chunk_ids[i]: r for r, i in enumerate(dense_rows, start=1)}
    # ---- sparse ranking (only matched chunks, bm25 > 0) ----
    sparse_rank = {cid: r for r, (cid, sc) in enumerate(
        [(c, s) for c, s in sparse_ranked if s > 0], start=1)}

    # ---- RRF fuse ----
    K = config.RRF_K
    rrf = {}
    for cid in universe:
        s = 1.0 / (K + dense_rank[cid])
        if cid in sparse_rank:
            s += 1.0 / (K + sparse_rank[cid])
        rrf[cid] = s
    rmax, rmin = max(rrf.values()), min(rrf.values())
    passage_sim = {cid: (rrf[cid] - rmin) / (rmax - rmin) if rmax > rmin else 1.0
                   for cid in universe}   # normalise so it's the primary signal

    # ---- topic_affinity = relevance · (chunk→centroid sims). Global fallback:
    #      a weak/out-of-scope prior contributes no bias (uniform). ----
    relevance = route_info["relevance"]
    if not route_info["in_scope"]:
        relevance = np.full_like(relevance, 1.0 / len(relevance))   # global fallback
    row_of = {cid: i for i, cid in enumerate(chunk_ids)}
    affinity = {cid: float(chunk_cen_sims[row_of[cid]] @ relevance) for cid in universe}

    lam = config.LAMBDA
    score = {cid: passage_sim[cid] + lam * affinity[cid] for cid in universe}

    # ---- dynamic cutoff: keep score >= TAU·top, bounded MIN_K..MAX_K ----
    ranked = sorted(universe, key=lambda c: -score[c])
    top = score[ranked[0]]
    kept = [c for c in ranked if score[c] >= config.TAU * top]
    kept = ranked[:config.MIN_K] if len(kept) < config.MIN_K else kept
    kept = kept[:config.MAX_K]

    return {
        "universe_size": n, "dense_n": len(dense_set), "sparse_n": len(sparse_set),
        "aligned": dense_set == sparse_set,
        "selected": [(c, round(score[c], 4),
                      {"passage": round(passage_sim[c], 4), "affinity": round(affinity[c], 4),
                       "dense_rank": dense_rank[c], "sparse_rank": sparse_rank.get(c)})
                     for c in kept],
        "fallback_global": not route_info["in_scope"],
    }


def run(query: str, allowlist_doc_ids: set) -> dict:
    """Full deterministic retrieval with per-stage timing (proves zero
    pre-composition LLM round-trips — every stage below is local)."""
    t = {}
    t0 = time.perf_counter()
    gate = input_gate(query); t["input_gate_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    t0 = time.perf_counter()
    qv = embeddings.embed_query(query); t["embed_query_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    t0 = time.perf_counter()
    ri = route(query, qv=qv); t["route_centroids_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    t0 = time.perf_counter()
    rr = retrieve(query, allowlist_doc_ids, route_info=ri); t["retrieve_rrf_cutoff_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return {"gate": gate, "route": ri, "retrieval": rr, "timing": t,
            "llm_calls_before_composition": 0}
