"""
W1.4 Step 3 — heading-aware chunking of the FULL regenerated corpus, and the
doc store + chunk index.

Reads every corpus/{columns,books,speeches,biography}/**/*.md (+ paired .json),
splits each on markdown headings, and packs sections into ~CHUNK_TARGET band
chunks (config.py). Anecdote sections (under "## Notable Anecdotes") are kept
whole. Over-band prose sections are split on paragraph/sentence boundaries with
a small overlap. ALL knobs come from config.py — no literals here.

Outputs (committed, stable across pilot-subset re-freezes):
  corpus/index/chunks.jsonl     - the doc store: one chunk per line, with text +
                                  metadata (chunk_id -> doc_id, heading, anecdote
                                  flag, token estimate, ...).
  corpus/index/chunk_index.json - {stats, by_doc: doc_id -> [chunk_ids],
                                  source_snapshot} for fast lookup + coverage.

Usage:
    python scripts/chunk_corpus.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import config

CORPUS_ROOT = PROJECT_ROOT / "corpus"
INDEX_DIR = CORPUS_ROOT / "index"
TYPE_FOLDERS = ["columns", "books", "speeches", "biography"]
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def est_tokens(text: str) -> int:
    return max(1, len(text) // config.CHARS_PER_TOKEN_APPROX)


def parse_blocks(md: str) -> list[dict]:
    """Split markdown into heading-delimited blocks. Each heading line starts a
    new block; returns [{level, heading, body, region}] where region marks
    anecdote sections so they can be kept whole."""
    md = FRONTMATTER_RE.sub("", md, count=1)
    blocks: list[dict] = []
    cur = {"level": 0, "heading": "", "body": []}
    region = "body"
    for line in md.splitlines():
        m = HEADING_RE.match(line)
        if m:
            if cur["heading"] or cur["body"]:
                blocks.append(cur)
            level = len(m.group(1))
            heading = m.group(2).strip()
            # track whether we are inside the Notable Anecdotes section
            if level <= 2:
                region = "anecdotes" if heading.lower().startswith("notable anecdotes") else "body"
            cur = {"level": level, "heading": heading, "body": [], "region": region}
        else:
            cur["body"].append(line)
    if cur["heading"] or cur["body"]:
        blocks.append(cur)
    for b in blocks:
        b["text"] = "\n".join(b["body"]).strip()
        b["is_anecdote"] = (b.get("region") == "anecdotes" and b["level"] >= 3)
        b.setdefault("region", region)
    return blocks


def split_long(text: str) -> list[str]:
    """Split an over-band prose block on paragraph then sentence boundaries,
    packing to CHUNK_TARGET_TOKENS_MAX with CHUNK_OVERLAP_TOKENS overlap."""
    max_chars = config.CHUNK_TARGET_TOKENS_MAX * config.CHARS_PER_TOKEN_APPROX
    overlap_chars = config.CHUNK_OVERLAP_TOKENS * config.CHARS_PER_TOKEN_APPROX
    units = [u for u in text.split("\n") if u.strip()]
    fine: list[str] = []
    for u in units:                       # break any single over-long paragraph
        if len(u) <= max_chars:
            fine.append(u)
        else:
            fine.extend(s for s in re.split(r"(?<=[.!?])\s+", u) if s.strip())
    out: list[str] = []
    buf = ""
    for u in fine:
        if buf and len(buf) + 1 + len(u) > max_chars:
            out.append(buf.strip())
            tail = buf[-overlap_chars:] if overlap_chars else ""
            buf = (tail + " " + u).strip() if tail else u
        else:
            buf = (buf + "\n" + u).strip() if buf else u
    if buf.strip():
        out.append(buf.strip())
    return out


def chunk_doc(doc_id: str, meta: dict, md: str) -> list[dict]:
    blocks = parse_blocks(md)
    min_chars = config.CHUNK_TARGET_TOKENS_MIN * config.CHARS_PER_TOKEN_APPROX
    max_chars = config.CHUNK_TARGET_TOKENS_MAX * config.CHARS_PER_TOKEN_APPROX
    pieces: list[dict] = []            # {heading, text, is_anecdote}
    buf_text, buf_head = "", None
    anec_buf: list[str] = []           # consecutive whole anecdotes, packed

    def flush():
        nonlocal buf_text, buf_head
        if buf_text.strip():
            pieces.append({"heading": buf_head or "", "text": buf_text.strip(),
                           "is_anecdote": False})
        buf_text, buf_head = "", None

    def flush_anec():
        nonlocal anec_buf
        if anec_buf:
            pieces.append({"heading": "Notable Anecdotes",
                           "text": "\n\n".join(anec_buf).strip(), "is_anecdote": True})
            anec_buf = []

    for b in blocks:
        if not b["text"].strip():
            continue  # skip heading-only structural blocks (e.g. bare "Notable Anecdotes")
        seg = (f"{b['heading']}\n\n{b['text']}".strip() if b["heading"] else b["text"]).strip()
        # ----- anecdotes: pack consecutive ones whole, never split one -----
        if config.CHUNK_KEEP_ANECDOTES_WHOLE and b["is_anecdote"]:
            flush()
            cur = sum(len(a) + 2 for a in anec_buf)
            if anec_buf and cur + len(seg) > max_chars:
                flush_anec()
            if len(seg) > max_chars and not anec_buf:
                pieces.append({"heading": b["heading"], "text": seg, "is_anecdote": True})
                continue
            anec_buf.append(seg)
            continue
        flush_anec()  # left the anecdote region
        # ----- over-band prose: split on paragraph/sentence with overlap -----
        if est_tokens(seg) * config.CHARS_PER_TOKEN_APPROX > max_chars and config.CHUNK_HEADING_AWARE:
            flush()
            subs = split_long(b["text"])
            for i, s in enumerate(subs):
                head = b["heading"] if i == 0 else f"{b['heading']} (cont.)"
                txt = f"{head}\n\n{s}".strip() if b["heading"] else s
                pieces.append({"heading": b["heading"], "text": txt, "is_anecdote": False})
            continue
        # ----- greedy pack prose into the band -----
        if buf_text and len(buf_text) + 2 + len(seg) > max_chars:
            flush()
        buf_text = (buf_text + "\n\n" + seg).strip() if buf_text else seg
        buf_head = buf_head or b["heading"]
        if len(buf_text) >= min_chars:
            flush()
    flush()
    flush_anec()

    chunks = []
    for i, p in enumerate(pieces):
        chunks.append({
            "chunk_id": f"{doc_id}::c{i:03d}",
            "doc_id": doc_id,
            "format": meta.get("format"),
            "theme": meta.get("theme"),
            "theme_label": meta.get("theme_label"),
            "title": meta.get("title"),
            "heading": p["heading"],
            "ordinal": i,
            "is_anecdote": p["is_anecdote"],
            "char_len": len(p["text"]),
            "n_tokens_est": est_tokens(p["text"]),
            "text": p["text"],
        })
    return chunks


def main() -> int:
    md_paths = []
    for tf in TYPE_FOLDERS:
        md_paths.extend(sorted((CORPUS_ROOT / tf).rglob("*.md")))
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    all_chunks: list[dict] = []
    by_doc: dict[str, list[str]] = {}
    anec_docs = 0
    for p in md_paths:
        doc_id = p.stem
        meta = json.loads((p.with_suffix(".json")).read_text(encoding=config.FILE_ENCODING))
        md = p.read_text(encoding=config.FILE_ENCODING)
        chunks = chunk_doc(doc_id, meta, md)
        if not chunks:   # guarantee every doc resolves to >=1 chunk
            chunks = [{
                "chunk_id": f"{doc_id}::c000", "doc_id": doc_id,
                "format": meta.get("format"), "theme": meta.get("theme"),
                "theme_label": meta.get("theme_label"), "title": meta.get("title"),
                "heading": meta.get("title"), "ordinal": 0, "is_anecdote": False,
                "char_len": 0, "n_tokens_est": 1, "text": (meta.get("title") or doc_id)}]
        if any(c["is_anecdote"] for c in chunks):
            anec_docs += 1
        all_chunks.extend(chunks)
        by_doc[doc_id] = [c["chunk_id"] for c in chunks]

    # write doc store (jsonl)
    with open(INDEX_DIR / "chunks.jsonl", "w", encoding=config.OUTPUT_ENCODING, newline="\n") as fh:
        for c in all_chunks:
            fh.write(json.dumps(c, ensure_ascii=config.JSON_ENSURE_ASCII) + "\n")

    toks = [c["n_tokens_est"] for c in all_chunks]
    anec_chunks = sum(1 for c in all_chunks if c["is_anecdote"])
    snap = json.loads((PROJECT_ROOT / "corpus_snapshot.json").read_text(encoding="utf-8")) \
        if (PROJECT_ROOT / "corpus_snapshot.json").exists() else {}
    stats = {
        "n_docs": len(by_doc),
        "n_chunks": len(all_chunks),
        "avg_tokens": round(sum(toks) / len(toks), 1) if toks else 0,
        "min_tokens": min(toks) if toks else 0,
        "max_tokens": max(toks) if toks else 0,
        "anecdote_chunks": anec_chunks,
        "docs_with_anecdotes": anec_docs,
        "chunk_band": [config.CHUNK_TARGET_TOKENS_MIN, config.CHUNK_TARGET_TOKENS_MAX],
        "overlap_tokens": config.CHUNK_OVERLAP_TOKENS,
    }
    index = {
        "stats": stats,
        "source_snapshot": {
            "doc_id_count": snap.get("header", {}).get("doc_id_count"),
            "source_files": [{"filename": s["filename"], "sha256": s["sha256"]}
                             for s in snap.get("source_files", [])],
        },
        "by_doc": by_doc,
    }
    (INDEX_DIR / "chunk_index.json").write_text(
        json.dumps(index, ensure_ascii=config.JSON_ENSURE_ASCII, indent=2) + "\n",
        encoding=config.OUTPUT_ENCODING)

    print(f"[chunk] docs={stats['n_docs']} chunks={stats['n_chunks']} "
          f"avg_tok={stats['avg_tokens']} (min {stats['min_tokens']}, max {stats['max_tokens']})")
    print(f"[chunk] anecdote chunks={anec_chunks} across {anec_docs} docs; "
          f"band={stats['chunk_band']} overlap={stats['overlap_tokens']}")
    print(f"[chunk] wrote {INDEX_DIR/'chunks.jsonl'} + {INDEX_DIR/'chunk_index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
