"""
W1.6 — sparse arm (box 7): BM25 over full chunk text + a curated atomic-phrase
dictionary. The exact-identifier complement to the dense arm — statute citations,
case names, and named entities that no embedding reliably matches. Kept
regardless of which dense model wins W3.4.

This module holds the SHARED tokenizer (used identically at index and query
time) plus the resident index loaders and sparse_score. The build itself lives
in scripts/build_sparse_index.py.

Public API:
    normalize(s)                       -> NFKC + lower + collapse-ws
    word_units(s)                      -> identifier-preserving word tokens
    load_phrase_dict(force=False)      -> resident (phrase_set, max_len_words)
    tokenize(text)                     -> tokens; dict phrases stay ATOMIC (1 term)
    load_index(force=False)            -> resident (bm25, chunk_ids, doc_ids)
    sparse_score(query, allowlist, k)  -> ranked [(chunk_id, score)]
"""
from __future__ import annotations

import json
import pickle
import re
import sys
import unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config

# Word unit = identifier-preserving token: word chars with internal . - / '
# and an optional trailing dot, so "g.r.", "no.", "v.", "8293", "ra" survive.
_WORD_RE = re.compile(r"[0-9a-z]+(?:[.\-/'][0-9a-z]+)*\.?")

# ---- resident singletons --------------------------------------------------
# _PHRASES: dict first_word -> list of (n_words, phrase_key) sorted longest-first.
# A first-word index keeps greedy longest-match cheap even when a few curated
# phrases are very long (only phrases starting at the current word are tested).
_PHRASES = None
_INDEX = None         # (bm25, chunk_ids, doc_ids)


def _build_phrase_index(keys) -> dict:
    index: dict[str, list] = {}
    for key in keys:
        first = key.split(" ", 1)[0]
        index.setdefault(first, []).append((key.count(" ") + 1, key))
    for first in index:
        index[first].sort(key=lambda lp: -lp[0])   # longest-first
    return index


def prime_phrases(keys) -> None:
    """Set the resident phrase index from an in-memory key set (build time)."""
    global _PHRASES
    _PHRASES = _build_phrase_index(keys)


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(s)).lower()).strip()


def word_units(s: str) -> list[str]:
    """Identifier-preserving word tokens of an already-or-not normalised string."""
    return _WORD_RE.findall(normalize(s))


def phrase_key(raw: str) -> str:
    """Canonical atomic-phrase key = space-joined word units (so index- and
    query-time tokenisation compare identically)."""
    return " ".join(word_units(raw))


def load_phrase_dict(force: bool = False) -> dict:
    """Load the atomic-phrase dictionary ONCE (resident). Returns the first-word
    index {first_word -> [(n_words, phrase_key), ...] longest-first}."""
    global _PHRASES
    if _PHRASES is None or force:
        data = json.loads(Path(config.SPARSE_DICT_PATH).read_text(encoding="utf-8"))
        _PHRASES = _build_phrase_index(data["phrases"].keys())
    return _PHRASES


def tokenize(text: str) -> list[str]:
    """Shared tokenizer. GREEDY LONGEST-MATCH against the phrase dictionary: a
    matched multi-word phrase emits ONE atomic token (its phrase_key); residual
    text falls back to single word tokens."""
    index = load_phrase_dict()
    units = word_units(text)
    out: list[str] = []
    i, n = 0, len(units)
    while i < n:
        matched = False
        for L, phrase in index.get(units[i], ()):   # longest-first; multi-word
            if L >= 2 and i + L <= n and " ".join(units[i:i + L]) == phrase:
                out.append(phrase)
                i += L
                matched = True
                break
        if not matched:
            out.append(units[i])
            i += 1
    return out


def load_index(force: bool = False):
    """Load the pickled BM25 index ONCE (resident)."""
    global _INDEX
    if _INDEX is None or force:
        with open(config.SPARSE_INDEX_PATH, "rb") as fh:
            state = pickle.load(fh)
        _INDEX = (state["bm25"], state["chunk_ids"], state["doc_ids"])
    return _INDEX


def query_phrase_hits(query: str) -> list[str]:
    """Curated MULTI-WORD atomic phrases present in the query, via the SAME
    analyzer used at index time (word_units -> NFKC+lower+collapse-ws -> greedy
    longest phrase match). Each returned token is a dict phrase_key that the
    tokenizer emitted atomically (contains a space => it was a >=2-word curated
    match). Single common words are never returned. This is the entity-rescue
    trigger: 'what can you say about the Museum of Liberty and Prosperity'
    -> ['museum of liberty and prosperity']."""
    return [t for t in tokenize(query) if " " in t]


def chunks_with_phrase(phrase_key_str: str, allowlist=None) -> list[str]:
    """Chunk_ids whose INDEXED text contains the atomic phrase token exactly —
    read from the BM25 per-doc term table (same analyzer as the index; no
    re-tokenising of chunk bodies). Restricted to `allowlist` (doc_ids and/or
    chunk_ids) when given. This is the exact-entity container set for rescue."""
    bm25, chunk_ids, doc_ids = load_index()
    allow = set(allowlist) if allowlist is not None else None
    out = []
    for i, df in enumerate(bm25.doc_freqs):
        if phrase_key_str in df and (
                allow is None or chunk_ids[i] in allow or doc_ids[i] in allow):
            out.append(chunk_ids[i])
    return out


def phrase_doc_freq(phrase_key_str: str) -> int:
    """Corpus-wide DISTINCT-DOC frequency of an atomic phrase token (how many
    docs contain it). Low = distinctive entity; high = common phrase. Read from
    the BM25 per-doc term table — the distinctiveness bar for entity-rescue."""
    bm25, chunk_ids, doc_ids = load_index()
    docs = set()
    for i, df in enumerate(bm25.doc_freqs):
        if phrase_key_str in df:
            docs.add(doc_ids[i])
    return len(docs)


def sparse_score(query: str, allowlist=None, k: int | None = None):
    """Rank chunks by BM25 for `query`. allowlist=None ranks the full corpus
    (W1.8 global-fallback). allowlist=<set of doc_ids and/or chunk_ids> restricts
    candidates to that subset BEFORE ranking (so the universe matches W1.5's
    dense subset for RRF). Returns ranked [(chunk_id, score)]."""
    if k is None:
        k = config.SPARSE_TOP_K
    bm25, chunk_ids, doc_ids = load_index()
    scores = bm25.get_scores(tokenize(query))   # np array over all chunks
    if allowlist is not None:
        allow = set(allowlist)
        idxs = [i for i in range(len(chunk_ids))
                if chunk_ids[i] in allow or doc_ids[i] in allow]
    else:
        idxs = range(len(chunk_ids))
    ranked = sorted(idxs, key=lambda i: -scores[i])[:k]
    return [(chunk_ids[i], float(scores[i])) for i in ranked]
