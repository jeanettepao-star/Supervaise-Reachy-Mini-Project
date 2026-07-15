"""
W1.8 — deterministic retrieval path (NO pre-composition LLM round-trip).

Assembles W1.5 (dense bge index), W1.6 (BM25 sparse), W1.7 (34-topic centroids)
into a single config-driven path:

  embed query (resident bge, GPU) ──▶ soft-prior router (cosine vs 34 centroids
  ──softmax──▶ relevance; OUT_OF_SCOPE_THRESHOLD decides in/out — BIASES, never
  GATES) ──▶ hybrid retrieve (dense + BM25 over the SAME pilot universe, RRF
  fused) ──▶ score = passage_sim + LAMBDA·topic_affinity ──▶ [W2.x-TOPP] top-p
  (nucleus) cutoff: keep chunks in rank order until the NORMALIZED fused mass
  reaches RETRIEVAL_TOP_P (floor RETRIEVAL_MIN_K). Supersedes the old top-k/MAX_K
  cap; TAU is no longer used for selection.

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


def _score_universe(query: str, allowlist_doc_ids: set, route_info: dict | None = None,
                    timing: dict | None = None) -> dict:
    """Compute the per-candidate score components over ONE universe (allowlist):
    dense cosine, RRF-fused passage_sim, topic affinity, and the fused score.
    Exposed so top-p can accumulate over different bases (W2.x-TOPP-2).
    [instrumentation] pass `timing` to record per-sub-stage ms; when None the code
    path is byte-identical (no timer calls)."""
    def _mark(k, t0):
        if timing is not None:
            timing[k] = round((time.perf_counter() - t0) * 1000, 3)
    mat, chunk_ids, doc_ids, chunk_cen_sims = _load_pilot()
    if route_info is None:
        route_info = route(query)
    qv = route_info["qv"]

    # ---- candidate universes — dense over pilot chunks; sparse over SAME docs ----
    dense_idx = [i for i, d in enumerate(doc_ids) if d in allowlist_doc_ids]
    dense_set = {chunk_ids[i] for i in dense_idx}
    _t = time.perf_counter()
    sparse_ranked = sparse.sparse_score(query, allowlist=allowlist_doc_ids, k=len(chunk_ids))
    _mark("t_sparse_bm25_ms", _t)
    sparse_set = {cid for cid, _ in sparse_ranked}
    assert dense_set == sparse_set, (
        f"RRF universe mismatch: dense={len(dense_set)} sparse={len(sparse_set)}")
    universe = dense_set

    _t = time.perf_counter()
    row_of = {cid: i for i, cid in enumerate(chunk_ids)}
    dsims = mat @ qv
    dense_cos = {cid: float(dsims[row_of[cid]]) for cid in universe}
    dense_rows = sorted(dense_idx, key=lambda i: -dsims[i])
    dense_rank = {chunk_ids[i]: r for r, i in enumerate(dense_rows, start=1)}
    _mark("t_dense_search_ms", _t)
    sparse_rank = {cid: r for r, (cid, sc) in enumerate(
        [(c, s) for c, s in sparse_ranked if s > 0], start=1)}

    _t = time.perf_counter()
    K = config.RRF_K
    rrf = {}
    for cid in universe:
        s = 1.0 / (K + dense_rank[cid])
        if cid in sparse_rank:
            s += 1.0 / (K + sparse_rank[cid])
        rrf[cid] = s
    rmax, rmin = max(rrf.values()), min(rrf.values())
    passage_sim = {cid: (rrf[cid] - rmin) / (rmax - rmin) if rmax > rmin else 1.0
                   for cid in universe}
    _mark("t_rrf_fusion_ms", _t)

    _t = time.perf_counter()
    relevance = route_info["relevance"]
    if not route_info["in_scope"]:
        relevance = np.full_like(relevance, 1.0 / len(relevance))   # global fallback
    affinity = {cid: float(chunk_cen_sims[row_of[cid]] @ relevance) for cid in universe}
    lam = config.LAMBDA
    score = {cid: passage_sim[cid] + lam * affinity[cid] for cid in universe}
    _mark("t_centroid_score_ms", _t)

    return {"universe": universe, "score": score, "dense_cos": dense_cos,
            "passage_sim": passage_sim, "affinity": affinity,
            "dense_rank": dense_rank, "sparse_rank": sparse_rank,
            "dense_set": dense_set, "sparse_set": sparse_set, "route_info": route_info}


def select_nucleus(su: dict, basis: str | None = None, temp: float | None = None,
                   top_p: float | None = None, min_k: int | None = None) -> dict:
    """Top-p (nucleus) selection over a chosen score basis. Returns ranked order,
    kept chunk_ids, cumulative mass, floor flag, and the normalized masses."""
    basis = config.RETRIEVAL_TOP_P_BASIS if basis is None else basis
    temp = config.RETRIEVAL_SOFTMAX_TEMP if temp is None else temp
    top_p = config.RETRIEVAL_TOP_P if top_p is None else top_p
    min_k = config.RETRIEVAL_MIN_K if min_k is None else min_k
    universe, score, dcos = su["universe"], su["score"], su["dense_cos"]

    if basis == "cosine":
        ranked = sorted(universe, key=lambda c: -dcos[c])
        norm = _softmax(np.array([dcos[c] for c in ranked]), temp)     # real peak
    elif basis == "softmax_temp":
        ranked = sorted(universe, key=lambda c: -score[c])
        norm = _softmax(np.array([score[c] for c in ranked]), temp)    # sharpen fused
    else:  # rrf_flat (degenerate baseline)
        ranked = sorted(universe, key=lambda c: -score[c])
        m = np.array([score[c] if score[c] > 0.0 else 0.0 for c in ranked], dtype=np.float64)
        s = float(m.sum())
        norm = (m / s) if s > 0.0 else np.full(len(ranked), 1.0 / max(len(ranked), 1))

    kept, cum = [], 0.0
    for c, mv in zip(ranked, norm):
        kept.append(c); cum += float(mv)
        if cum >= top_p:
            break
    floor_hit = len(kept) < min_k
    if floor_hit:
        kept = ranked[:min_k]
    return {"ranked": ranked, "kept": kept, "cum_mass": cum, "floor_hit": floor_hit,
            "norm_of": dict(zip(ranked, (float(x) for x in norm))), "basis": basis, "temp": temp}


# ===========================================================================
# [W2.4] Date index — ADDITIVE, config-gated (DARK by default). Deterministic
# temporal-intent detection (no LLM) + a filter/boost over the date table. When
# config.DATE_INDEX_ENABLED is False the branch below is never entered, so
# retrieve() is byte-identical to arch-baseline-v2.
_DATE_TABLE = None
_YEAR_RE = _re.compile(r"\b(1[89]\d\d|20\d\d)\b")
_RECENT_RE = _re.compile(r"\b(recent(ly)?|latest|most recent|newest|nowadays|these days)\b", _re.I)
_SINCE_RE = _re.compile(r"\b(since|after|from)\s+(1[89]\d\d|20\d\d)", _re.I)
_BEFORE_RE = _re.compile(r"\b(before|until|by|up to)\s+(1[89]\d\d|20\d\d)", _re.I)


def _load_date_table():
    global _DATE_TABLE
    if _DATE_TABLE is None:
        _DATE_TABLE = json.loads(Path(config.DATE_INDEX_PATH).read_text(encoding="utf-8"))
    return _DATE_TABLE


def temporal_intent(query: str):
    """Deterministic (no LLM) temporal intent: explicit year, range, since/before,
    or recency. Returns an intent dict or None (non-temporal -> None)."""
    q = query or ""
    years = [int(y) for y in _YEAR_RE.findall(q)]
    if len(years) >= 2:
        return {"type": "range", "lo": min(years), "hi": max(years)}
    if len(years) == 1:
        y = years[0]
        if _SINCE_RE.search(q):
            return {"type": "range", "lo": y, "hi": 9999}
        if _BEFORE_RE.search(q):
            return {"type": "range", "lo": 0, "hi": y}
        return {"type": "year", "years": [y]}
    if _RECENT_RE.search(q):
        return {"type": "recent"}
    return None


def _date_select(ranked, intent, kept):
    """Narrow/order candidates by date. Returns (new_kept, diag). Falls back to the
    original nucleus (no-op) if nothing matches — never returns empty."""
    table = _load_date_table()
    def yr(c):
        v = table.get(c.split("::")[0]) or {}
        di = v.get("date_iso")
        return int(di[:4]) if di else None
    if intent["type"] == "recent":
        ordered = sorted(kept, key=lambda c: (yr(c) is not None, yr(c) or 0), reverse=True)
        return ordered, {"mode": "recent_order", "intent": intent}
    def match(c):
        y = yr(c)
        if y is None:
            return False
        return (y in intent["years"]) if intent["type"] == "year" else (intent["lo"] <= y <= intent["hi"])
    matching = [c for c in ranked if match(c)][:config.COMPOSER_TOP_K]
    if not matching:
        return kept, {"mode": "no_match_noop", "intent": intent}
    return matching, {"mode": "date_filter", "intent": intent, "n_matched": len(matching)}


def retrieve(query: str, allowlist_doc_ids: set, route_info: dict | None = None) -> dict:
    """Hybrid dense+sparse RRF over ONE universe, biased by the soft prior, cut by
    a config-driven top-p nucleus (W2.x-TOPP-2). Returns selected chunks + diag.
    [W2.4] An optional, DARK-by-default date filter/boost may narrow/order the
    candidates when config.DATE_INDEX_ENABLED and the query carries temporal intent."""
    su = _score_universe(query, allowlist_doc_ids, route_info)
    nuc = select_nucleus(su)
    universe, score, passage_sim, affinity = su["universe"], su["score"], su["passage_sim"], su["affinity"]
    dense_rank, sparse_rank, norm_of = su["dense_rank"], su["sparse_rank"], nuc["norm_of"]
    kept = nuc["kept"]

    date_diag = None
    if config.DATE_INDEX_ENABLED:                       # DARK by default -> branch skipped
        _ti = temporal_intent(query)
        if _ti:
            kept, date_diag = _date_select(nuc["ranked"], _ti, kept)

    cutoff = {"mechanism": "top_p", "basis": nuc["basis"], "temp": nuc["temp"],
              "top_p": config.RETRIEVAL_TOP_P, "cum_mass": round(nuc["cum_mass"], 4),
              "n_kept": len(kept), "min_k_floor": config.RETRIEVAL_MIN_K,
              "min_k_floor_hit": nuc["floor_hit"]}
    if date_diag is not None:                           # only present when the date path ran
        cutoff["date_filter"] = date_diag
    return {
        "universe_size": len(universe), "dense_n": len(su["dense_set"]),
        "sparse_n": len(su["sparse_set"]), "aligned": su["dense_set"] == su["sparse_set"],
        "cutoff": cutoff,
        "selected": [(c, round(score[c], 4),
                      {"passage": round(passage_sim[c], 4), "affinity": round(affinity[c], 4),
                       "dense_rank": dense_rank[c], "sparse_rank": sparse_rank.get(c),
                       "norm_mass": round(norm_of.get(c, 0.0), 5)})
                     for c in kept],
        "fallback_global": not su["route_info"]["in_scope"],
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


def run_timed(query: str, allowlist_doc_ids: set) -> dict:
    """[instrumentation] Twin of run() with FINE per-sub-stage retrieval timing.
    Same scoring/behavior as run() (adds timers only); NO composition. Splits the
    lumped 'router' into t_query_embed_ms (bge GPU) vs t_router_ms (the soft-prior
    routing math) so the ~542ms 'router' can be attributed to the right stage."""
    T = {}
    def mark(k, t0): T[k] = round((time.perf_counter() - t0) * 1000, 3)
    t0 = time.perf_counter(); input_gate(query); mark("t_input_gate_ms", t0)
    t0 = time.perf_counter(); qv = embeddings.embed_query(query); mark("t_query_embed_ms", t0)
    t0 = time.perf_counter(); ri = route(query, qv=qv); mark("t_router_ms", t0)   # soft-prior routing math only
    st = {}
    su = _score_universe(query, allowlist_doc_ids, route_info=ri, timing=st)       # dense/sparse/rrf/centroid
    T.update(st)
    t0 = time.perf_counter(); nuc = select_nucleus(su); mark("t_cutoff_ms", t0)
    t0 = time.perf_counter()
    score = su["score"]
    selected = [(c, round(score[c], 4)) for c in nuc["kept"]]                      # payload (chunk selection)
    mark("t_payload_assembly_ms", t0)
    stages = ("t_input_gate_ms", "t_query_embed_ms", "t_router_ms", "t_sparse_bm25_ms",
              "t_dense_search_ms", "t_rrf_fusion_ms", "t_centroid_score_ms",
              "t_cutoff_ms", "t_payload_assembly_ms")
    T["t_retrieval_total_ms"] = round(sum(T.get(s, 0.0) for s in stages), 3)
    return {"timing": T, "chunks_returned": len(nuc["kept"]), "route": ri, "selected": selected}
