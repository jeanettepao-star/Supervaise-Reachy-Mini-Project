# Engineering Handover — CJP Retrieval Pipeline (`develop`)
### Embeddings-based retrieval architecture · baseline **arch-baseline-v4.2**

**Prepared:** 2026-07-18 (against branch `develop` @ `9ef1f5c` = `arch-baseline-v4.2`)
**Repo:** https://github.com/jeanettepao-star/Supervaise-Reachy-Mini-Project
**Local clone:** `C:\Reachy Mini Project 2026`
**Prepared for:** the next Claude Code / LLM agent working the retrieval pipeline

---

## 0. READ FIRST — which architecture this doc covers

This project has **two distinct lines of work on different branches**, and they use
**different retrieval architectures**. Do not conflate them.

| Branch | Surface | Retrieval | Documented in |
|---|---|---|---|
| `pre-wake-word-integration` | push-to-talk voice **kiosk** (`app/app.py`) | **NO embeddings** — Haiku router over a hand-curated 35-topic taxonomy | [handover 2026-06-21](handover_claude_code_2026-06-21.md) |
| **`develop` (this doc)** | **retrieval pipeline** (`app/retrieval.py` + `service.py`) | **bge-base embeddings + BM25, RRF-fused, soft-prior centroids, top-p cutoff** | **this doc** |

The 2026-06-21 handover and `CLAUDE.md`'s "Not RAG / no embeddings" line describe the
**kiosk branch**, which is correct *for that branch*. This doc is the source of truth for
the **`develop` retrieval architecture**, which is an embeddings system (the "NEW-ARCH"
W1.5–W1.8 work referenced throughout the code). If you are on `develop`, ignore the
"no embeddings" framing — the code you're running is `app/embeddings.py` (resident
bge-base) + `app/sparse.py` (BM25) + `app/retrieval.py` (RRF + centroids + nucleus).

---

## 1. CURRENT BASELINE — arch-baseline-v4.2

**Tag `arch-baseline-v4.2` = `9ef1f5c`** (annotated, 2026-07-18) — the OPS-2 full-corpus
promotion. First fully-reproducible OPS-2 state: promoted artifacts + the pyarrow pin that
makes them loadable + the gate-closure provenance, all in one commit.

- **Canonical retrieval recall** (v4 gold, N=34, scope-aware, retrieval-only): **recall@1 / @5 / @chunks-sent / @10 = 0.588 / 0.882 / 0.941 / 0.971**. Fabrication 0/40 (last measured composer eval). The @1 is −2.9pt vs the pre-batch-02 0.618 — the **accepted B11 batch-02 BM25/IDF cost** (attribution machine-verified clean; OPS-2 dense+centroids add zero drift).
- **Gate closures recorded** (Dev0-attested, 2026-07-18): Dok OPS-2 ratification · Sheena 29-doc ack · B11 acceptance → [eval/results/arch_baseline_v4_2_provenance.json](../eval/results/arch_baseline_v4_2_provenance.json).
- **Live-path health gate:** 3/3 anchors pass (retrieval-only).

### Tag lineage (all annotated)
| Tag | Commit | Meaning |
|---|---|---|
| arch-baseline | caa3c8c | first new-arch e2e on the frozen query set |
| arch-baseline-v2 | 704c8a6 | top-p nucleus re-baseline (MIN_K=4) |
| arch-baseline-v3 | fe75a3a | feature-complete (date-index + expand-on-demand, dark) |
| arch-baseline-v4 | 553483c | **bge-base embedder transition** (was bge-large; Dok-ratified) |
| **arch-baseline-v4.2** | **9ef1f5c** | **OPS-2 full-corpus promotion (current)** |
| arch-baseline-v4.1 | — | **RESERVED / uncreated** — W3.7 OOS-calibration close |

---

## 2. ARCHITECTURE (the `develop` retrieval path)

```
query
 → input_gate (local, zero-LLM: empty / identity_probe / in_corpus)
 → embed_query  (resident bge-base-en-v1.5, 768d, GPU)         [app/embeddings.py]
 → route        (soft prior: cosine vs 34 centroids → softmax relevance;
                 OUT_OF_SCOPE_THRESHOLD BIASES, never gates)   [app/retrieval.py:route]
 → retrieve     (dense pilot 827 + BM25 over SAME docs → RRF (K=60) fuse;
                 score = passage_sim + LAMBDA·topic_affinity;
                 top-p NUCLEUS cutoff over softmax_temp basis, floor MIN_K)
      · DARK branches (all default OFF): date-index filter, entity-rescue
 → build_payload (top-k chunks + lean directives)              [app/service.py]
 → compose_streamed (Sonnet 4.6: streamed prose + ---ENVELOPE--- sentinel + JSON meta;
                     OOS graceful decline)                     [app/service.py]
 → voice (streaming sentence-chunk → TTS; see voice apps)
```

**Retrieval knobs (v4.2 pins, `config.py`):** `EMBED_MODEL_ID=BAAI/bge-base-en-v1.5`,
`EMBED_DIM=768`, `RRF_K=60`, `LAMBDA=0.25`, `RETRIEVAL_TOP_P=0.95`, `RETRIEVAL_MIN_K=4`,
`RETRIEVAL_TOP_P_BASIS=softmax_temp`, `RETRIEVAL_SOFTMAX_TEMP=0.06`,
`OUT_OF_SCOPE_THRESHOLD=0.15` (proven inert — composer-decline owns OOS),
`COMPOSER_TOP_K=12`, `COMPOSER_MAX_TOKENS=480` (lowered 640→480 with the W3.3-LITE
concise-length directive, 2026-07-18), composer = `claude-sonnet-4-6`.

