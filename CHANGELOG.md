# CHANGELOG

## 2026-06-29 — W1.7 GPU path: full-corpus embeddings (one regime, cuda_fp32)

Compute unblocked via the local GTX 1650. Full-corpus embed DONE; STOP before
centroid steps (threshold recalibration reviewed first).

- **Phase 1 (CUDA install):** replaced torch 2.12.1+cpu with **2.5.1+cu121**
  (driver 536.67 → CUDA 12.2 caps at cu121; cu124 would need driver ≥550).
  Asserted +cu121 / cuda available / GTX 1650 / cuda 12.1 / model on cuda:0.
- **Phase 2 (config truth-up):** `EMBED_BACKEND=cuda_fp32`, `EMBED_DEVICE=cuda`,
  `EMBED_BATCH_SIZE=8`. Version block (torch/cuda/cudnn/driver/device) captured
  into the dense meta = the embedding-regime fingerprint.
- **Phase 3 (smoke test):** 64 chunks fp32 batch 8 → **8.3 chunks/s**, peak VRAM
  **1.64 GB** (no OOM; 3.9 GB free), full-corpus projection ~17 min (33× the
  CPU's 9.5 hrs). batch 16 = same speed (GPU-bound).
- **Phase 4 (full embed + one regime):** `build_corpus_dense.py` on cuda embedded
  all 8,887 chunks → `corpus_dense.npy` (8887×1024 f32, unit-norm) + meta. The new
  `pilot_dense.npy` is **sliced** from the full matrix (not re-embedded) →
  **bit-identical** to the corpus subset rows; old CPU file overwritten (backend
  now cuda_fp32). Parity sanity old_cpu vs new_cuda: **min cosine 1.000000** / 827
  rows. Checkpoint keyed on (model, backend, normalize, chunk-index sha, chunk-set
  hash). verify_pin PASS.
- **Bug fixed (not reported benign):** first completion run hit a Windows
  `PermissionError` on the checkpoint unlink (np.load kept the npz handle open /
  AV lock), and the broad except deleted the good outputs. Fixed: close the npz
  via context manager on resume; final cleanup unlink is now best-effort with
  retry and never endangers written outputs. Recovered from the intact checkpoint
  (no re-embed) + git-restored CPU pilot for a valid cpu-vs-cuda sanity.
- 36 MB `corpus_dense.npy` gitignored (regenerable on GPU in ~17 min); meta +
  regenerated `pilot_dense.npy` committed.

STOP per instruction: Steps 1 (threshold recalibration) and 3–5 (centroids,
independence/coverage, tagging) await review of TOPIC_MERGE_COSINE /
TOPIC_ASSIGN_MIN_COSINE before any centroid merge runs.

## 2026-06-29 — W1.7 Step 0 done; Steps 2–5 BLOCKED (compute + topic-set source)

Box 6 (centroid model). Step 0 (embedding fast-path) completed; the full-corpus
embed and centroid regeneration are **blocked** in this environment — reported,
not silently worked around.

- **Step 0 — fast-path assessed, backend chosen, parity PASS.** No GPU (torch is
  +cpu); CPU is an AMD Zen+ APU (AVX2, no AVX-512/VNNI). Throughput is
  compute-bound: threads=8 + batch 32/64 → **0.26–0.27 chunks/s** (= W1.5's
  0.25; tuning gives nothing). int8 was ~0.31/s (W1.5); ONNX absent and ~2× at
  best on this APU with uncertain fp32 parity. **Full 8,887-chunk embed ≈ 9.5 hrs.**
  `EMBED_BACKEND=cpu_fp32` + `EMBED_BATCH_SIZE` recorded in config. Sample parity
  vs `pilot_dense.npy`: **min cosine 1.000000** — the path is numerically faithful,
  so a future GPU run keeps W1.5's index valid (one regime, no re-embed).
- **`scripts/build_corpus_dense.py`** (Step 2 tool, GPU-ready): full-corpus embed
  with a checkpoint keyed on (EMBED_MODEL_ID, EMBED_BACKEND, EMBED_NORMALIZE,
  chunk-index sha256, chunk-set hash) — invalidates on any drift (validated); an
  end-of-run parity gate refuses to write a mixed regime. Config-driven, exits 0,
  no leftovers. Intended for a CUDA box (`CJ_EMBED_BACKEND=cuda_fp32`).
- Config: section 13 (centroid model) — `CORPUS_DENSE_PATH`/meta,
  `CENTROIDS_PATH`/meta, `N_EXEMPLAR_CHUNKS`, `TOPIC_ASSIGN_MIN_COSINE`
  (placeholder; derivation pending the full embed).

**⚠ BLOCKER 1 (compute):** Step 0's "workable embed throughput" hard precondition
is not met here (no GPU; 9.5-hr CPU embed; the run cannot complete under the
10-min foreground cap / background-teardown execution model). Per the brief's
precondition gate → STOP and report.

**⚠ BLOCKER 2 (topic-set source):** Step 3 says build the topic set from the
curated `primary_topics`/`sub_topics`, but those fields are **5,568 / 16,249
distinct free-text per-doc labels** (≈1:1 with docs), not a ~38-topic taxonomy.
A topic set can't be read off them directly — it needs clustering or use of the
35-topic curated taxonomy labels (which the brief says not to start from). Needs
a design decision before Steps 3–5.

## 2026-06-28 — W1.6 Sparse arm (BM25 + curated atomic-phrase dictionary)

Builds box 7 — the exact-identifier complement to the dense arm (statutes, case
names, entities that no embedding reliably matches). Built once over the FULL
corpus chunks; an allowlist filter aligns it 1:1 with W1.5's pilot subset for RRF.

- **Config:** `BM25_K1`(1.5), `BM25_B`(0.75), `SPARSE_TOP_K`(50),
  `CURATED_XLSX_GLOB`, `SPARSE_INDEX_PATH`/`SPARSE_DICT_PATH`/`SPARSE_META_PATH`
  — defaults only (BM25 tuning is W3.3/W3.4).
- **Atomic-phrase dictionary** (`app/sparse.py` tokenizer; `scripts/build_sparse_index.py`):
  34,035 phrases — keyword 9,476, entity 23,250, case 1,309 — NFKC+lowercase,
  entities keep canonical + trailing-parenthetical-stripped variants, `cases`
  verbatim. Shared greedy longest-match tokenizer (first-word index) so a
  multi-word keyword / case name becomes ONE atomic BM25 term with its own IDF.
- **BM25** over all 8,887 chunks (rank_bm25 BM25Okapi, k1/b from config). Pinned
  meta records n_chunks, phrase counts by provenance, k1/b, and sha256 of the
  curated xlsx + chunk index (staleness detectable). Build exits 0, writes
  outputs only on success (full cleanup on error — no partial leftovers), no
  checkpoint scaffolding.
- **sparse_score(query, allowlist, k)** → chunk_ids (mirrors the dense contract).
  allowlist=None ranks full corpus; allowlist=pilot restricts the universe to
  match W1.5's 827-chunk dense subset for RRF.
- **Verify:** verify_pin PASS; tokenization atomic ("rule of law", "morfe v.
  mutuc" → 1 term); complementarity — "RA 10173" sparse #3 vs dense #202,
  "Morfe v. Mutuc" #2 vs #52, "Roe v. Wade" #1 vs #45; allowlist returns only
  subset chunks.
- **⚠ Spec/data inconsistency (flagged, not silently accepted):** the brief said
  "Keyword/s: split on ';'", but the curated field is a JSON array (the form
  W1.3/W1.4 parse). Splitting on ';' fused each doc's keywords into one bogus
  mega-phrase; parsing the list (with a ';' fallback) yields atomic keywords —
  89% multi-word, matching the brief's stated ~91%.
- **deps:** `rank-bm25`.

## 2026-06-28 — W1.5 Embed the pilot subset (runtime dense index)

Builds the runtime dense arm (box 5): embeds ONLY the <100 pilot-subset chunks
(the v4 eval allowlist). Distinct from W1.7 (full-corpus centroids) — both share
the SAME model + dim via config.

- **Config:** added authoritative `EMBED_*` knobs to config.py — `EMBED_MODEL_ID`
  (BAAI/bge-large-en-v1.5), `EMBED_DIM` (1024), `EMBED_DEVICE`, `EMBED_NORMALIZE`,
  `EMBED_QUERY_PREFIX` / `EMBED_DOCUMENT_PREFIX` (bge query/doc asymmetry),
  `DENSE_INDEX_PATH` / `DENSE_INDEX_META_PATH`. The W1.1 `EMBEDDING_MODEL_ID/DIM`
  placeholders are now back-compat aliases of `EMBED_*` (single source; model
  stays swappable — MiniLM-384 / OpenAI text-embedding-3 are W3.4 alternatives).
- **Resident model:** `app/embeddings.py` lazy-loads ONE module-level singleton
  (`get_model`; `model_load_count` proves no per-request reload). `embed_documents`
  (search_document, no prefix) and `embed_query` (search_query, prefixed) hide the
  bge prefix from call sites. `dense_score(query)` ranks by cosine over the
  resident unit-normalised matrix.
- **Index:** `scripts/build_dense_index.py` resolves the v4 allowlist → 827 chunks
  via the W1.4 chunk index, embeds them, and persists a float32 [827,1024]
  unit-normalised matrix (`data/index/pilot_dense.npy`, 3.3 MB) + meta
  (`pilot_dense_meta.json`: model_id, dim, normalize, chunk_ids, doc_ids,
  build_date, n_chunks). The embed loop is checkpointed/resumable (CPU bge-large
  is slow in this env; ~0.25 chunks/s, so the build runs in resumable passes).
- **Verify:** model loads exactly ONCE; matrix (827,1024) float32, mean‖row‖=1.0;
  95/95 allowlist docs resolved, 0 unresolved; meta records bge-large/1024 (=W1.7).
  dense_score spot-checks are on-topic — "rule of law" → CA031 (theme A);
  "AI governed in courts" → CA034 "AI in justice and governance"; "FLP
  scholarships" → FLP book chapters + CD003.
- **deps:** activated `sentence-transformers` in app/requirements.txt.

## 2026-06-27 — W1.4 Corpus prep + full-corpus chunking + verifiable pin

Branch `feat/full-corpus-chunk` (off `pilot/freeze-subset-v3`). Architecture:
chunk the FULL ~1,089-doc corpus once; the pilot subset is an eval-time
allowlist applied later (W1.5/W3), NOT the chunking input.

**Precondition:** all four `data/csv/*_curated_normalized.xlsx` load (utf-8-sig
content). Row counts: Column 785, Book 115, Speech 154, Biography 35 =
**1,089 total**. The "1,059" figure remains unsupported by the files; the real
count read is **1,089**. Biography xlsx has 14 columns (no `Link`) vs 15 for the
others — benign schema variance, flagged.

**Step 1 — regenerate corpus from xlsx (script repoint):** added
`scripts/generate_corpus_from_xlsx.py` (a fork; the old
`generate_corpus_files.py` and its CSV inputs are left intact). It reads the four
xlsx and writes the full `corpus/{columns,books,speeches,biography}/{theme}/`
tree — 1,089 paired `.md`+`.json`. doc_id = padded `^[CGBS][A-E]\d{3}$`. `.md`
carries frontmatter + `# Title` + the article body (merged from
`data/text/<id>.md` when present — 1,055 docs; the other 34 fall back to the
curated `one_paragraph_summary`, flagged) + `## Summary` + a `## Notable
Anecdotes` section (each anecdote under its own `###` so the chunker keeps them
whole). `.json` holds the full curated record; **`entities` preserved as a JSON
object**, never flattened. utf-8-sig reads, ensure_ascii=False writes. The legacy
80-doc tree was **moved aside** to `corpus/_legacy_phase1/` (not deleted).

**Step 2 — verifiable pin:** the four xlsx are now **tracked in git** (<4 MB).
`scripts/build_corpus_snapshot.py` writes `corpus_snapshot.json` (committed):
per-file `{sha256,bytes,sheet,row_count}` + per-doc `row_sha256` (sha256 of the
canonical key-sorted serialization of the 15 curated fields) + header
(producer/date/source). `scripts/verify_pin.py` recomputes both levels and
**exits nonzero on any drift** (proven: tampering one row hash → exit 1; intact →
exit 0).

**Step 3 — heading-aware chunking + doc store:** added chunk knobs to
`config.py` (`CHUNK_TARGET_TOKENS_MIN/MAX` 200/400, `CHUNK_OVERLAP_TOKENS` 40,
`CHUNK_HEADING_AWARE`, `CHUNK_KEEP_ANECDOTES_WHOLE`, `DOC_ID_REGEX_PADDED`) —
the chunker reads all knobs from config, no literals. `scripts/chunk_corpus.py`
splits each `.md` on headings, packs prose to the band (paragraph/sentence split
with overlap for over-band sections), and keeps anecdotes whole (consecutive
short anecdotes packed together, never split mid-anecdote). Outputs the doc
store `corpus/index/chunks.jsonl` (chunk_id → doc_id + metadata + text) and
`corpus/index/chunk_index.json` (stats + `by_doc` + source-snapshot ref).

**Step 4 — verify:** 1,089 docs → **8,887 chunks**, avg **311.6** tokens (78% in
200–400 band; 24 chunks <50). Boundaries + anecdotes spot-checked across all
formats (CA034 column, CB001, SE012 speech, GC001 biography, BA009 book) — prose
in-band, anecdotes intact. **All 95 v3 pilot doc_ids resolve to chunks** (the
missing-89 problem is gone; 0 missing). `verify_pin` → PASS.

## [pilot-baseline] — 2026-06-25 — W1.1 Stabilise codebase + unified config.py

A **code/config baseline** taken BEFORE the W1.7 topic-map rebuild and the
W1.4–W1.6 index builds. Branch: `pilot/stabilise-config` (off
`weekly-plan-execution` @ `07a8b8d`, the reconciled pre-wake-word baseline).
See [BRANCHES.md](BRANCHES.md) for the full branch audit.

### Consolidated

- **No branch merge / cherry-pick was performed, and therefore there were no
  merge conflicts to resolve.** The only branches diverging from the chosen
  base (`origin/main`, `origin/integration/hands-free-wake`) carry exclusively
  the **wake-word re-integration track**, which is deferred for the May-30 demo
  (ADR-0005; reconciled 2026-06-21 handover). Pulling them would drag a deferred
  feature into the pilot baseline, so none of their work "belongs in the pilot."
  The chosen base was taken as-is.
- The brief's instruction to "resolve each conflict toward the LOCKED NEW
  architecture" was **inapplicable**: no branch in the tree contains any
  competing retrieval/centroid/RRF code to conflict with. The new architecture
  exists only as the config surface added here (see below).

### Added — `config.py` (single source of truth, repo root)

One import (`import config`) now surfaces **46 knobs**, grouped + commented,
each with a one-line trade-off note and an env-var override (precedence:
env var > default-in-file). W3.3 sweeps **this file** (or the matching env
var); it never edits code. Verified: `python config.py` dumps every knob.

Knobs centralised, by group:

- **Retrieval cutoff** `[NEW-ARCH]`: `TAU` (keep chunk if score ≥ TAU·top_score),
  `MIN_K`, `MAX_K`.
- **Fusion** `[NEW-ARCH]`: `RRF_K` (reciprocal-rank-fusion constant),
  `LAMBDA` (topic-affinity weight: `score = passage_sim + LAMBDA·topic_affinity`).
- **Routing / scope**: `OUT_OF_SCOPE_THRESHOLD`, `TOPIC_SOFTMAX_TEMPERATURE`.
- **Topic model** `[NEW-ARCH, drives W1.7 regen]`: `TOPIC_MAP_PATH`,
  `TOPIC_MAP_VERSION`, `TOPIC_MERGE_COSINE` (independence check, default **0.85**),
  `MAX_TOPIC_TAGS` (clamped 1–3), `CENTROID_SOURCE_FIELDS`
  (`label/description/signature_phrases/exemplar_chunks`). Also the
  baseline-consumed `TOPIC_PRIMARY_N`, `TOPIC_SECONDARY_N`, and the matcher-health
  thresholds `TOPIC_OVER_BROAD_FRAC` / `TOPIC_NEAR_DUP_JACCARD` /
  `TOPIC_DOMINANT_TERM_FRAC`.
- **Composition**: `MAX_TOKENS`, `COMPOSER_TIMEOUT_S`, `MAX_RETRIES`,
  `FIDELITY_MAX_RETRIES`, `EXPAND_ON_DEMAND_FIRE_RATE_GATE` (~0.10) `[NEW-ARCH]`,
  `CONTEXT_TOKEN_BUDGET`, `CHARS_PER_TOKEN_APPROX`, `MAX_SOURCE_DOCS`.
- **Models**: `EMBEDDING_MODEL_ID` (all-MiniLM-L6-v2) `[NEW-ARCH]`,
  `EMBEDDING_DIM` (384) `[NEW-ARCH]`, `COMPOSER_MODEL_ID` (claude-sonnet-4-6),
  `ROUTER_MODEL_ID` (claude-haiku-4-5-20251001), `WHISPER_MODEL_SIZE`,
  `OPENAI_STT_MODEL` / `OPENAI_TTS_MODEL` / `OPENAI_TTS_VOICE` / `OPENAI_TTS_SPEED`.
- **Encoding** `[CONVENTION]`: `FILE_ENCODING` (utf-8-sig, reads),
  `OUTPUT_ENCODING` (utf-8, writes), `JSON_ENSURE_ASCII` (False).
- **Audio** `[BASELINE]`: `SAMPLE_RATE`, `RECORD_SECONDS_MAX`,
  `SILENCE_RMS_THRESHOLD`, `TRAILING_SILENCE_MS`, `TTS_SENTENCE_SILENCE`,
  `TTS_LENGTH_SCALE`.
- **Data conventions** `[CONVENTION]`: `CURATED_SCHEMA_COLUMNS` (15),
  `DOC_ID_REGEX` (`^[SCGB][A-E]\d+$`).

### Moved from code → config (literals replaced with config reads)

- **`app/cj_chat.py`**: `ROUTER_MODEL`→`config.ROUTER_MODEL_ID`,
  `INFERENCE_MODEL`→`config.COMPOSER_MODEL_ID`, `WHISPER_MODEL_SIZE`,
  `SAMPLE_RATE`, `RECORD_SECONDS_MAX`, `ANTHROPIC_MAX_RETRIES`→`config.MAX_RETRIES`,
  `CONTEXT_TOKEN_BUDGET`, `_CHARS_PER_TOKEN_APPROX`, the `max_docs=3`
  defaults→`config.MAX_SOURCE_DOCS`, both composer `max_tokens=300`→`config.MAX_TOKENS`,
  the fidelity `max_retries=1`→`config.FIDELITY_MAX_RETRIES`,
  `TTS_SENTENCE_SILENCE` / `TTS_LENGTH_SCALE`, and the recorder's
  `silence_rms_threshold` / `trailing_silence_ms`.
- **`scripts/build_topic_map.py`**: `schema_version "2.0"`→`config.TOPIC_MAP_VERSION`,
  `derive_topic_paths` `primary_n/secondary_n`→`config.TOPIC_PRIMARY_N/SECONDARY_N`,
  `matcher_health_check` thresholds→config, and all read/write encodings →
  `config.FILE_ENCODING` (reads) / `config.OUTPUT_ENCODING` +
  `config.JSON_ENSURE_ASCII` (writes).
- **`app/voice_io.py`**: `STT_MODEL_DEFAULT`, `TTS_MODEL_DEFAULT`,
  `TTS_VOICE_DEFAULT`, `TTS_SPEED_DEFAULT` → config.

Each file imports the repo-root `config.py` via a small `sys.path` bootstrap so
it works whether run from repo root, `app/`, or `scripts/`. Every previous
env-var override name (`ROUTER_MODEL`, `INFERENCE_MODEL`, `WHISPER_MODEL`,
`OPENAI_TTS_VOICE`, …) is preserved — `config.py` reads those same names, so
existing `.env` files keep working unchanged.

### Conventions preserved

- **utf-8-sig** read encoding / **ensure_ascii=False** JSON writes — now named
  constants in `config.py` and wired through `build_topic_map.py`.
- **15-column curated schema** — surfaced as `CURATED_SCHEMA_COLUMNS`.
- **ID regex** — surfaced as `DOC_ID_REGEX = ^[SCGB][A-E]\d+$`. ⚠ See flag below:
  the brief's regex adds **`B`** (book corpus, PLAN-0005). The shipping runtime
  (`cj_chat._DOC_ID_RE`) still recognises only **S/C/G** because no `B` docs or
  `corpus/books/` tree exist yet; `B` is reserved in config for when books land.
  Left runtime regex unchanged (changing it now would be a fix outside W1.1
  scope with no docs to validate against).

### Requirements

`app/requirements.txt` updated for honesty against actual imports: added (as
commented/optional) the lazily-imported voice-mode deps `faster-whisper` +
`sounddevice` used by the CLI push-to-talk path, and a commented
`sentence-transformers` line for the W1.4+ MiniLM embedding engine (left out of
the default install so the baseline stays light). Existing `>=` floors kept; no
exact re-pin (would risk destabilising the validated baseline).

### Regression (existing build only — NOT the pilot pipeline)

Offline (no API key required) — all green:

1. `python config.py` → 46 knobs dump cleanly from one import.
2. `import cj_chat` clean; asserts confirm `ROUTER_MODEL`, `INFERENCE_MODEL`,
   `CONTEXT_TOKEN_BUDGET` now read from `config`. 35 topics load;
   `build_context()` assembles a ~7.6k-token grounded block.
3. `python scripts/build_topic_map.py` → 79 docs → 35 topics, 0 unmatched;
   output **content-identical** to the committed map (only `generated_at`
   timestamp differs). Regenerated files were reverted to keep the stale map
   intact for W1.7.

Live (`python app/cj_chat.py --text "What is the rule of law?"`, key supplied
via `app/.env`): **PASS, end-to-end.** Gate → `in_corpus`; router →
`primary=rule_of_law`, `secondary=[constitutional_doctrine, due_process]`,
`confidence=high`; Sonnet composed a grounded in-voice answer (212 output
tokens; prompt-cache write 4,411 tok on the voice card). Confirms the full
Haiku-router → Sonnet-composer path runs through `config.py`. (Full pilot e2e
— the new retrieval engine — remains deferred to a post-W1.8 checkpoint per the
brief; this is the baseline pipeline only.)

### ⚠ Retrieval-quality caveat (read before trusting routing)

The on-disk `corpus/voice/topic_map.json` is **STALE under the locked new
architecture** and was **not** re-tuned here. The current map is built by
lexical keyword matchers, not centroids; its own health check already flags
**32 taxonomy warnings** (8 over-broad topics, 8 near-duplicate pairs — e.g.
`msme_and_entrepreneurship`↔`museum_for_liberty_and_prosperity` at Jaccard 0.91,
`twin_beacons_doctrine`↔`foundation_for_liberty_and_prosperity` at 0.86, both
above the `TOPIC_MERGE_COSINE` 0.85 independence bar). **Retrieval quality is
expected to change once W1.7 rebuilds the centroids.** Do not treat current
routing behaviour as validated.

### ⚠ Inconsistencies flagged (not silently fixed)

1. **`feat/topic-map-coverage` does not exist** — the brief's suggested
   candidate base is absent from local, `origin`, and the reflog. Base chosen on
   evidence instead (BRANCHES.md).
2. **Architecture gap** — the brief's "LOCKED NEW architecture" (centroids,
   numpy retrieval, RRF) is **not implemented anywhere** in the tree; the live
   pipeline is the documented Haiku-router → Sonnet-composer baseline. W1.1
   lands only the config surface for the new architecture, not the engine.
3. **DOC_ID regex `B`** — see "Conventions preserved" above.
