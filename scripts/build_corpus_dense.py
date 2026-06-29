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


def _safe_unlink(path: Path) -> bool:
    """Best-effort delete; tolerates a transient Windows lock (np handle / AV
    scan). Returns True if gone. Never raises — a leftover checkpoint must not
    nuke good outputs."""
    import time
    for _ in range(5):
        try:
            Path(path).unlink(missing_ok=True)
            return True
        except OSError:
            time.sleep(0.5)
    return not Path(path).exists()


def _version_block() -> dict:
    """Capture the embedding regime's version fingerprint (recorded in meta)."""
    import subprocess
    block = {"backend": config.EMBED_BACKEND}
    try:
        import torch
        block["torch"] = torch.__version__
        block["torch_cuda"] = torch.version.cuda
        block["cudnn"] = torch.backends.cudnn.version() if torch.cuda.is_available() else None
        block["device_name"] = (torch.cuda.get_device_name(0)
                                if torch.cuda.is_available() else "cpu")
    except Exception as e:
        block["torch_error"] = str(e)
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=driver_version",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
        block["driver"] = out.stdout.strip() or None
    except Exception:
        block["driver"] = None
    return block


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
            with np.load(ckpt, allow_pickle=True) as z:   # close handle (Win lock)
                same = str(z["key"]) == key
                if same:
                    ids = z["ids"].tolist()
                    mat = np.asarray(z["mat"], dtype=np.float32)
            if same:
                for cid, row in zip(ids, mat):
                    done[cid] = row
                print(f"[corpus-dense] resume: {len(done)} chunks (key match)")
            else:
                _safe_unlink(ckpt)
                print("[corpus-dense] checkpoint key drift -> discarded (no mixed regime)")

        remaining = [c for c in chunk_ids if c not in done]
        print(f"[corpus-dense] {len(chunk_ids)} chunks total, {len(remaining)} to embed "
              f"(backend={config.EMBED_BACKEND}, batch={config.EMBED_BATCH_SIZE})")
        BATCH = config.EMBED_BATCH_SIZE
        CKPT_EVERY = 512   # checkpoint roughly every 512 chunks (not every batch —
                           # rewriting the growing matrix per-batch is O(n^2) I/O)
        since_ckpt = 0

        def _save_ckpt():
            np.savez(ckpt, key=key,
                     ids=np.array(list(done.keys()), dtype=object),
                     mat=np.stack(list(done.values())).astype(np.float32))

        for i in range(0, len(remaining), BATCH):
            bids = remaining[i:i + BATCH]
            vecs = embeddings.embed_documents([text_of[c] for c in bids])
            for c, v in zip(bids, vecs):
                done[c] = v
            since_ckpt += len(bids)
            if since_ckpt >= CKPT_EVERY:
                _save_ckpt(); since_ckpt = 0
                print(f"[corpus-dense]   {len(done)}/{len(chunk_ids)}", flush=True)
        if since_ckpt:
            _save_ckpt()

        matrix = np.stack([done[c] for c in chunk_ids]).astype(np.float32)
        assert matrix.shape == (len(chunk_ids), config.EMBED_DIM)
        pos = {cid: r for r, cid in enumerate(chunk_ids)}

        # --- Phase 4 one-regime: derive the new pilot_dense by SLICING the full
        #     matrix (NOT re-embedding the subset separately), so subset and full
        #     corpus are bit-identical (both cuda_fp32). Sanity-compare to the OLD
        #     cpu pilot (expect >=0.9999; cpu vs cuda differ only in float
        #     reduction order). Compute BEFORE writing so a failure leaves nothing.
        sanity = "skipped (no prior pilot index)"
        new_pilot = None
        pmeta = None
        if Path(config.DENSE_INDEX_PATH).exists():
            old_pmat = np.load(config.DENSE_INDEX_PATH).astype(np.float32)
            pmeta = json.loads(Path(config.DENSE_INDEX_META_PATH).read_text(encoding="utf-8"))
            sub_ids = pmeta["chunk_ids"]
            miss = [c for c in sub_ids if c not in pos]
            if miss:
                raise RuntimeError(f"{len(miss)} pilot chunks absent from corpus matrix: {miss[:5]}")
            new_pilot = np.stack([matrix[pos[c]] for c in sub_ids]).astype(np.float32)
            cos = [float(np.dot(new_pilot[i], old_pmat[i])) for i in range(len(sub_ids))]
            mn = min(cos)
            sanity = f"min_cosine(old_cpu vs new_cuda)={mn:.6f} over {len(cos)} rows"
            if mn < 0.999:
                raise SystemExit(f"PARITY SANITY FAIL ({sanity}); materially below 0.9999 -> "
                                 "normalization/ordering bug, not float drift. STOP.")

        # --- write full-corpus matrix + meta ---
        np.save(config.CORPUS_DENSE_PATH, matrix)
        Path(config.CORPUS_DENSE_META_PATH).write_text(json.dumps({
            "model_id": config.EMBED_MODEL_ID, "dim": config.EMBED_DIM,
            "backend": config.EMBED_BACKEND, "normalize": config.EMBED_NORMALIZE,
            "batch_size": config.EMBED_BATCH_SIZE,
            "version_block": _version_block(),
            "n_chunks": len(chunk_ids), "build_date": datetime.date.today().isoformat(),
            "chunk_index_sha256": chunk_index_sha, "pilot_parity_sanity": sanity,
            "chunk_ids": chunk_ids,
        }, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
            encoding=config.OUTPUT_ENCODING)

        # --- overwrite pilot_dense + meta from the slice (backend now cuda_fp32) ---
        if new_pilot is not None:
            np.save(config.DENSE_INDEX_PATH, new_pilot)
            pmeta["backend"] = config.EMBED_BACKEND
            pmeta["build_date"] = datetime.date.today().isoformat()
            pmeta["derived_from"] = "corpus_dense.npy slice (W1.7 Phase 4 — one regime)"
            Path(config.DENSE_INDEX_META_PATH).write_text(
                json.dumps(pmeta, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
                encoding=config.OUTPUT_ENCODING)

        # best-effort checkpoint cleanup — non-fatal, must not endanger the
        # already-written outputs if a transient lock holds the file.
        if not _safe_unlink(ckpt):
            print(f"[corpus-dense] WARN: could not remove {ckpt.name} (locked); "
                  "outputs are complete — delete it manually.", file=sys.stderr)
        print(f"[corpus-dense] wrote {config.CORPUS_DENSE_PATH.name} {matrix.shape}; "
              f"pilot sliced+overwritten; {sanity}")
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
