"""
W1.5 — runtime dense arm of the retrieval pipeline (box 5).

A module-level singleton holds ONE resident embedding model for the whole
service lifetime. The model id / dim / prefixes / device all come from config.py
so the model stays swappable (bge-large-en-v1.5 today; MiniLM-384 and OpenAI
text-embedding-3 are the W3.4 benchmark alternatives) without touching call
sites. The same EMBED_MODEL_ID + EMBED_DIM are used by W1.7 centroids.

Public API:
    get_model()                 -> the resident SentenceTransformer (loads once)
    model_load_count()          -> int, proves the model is not reloaded per call
    embed_documents(texts)      -> float32 [n, EMBED_DIM]  (search_document, no prefix)
    embed_query(text)           -> float32 [EMBED_DIM]     (search_query, prefixed)
    load_dense_index()          -> (matrix, meta) resident, loaded once
    dense_score(query, top_k)   -> ranked [(chunk_id, cosine)]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# torch 2.5.1 + transformers 5.12.1 on this Windows env: lazily initializing
# torch's intra-op (OpenMP) runtime mid-load access-violates (exit 139) —
# seen at from_pretrained weight init (modeling_bert._init_weights) and even
# at a bare torch.get_num_threads() after a large np.load. The proven fix
# (2026-07-17: crash 100% without, 0% with) is to import torch and initialize
# its thread pool single-threaded HERE, before numpy or any model machinery
# touches native runtimes. OMP_NUM_THREADS is set as belt-and-braces; the
# operative part is the early set_num_threads(1) call. Production encodes run
# on CUDA, so encode throughput is unaffected.
os.environ.setdefault("OMP_NUM_THREADS", "1")
import torch  # heavy import promoted from get_model() — must init first
torch.set_num_threads(1)

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config

# ---- resident singletons (module-level; never per-request) ----------------
_MODEL = None
_LOAD_COUNT = 0
_INDEX = None          # (matrix float32 [n,dim], meta dict)


def _local_snapshot(model_id: str):
    """Resolve a cached HF model to its local snapshot DIRECTORY. Loading from
    the local path (vs the 'org/name' hub id) avoids the hub-resolution code
    path that, on this Windows env, loads a non-applink OpenSSL DLL and aborts
    (OPENSSL_Uplink: no OPENSSL_Applink). Returns None if not cached."""
    import glob
    import os
    if os.path.isdir(model_id):
        return model_id
    hub = os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    base = os.path.join(hub, "hub", "models--" + model_id.replace("/", "--"))
    ref = os.path.join(base, "refs", "main")
    if os.path.isfile(ref):
        snap = os.path.join(base, "snapshots", open(ref).read().strip())
        if os.path.isdir(snap):
            return snap
    snaps = sorted(glob.glob(os.path.join(base, "snapshots", "*")))
    return snaps[-1] if snaps else None


def get_model():
    """Lazy-load the embedding model ONCE and keep it resident. Subsequent
    calls return the same object (no cold-start reload per request)."""
    global _MODEL, _LOAD_COUNT
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer  # heavy import, deferred
        # Resolution (portable; no machine-specific literal):
        #   EMBED_MODEL_PATH (config) → HF cache snapshot dir → EMBED_MODEL_ID (hub)
        import os
        if config.EMBED_MODEL_PATH and os.path.isdir(config.EMBED_MODEL_PATH):
            src, how = config.EMBED_MODEL_PATH, "config-path"
        elif _local_snapshot(config.EMBED_MODEL_ID):
            src, how = _local_snapshot(config.EMBED_MODEL_ID), "cache-snapshot"
        else:
            src, how = config.EMBED_MODEL_ID, "hub"
        print(f"[embeddings] loading resident model {config.EMBED_MODEL_ID} "
              f"on {config.EMBED_DEVICE} (load #{_LOAD_COUNT + 1}; {how})", file=sys.stderr)
        _MODEL = SentenceTransformer(src, device=config.EMBED_DEVICE)
        _LOAD_COUNT += 1
        # st<5 used get_sentence_embedding_dimension; st>=5 renamed it.
        _dim_fn = (getattr(_MODEL, "get_embedding_dimension", None)
                   or _MODEL.get_sentence_embedding_dimension)
        dim = _dim_fn()
        if dim != config.EMBED_DIM:
            raise ValueError(
                f"EMBED_DIM mismatch: model {config.EMBED_MODEL_ID} emits {dim}, "
                f"config.EMBED_DIM={config.EMBED_DIM}. Fix config before indexing.")
    return _MODEL


def model_load_count() -> int:
    """How many times the model was actually constructed (should stay 1)."""
    return _LOAD_COUNT


def _encode(texts: list[str]) -> np.ndarray:
    model = get_model()
    vecs = model.encode(
        texts, batch_size=32, convert_to_numpy=True,
        normalize_embeddings=config.EMBED_NORMALIZE, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def embed_documents(texts: list[str]) -> np.ndarray:
    """Embed chunk/document texts (search_document): no query prefix on bge.
    Returns float32 [n, EMBED_DIM], unit-normalised when EMBED_NORMALIZE."""
    prefixed = [config.EMBED_DOCUMENT_PREFIX + t for t in texts]
    return _encode(prefixed)


def embed_query(text: str) -> np.ndarray:
    """Embed a search query (search_query): prepend EMBED_QUERY_PREFIX.
    Returns float32 [EMBED_DIM]."""
    return _encode([config.EMBED_QUERY_PREFIX + text])[0]


def load_dense_index(force: bool = False):
    """Load the persisted pilot dense matrix + meta ONCE (resident)."""
    global _INDEX
    if _INDEX is None or force:
        matrix = np.load(config.DENSE_INDEX_PATH).astype(np.float32)
        meta = json.loads(Path(config.DENSE_INDEX_META_PATH).read_text(encoding="utf-8"))
        _INDEX = (matrix, meta)
    return _INDEX


def dense_score(query: str, top_k: int = 10) -> list[tuple[str, float]]:
    """Rank pilot chunks by cosine to the query. Uses embed_query (prefixed)
    and the resident unit-normalised matrix, so cosine == dot product."""
    matrix, meta = load_dense_index()
    qv = embed_query(query)                      # [dim], normalised
    sims = matrix @ qv                           # [n] cosine (both unit-norm)
    k = min(top_k, sims.shape[0])
    top = np.argpartition(-sims, k - 1)[:k]
    top = top[np.argsort(-sims[top])]
    chunk_ids = meta["chunk_ids"]
    return [(chunk_ids[i], float(sims[i])) for i in top]
