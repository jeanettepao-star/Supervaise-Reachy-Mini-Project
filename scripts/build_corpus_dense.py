"""
W1.7 Step 2 — full-corpus dense embeddings (all ~8,887 chunks).

Persists CORPUS_DENSE_PATH (.npy float32, unit-normalised, row i = chunk_ids[i])
+ CORPUS_DENSE_META_PATH (model_id, dim, backend, n_chunks, chunk_ids, source
sha256, build_date). The 827 pilot rows are verified to match pilot_dense.npy
(one embedding regime — the parity gate).

CHECKPOINT KEYING (W1.7 scope guard): the resume checkpoint is keyed on
(EMBED_MODEL_ID, EMBED_BACKEND, EMBED_NORMALIZE, chunk_index sha256, chunk-set
hash). If ANY of these drift, the checkpoint is discarded — a stale or
wrong-precision checkpoint can never resume into a mixed embedding set.

NOTE: on CPU (~0.27 chunks/s) the full run is ~9.5 hrs; intended for a CUDA box
(set CJ_EMBED_BACKEND=cuda_fp32, CJ_EMBED_DEVICE=cuda). Config-driven; exits 0 on
success with no partial leftovers.

Usage:  python scripts/build_corpus_dense.py
"""
from __future__ import annotations

import datetime
import hashlib
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


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _checkpoint_key(chunk_ids: list[str], chunk_index_sha: str) -> str:
    h = hashlib.sha256()
    for part in (config.EMBED_MODEL_ID, config.EMBED_BACKEND,
                 str(config.EMBED_NORMALIZE), chunk_index_sha,
                 hashlib.sha256("\n".join(chunk_ids).encode()).hexdigest()):
        h.update(part.encode())
    return h.hexdigest()


def main() -> int:
    ckpt = config.CORPUS_DENSE_PATH.parent / "_corpus_dense_partial.npz"
    out = [config.CORPUS_DENSE_PATH, config.CORPUS_DENSE_META_PATH]
    try:
        config.CORPUS_DENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        chunk_ids, texts = [], []
        for line in CHUNKS_JSONL.read_text(encoding=config.FILE_ENCODING).splitlines():
            c = json.loads(line)
            chunk_ids.append(c["chunk_id"]); texts.append(c["text"])
        text_of = dict(zip(chunk_ids, texts))
        chunk_index_sha = _sha256_file(CHUNK_INDEX)
        key = _checkpoint_key(chunk_ids, chunk_index_sha)

        # resume only if the checkpoint key matches (else invalidate)
        done: dict[str, np.ndarray] = {}
        if ckpt.exists():
            z = np.load(ckpt, allow_pickle=True)
            if str(z["key"]) == key:
                for cid, row in zip(z["ids"].tolist(), z["mat"]):
                    done[cid] = row.astype(np.float32)
                print(f"[corpus-dense] resume: {len(done)} chunks (key match)")
            else:
                ckpt.unlink()
                print("[corpus-dense] checkpoint key drift -> discarded (no mixed regime)")

        remaining = [c for c in chunk_ids if c not in done]
        print(f"[corpus-dense] {len(chunk_ids)} chunks total, {len(remaining)} to embed "
              f"(backend={config.EMBED_BACKEND}, batch={config.EMBED_BATCH_SIZE})")
        BATCH = config.EMBED_BATCH_SIZE
        for i in range(0, len(remaining), BATCH):
            bids = remaining[i:i + BATCH]
            vecs = embeddings.embed_documents([text_of[c] for c in bids])
            for c, v in zip(bids, vecs):
                done[c] = v
            np.savez(ckpt, key=key,
                     ids=np.array(list(done.keys()), dtype=object),
                     mat=np.stack(list(done.values())).astype(np.float32))
            print(f"[corpus-dense]   {len(done)}/{len(chunk_ids)}", flush=True)

        matrix = np.stack([done[c] for c in chunk_ids]).astype(np.float32)
        assert matrix.shape == (len(chunk_ids), config.EMBED_DIM)

        # parity gate: 827 pilot rows must match pilot_dense.npy
        parity = "skipped (pilot index absent)"
        if Path(config.DENSE_INDEX_PATH).exists():
            pmat = np.load(config.DENSE_INDEX_PATH).astype(np.float32)
            pmeta = json.loads(Path(config.DENSE_INDEX_META_PATH).read_text(encoding="utf-8"))
            pos = {cid: r for r, cid in enumerate(chunk_ids)}
            cos = [float(np.dot(matrix[pos[cid]], pmat[i]))
                   for i, cid in enumerate(pmeta["chunk_ids"]) if cid in pos]
            mn = min(cos) if cos else 0.0
            parity = f"min_cosine={mn:.6f} over {len(cos)} rows ({'PASS' if mn >= 0.9999 else 'FAIL'})"
            if cos and mn < 0.9999:
                raise SystemExit(f"PARITY FAIL ({parity}); refusing to write a mixed regime. "
                                 "Re-embed pilot_dense.npy from this matrix per the W1.7 gate.")

        np.save(config.CORPUS_DENSE_PATH, matrix)
        Path(config.CORPUS_DENSE_META_PATH).write_text(json.dumps({
            "model_id": config.EMBED_MODEL_ID, "dim": config.EMBED_DIM,
            "backend": config.EMBED_BACKEND, "normalize": config.EMBED_NORMALIZE,
            "n_chunks": len(chunk_ids), "build_date": datetime.date.today().isoformat(),
            "chunk_index_sha256": chunk_index_sha, "pilot_parity": parity,
            "chunk_ids": chunk_ids,
        }, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
            encoding=config.OUTPUT_ENCODING)
        ckpt.unlink(missing_ok=True)
        print(f"[corpus-dense] wrote {config.CORPUS_DENSE_PATH.name} {matrix.shape}; parity {parity}")
        return 0
    except SystemExit:
        raise
    except Exception as e:
        for p in out:
            Path(p).unlink(missing_ok=True)
        print(f"[corpus-dense] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
