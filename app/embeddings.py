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
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config

# ---- resident singletons (module-level; never per-request) ----------------
_MODEL = None
_LOAD_COUNT = 0
_INDEX = None          # (matrix float32 [n,dim], meta dict)


def get_model():
    """Lazy-load the embedding model ONCE and keep it resident. Subsequent
    calls return the same object (no cold-start reload per request)."""
    global _MODEL, _LOAD_COUNT
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer  # heavy import, deferred
        print(f"[embeddings] loading resident model {config.EMBED_MODEL_ID} "
              f"on {config.EMBED_DEVICE} (load #{_LOAD_COUNT + 1})", file=sys.stderr)
        _MODEL = SentenceTransformer(config.EMBED_MODEL_ID, device=config.EMBED_DEVICE)
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
