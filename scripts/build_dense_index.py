"""
W1.5 — build the runtime pilot dense index.

Resolves the pilot allowlist doc_ids -> their chunks (W1.4 chunk index),
embeds the chunk texts with the resident bge model (embed_documents), and
persists a float32 [n_chunks, EMBED_DIM] unit-normalised matrix + meta.

Outputs (config-driven paths):
    config.DENSE_INDEX_PATH        (.npy float32 matrix, row i = chunk_ids[i])
    config.DENSE_INDEX_META_PATH   ({model_id, dim, normalize, chunk_ids,
                                     doc_ids, build_date, n_chunks})

Usage:
    python scripts/build_dense_index.py [--allowlist v4]
"""
from __future__ import annotations

import argparse
import datetime
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

CHUNKS_JSONL = PROJECT_ROOT / "corpus" / "index" / "chunks.jsonl"
CHUNK_INDEX = PROJECT_ROOT / "corpus" / "index" / "chunk_index.json"
ALLOWLIST_DIR = PROJECT_ROOT / "reports" / "pilot-eval subset"


def load_allowlist(version: str) -> list[str]:
    path = ALLOWLIST_DIR / f"pilot_subset_frozen_{version}.csv"
    ids = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("#") or line.startswith("doc_id"):
            continue
        ids.append(line.split(",")[0].strip())
    return ids


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allowlist", default="v4", help="pilot subset version (default v4)")
    args = ap.parse_args(argv)

    allow = load_allowlist(args.allowlist)
    by_doc = json.loads(CHUNK_INDEX.read_text(encoding="utf-8"))["by_doc"]

    # resolve allowlist -> chunk_ids (flag any doc that doesn't resolve)
    unresolved = [d for d in allow if d not in by_doc]
    if unresolved:
        print(f"[build] FLAG: {len(unresolved)} allowlist doc(s) do not resolve to "
              f"chunks: {unresolved}", file=sys.stderr)
    resolved = [d for d in allow if d in by_doc]
    wanted_chunk_ids = []
    for d in resolved:
        wanted_chunk_ids.extend(by_doc[d])
    wanted = set(wanted_chunk_ids)

    # pull chunk texts in chunk_index order from the doc store
    text_by_chunk = {}
    docid_by_chunk = {}
    for line in CHUNKS_JSONL.read_text(encoding=config.FILE_ENCODING).splitlines():
        c = json.loads(line)
        if c["chunk_id"] in wanted:
            text_by_chunk[c["chunk_id"]] = c["text"]
            docid_by_chunk[c["chunk_id"]] = c["doc_id"]
    chunk_ids = [cid for cid in wanted_chunk_ids if cid in text_by_chunk]
    texts = [text_by_chunk[cid] for cid in chunk_ids]
    doc_ids = [docid_by_chunk[cid] for cid in chunk_ids]

    print(f"[build] allowlist={args.allowlist}: {len(resolved)} docs resolved, "
          f"{len(chunk_ids)} chunks to embed", flush=True)

    config.DENSE_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

    # ---- resumable, checkpointed embedding (CPU bge-large is slow; a torn-down
    #      run must not lose progress) ----
    try:
        import torch
        torch.set_num_threads(max(1, (__import__("os").cpu_count() or 2)))
    except Exception:
        pass
    partial = config.DENSE_INDEX_PATH.parent / "_pilot_dense_partial.npz"
    done: dict[str, np.ndarray] = {}
    if partial.exists():
        z = np.load(partial, allow_pickle=True)
        for cid, row in zip(z["ids"].tolist(), z["mat"]):
            done[cid] = row.astype(np.float32)
        print(f"[build] resuming: {len(done)} chunks already embedded", flush=True)
    remaining = [cid for cid in chunk_ids if cid not in done]
    BATCH = 16   # small -> frequent checkpoints -> minimal loss if a run is killed
    for i in range(0, len(remaining), BATCH):
        bids = remaining[i:i + BATCH]
        vecs = embeddings.embed_documents([text_by_chunk[c] for c in bids])
        for c, v in zip(bids, vecs):
            done[c] = v
        ids_arr = np.array(list(done.keys()), dtype=object)
        mat_arr = np.stack(list(done.values())).astype(np.float32)
        np.savez(partial, ids=ids_arr, mat=mat_arr)   # checkpoint
        print(f"[build]   embedded {min(i+BATCH,len(remaining))}/{len(remaining)} "
              f"(total {len(done)}/{len(chunk_ids)})", flush=True)

    matrix = np.stack([done[c] for c in chunk_ids]).astype(np.float32)  # final order
    assert matrix.shape == (len(chunk_ids), config.EMBED_DIM), matrix.shape
    assert matrix.dtype == np.float32
    np.save(config.DENSE_INDEX_PATH, matrix)
    meta = {
        "model_id": config.EMBED_MODEL_ID,
        "dim": config.EMBED_DIM,
        "normalize": config.EMBED_NORMALIZE,
        "allowlist_version": args.allowlist,
        "n_docs": len(resolved),
        "n_chunks": len(chunk_ids),
        "build_date": datetime.date.today().isoformat(),
        "chunk_ids": chunk_ids,
        "doc_ids": doc_ids,
        "unresolved_docs": unresolved,
    }
    Path(config.DENSE_INDEX_META_PATH).write_text(
        json.dumps(meta, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
        encoding=config.OUTPUT_ENCODING)

    partial.unlink(missing_ok=True)  # final written — drop the checkpoint
    npy_kb = config.DENSE_INDEX_PATH.stat().st_size / 1024
    meta_kb = Path(config.DENSE_INDEX_META_PATH).stat().st_size / 1024
    print(f"[build] matrix {matrix.shape} {matrix.dtype} -> {config.DENSE_INDEX_PATH.name} "
          f"({npy_kb:.0f} KB); meta -> {Path(config.DENSE_INDEX_META_PATH).name} ({meta_kb:.0f} KB)")
    print(f"[build] model={config.EMBED_MODEL_ID} dim={config.EMBED_DIM} "
          f"normalize={config.EMBED_NORMALIZE} | model loads so far: {embeddings.model_load_count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