**Corpus / index:** 1,109 docs / **9,865 chunks** (`corpus/index/chunks.jsonl`);
`data/index/corpus_dense.npy` (9865, 768) bge-base; `topic_centroids.npy` (34, 768)
full-corpus member-mean; **frozen pilot** = 95 docs / **827 chunks**
(`pilot_dense.npy`, `pilot_sparse.pkl`). Config is single-source-of-truth; all paths swappable.

**DARK features (shipped, default OFF — flip to promote, each verified independently):**
`DATE_INDEX_ENABLED` (temporal filter), `EXPAND_ON_DEMAND_ENABLED` (compose-side retry),
`ENTITY_RESCUE_ENABLED` (guarantees a distinctive curated-entity exact match reaches the
composer; distinctiveness bar `ENTITY_RESCUE_MAX_DOC_FREQ=25`; see
[entity_rescue_report.md](../eval/results/entity_rescue_report.md)).

---

## 3. ENVIRONMENT GOTCHAS (will bite you)

1. **`pyarrow==21.0.0` is PINNED** (`app/requirements.txt`). pyarrow 24's `arrow.dll`
   access-violates (exit 139) when imported after torch 2.5.1 — it killed every bare
   `sentence_transformers` import. Do NOT upgrade without re-running the bare-import probe
   on cpu+cuda. Evidence: [eval/results/postreboot/probe_report.json](../eval/results/postreboot/probe_report.json).
2. **BERT init guard** in `app/embeddings.py` (`_apply_bert_init_guard`) — retained
   defense-in-depth for the same class of Windows access-violation at model load.
3. **Transport flapping (Avast).** Native Python TLS breaks under Avast's HTTPS scanning;
   the fix is the "Service-host profile" (HTTPS scanning OFF, all other shields ON) —
   [docs/RUNBOOK_transport.md](RUNBOOK_transport.md). `native_sdk` vs `schannel_curl` fallback in `service._resolve_transport`. Preflight: `scripts/preflight_transport.py`.
4. **Model loads on GPU** (GTX 1650, cuda_fp32). First warm-up ~30–40s.

---

## 4. EVAL SUBSTRATE

- **Frozen 40-query anchor set** (`draft_queries_v1.json`, sha 65492b65) — never edit.
- **v4 gold** `eval/results/gold_reference_set.csv` — scope-aware, **N=34 in-scope**;
  content-aware diffs only (`git diff --ignore-cr-at-eol`), NEVER numstat equality
  (a numstat-parity misread once destroyed hand-edited gold — see the gold-incident lesson).
- **Frozen pilot** `pilot_subset_frozen_v4.csv` (95/827), norm-sha `7d16096ad536`.
- Canonical eval: `w3_2_REGRADE_v3_v4gold.json`; drift harness `scripts/run_ops2_c1.py`;
  post-reboot drift `eval/results/postreboot/bm25_drift_check.json`;
  state audit `eval/results/postreboot/prod_state_audit.md`.

---

## 5. OPEN THREADS / BLOCKERS

- **N-1** (next full pilot-report lock): needs API credits + the B11 verdict — now *accepted*
  (v4.2 provenance), so this is credit-gated only.
- **arch-baseline-v4.1**: reserved for the W3.7 OOS-calibration close — **do not create yet**.
- **OPS-3 taxonomy expansion**: adjudication packet ready
  ([ops3_adjudication_packet.md](../eval/results/ops3_adjudication_packet.md)); EXECUTION (add
  topics, rebuild centroids, regrade, tag) is **prohibited until after N-1 + pilot-report lock**.
  Key finding: the <0.85 independence bar is unsatisfiable in raw bge-base space (anisotropy);
  use the intra-cluster coherence column (existing-topic band 0.76–0.77) to judge candidates.
- **Baron Travel / GC006**: subset-excluded from the v4 pilot (f961ca3) — a **scope/allowlist
  decision** (add GC006-class docs → re-freeze v5), NOT a matching fix. The entity-rescue
  mechanism (dark) is ready for when v5 brings those docs in-universe.
- **Human-owned**: Sheena's per-doc curation of approved OPS-3 clusters; live TTFA/gap
  measurement from a human voice-demo session.

---

## 6. KEY ARTIFACTS (this session's evidence chain, on `develop`)

`eval/results/`: `arch_baseline_v4_2_provenance.json` (v4.2 gates) ·
`arch_baseline_v4_retrieval.json` (v4 ratification) · `bakeoff_FINAL_for_dok.md` ·
`ops2_c1_drift.json` · `ops2_orphan_census.json` · `taxonomy_expansion_PROPOSAL.md` ·
`ops3_adjudication_packet.md` · `entity_rescue_report.md` · `baron_travel_forensics.md` ·
`prod_state_audit.md` · `bm25_drift_check.json` · `probe_report.json`.

Voice apps (demo surface, not the retrieval core): `streamlit_voice_demo.py` (OpenAI STT/TTS,
DEMO-only), `streamlit_voice_smoke.py` (local Whisper+SAPI), `components/gapless_audio/`
(Web-Audio gapless playback). Launch config: `.claude/launch.json` (`voice-demo`).

---

## 7. HANDOVER RELATIONSHIP

This doc **supersedes the 2026-06-21 handover for retrieval-architecture questions on
`develop`**. The 2026-06-21 handover remains valid for the **push-to-talk kiosk** on
`pre-wake-word-integration` (a different surface + a no-embeddings router). When the two
lines are reconciled/merged, that merge is itself a decision to record — it is not implied here.
`CLAUDE.md`'s "Read first" table and "Not RAG / no embeddings" line still point at the kiosk
architecture and should be updated to disambiguate the two branches (flagged, not done here).
