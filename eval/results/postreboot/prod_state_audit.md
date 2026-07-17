# Production state audit vs arch-baseline-v4 (553483c) — 2026-07-18

$0, read-only. Resolves the OPS-2 contradiction ahead of any drift-remediation decision.
Operator state untouched. HEAD at audit time: 06b8129 (develop = origin/develop).

## 1. The ddb5edf claim — VERDICT: **OPS-2 A–D TRULY RAN** (every claim verified on disk)

| Phase | Claim (commit msg) | Disk evidence |
|---|---|---|
| A | corpus_dense rebuilt 9865×768 bge-base | `corpus_dense.npy` shape (9865, 768) float32, sha16 `df5ca465c954e218`; meta: bge-base/768/9865, build 2026-07-17, cuda_fp32, parity `min_cosine=1.000000 over 827 rows`. **No file named `corpus_dense_bgebase.npy` exists** — Phase A rebuilt the production name `corpus_dense.npy` in place (config-pathed); the stale bge-large matrix survives locally as `_archived_bgelarge_corpus_dense.npy` (8887×1024, sha16 `bdac40d54c4c5a0e`, untracked by design) + its meta (committed). |
| B | 34 full-corpus member-mean centroids; old set archived | `topic_centroids.npy` (34, 768), sha16 `50600bdd34836db7`, meta build 2026-07-17 "member_chunk_mean over FULL corpus (OPS-2 Phase B)". Old set archived as `_archived_pilotmm_topic_centroids.npy`, **git-blob-identical to the v4 tag's production centroids** (blob `16f678116d78c0186f5af0c2646c3e605de38ea6` both sides). |
| C | C0 = C1 = 0.588/0.882/0.941/0.971 | `ops2_c1_drift.json` exists with per-run **artifact sha16s** (see §4 — this is what un-confounds the drift attribution). |
| D | census + proposal | `ops2_orphan_census.json` (380 KB) + `taxonomy_expansion_PROPOSAL.md` (6.1 KB) exist, committed in ddb5edf. |

## 2. Production artifact delta vs 553483c (everything the live pipeline loads)

| Artifact | v4 state | Current | Changing commit | Sanctioned? |
|---|---|---|---|---|
| `pilot_dense.npy` | v4 blob sha16 `8d0d0a80ecb3015b` | OPS-2 slice, sha16 `0ec7d6f64d3c5b14` (parity 1.000000/827) | ddb5edf | Task-sanctioned; **ahead of promotion gate** (see §3) |
| `topic_centroids.npy` | pilot-slice member-mean (34×768) | **full-corpus member-mean (34×768)** | ddb5edf | Task-sanctioned; **ahead of promotion gate** |
| BM25 `pilot_sparse.pkl` (untracked) + `sparse_phrase_dict.json` + meta | 8,887-chunk index | 9,865-chunk batch-02 rebuild, pkl sha16 `9dc1243621a96382` | 0b486d2 | Sanctioned (batch-02 task); its deferred drift gate now closed by C0 + 06b8129 |
| `config.py` | v4 pins | one text change | 2c69cc5 | Sanctioned (Dev0-approved GAP-decline wording); **zero retrieval knobs** |

**Explicit answer:** production centroids are the **post-OPS-2 full-corpus set**, NOT the v4
pilot-slice set. The 06b8129 drift check loaded the production paths (config
`CENTROIDS_PATH`/`DENSE_INDEX_PATH`) and therefore ran on the **post-OPS-2** centroids+dense —
its own provenance says so.

## 3. Gate compliance

- **ddb5edf (dense+centroids):** executed under the explicit Pao task "Run OPS-2 Phases A–D" and
  committed/pushed on request → **sanctioned-by-task**. However, the tag framework reserves
  **v4.2 = OPS-2 promotion (Dok/Pao ratification)** and v4.2 is uncreated — so production now runs
  a **post-v4, pre-ratification artifact set**. Not a rogue change, but promotion-gate-AHEAD:
  the ratification that v4.2 represents has not happened while the artifacts are already live.
- **0b486d2 (BM25):** sanctioned by the batch-02 onboarding task; its explicitly deferred drift
  check (C1) has now run — result: the B11 hit@1 regression (the gate found what it was built to find).
- **2c69cc5 (config):** sanctioned, retrieval-irrelevant.

## 4. Drift-check validity — VERDICT: **B11/BM25 ATTRIBUTION STANDS CLEAN**

06b8129 **in isolation** would be confounded (it measured batch-02 BM25 *and* OPS-2
centroids/dense together). The confound is resolved by the `ops2_c1_drift.json` hash record:

| Run | pilot_dense | centroids | BM25 | recall @1/@5/@sent/@10 |
|---|---|---|---|---|
| C0 | `8d0d0a80` **= v4 blob exactly** | `91d48c38` **= v4 blob exactly** | `9dc12436` (batch-02) | 0.588/0.882/0.941/0.971 |
| C1 | `0ec7d6f6` (OPS-2) | `50600bdd` (OPS-2) | `9dc12436` (same) | **identical to C0** |
| 06b8129 | `0ec7d6f6` | `50600bdd` | `9dc12436` | identical again (fresh embeds, post-reboot, post-pyarrow-pin) |

C0 held dense and centroids at bit-exact v4 while swapping ONLY the BM25 index → B11's hit@1
loss already present. C1/06b8129 changed dense+centroids with BM25 fixed → nothing further moved.
**Sole cause: batch-02 BM25/IDF. Centroid + dense contribution: zero at the graded level.**

Belt-and-braces re-run (specified per task, NOT executed): same 06b8129 harness with
`CJ_CENTROIDS_PATH=data/index/_archived_pilotmm_topic_centroids.npy` and pilot_dense forced to
the v4 blob (`git show 553483c:data/index/pilot_dense.npy > <isolated copy>`, pointed at via
`CJ_DENSE_INDEX_PATH`). Expected: reproduces C0 row-for-row.

## 5. Restore-scope options for Dev0 (no remediation performed)

1. **Ratify & promote (recommended by the evidence):** keep the live OPS-2 set; when Dok/Pao
   ratify, create v4.2 with B11 recorded as the known batch-02 BM25 cost (−2.9 pts @1, nothing
   else moved). Zero file operations.
2. **Strict v4 rollback of the OPS-2 layer:** `git checkout 553483c -- data/index/pilot_dense.npy
   data/index/pilot_dense_meta.json data/index/topic_centroids.npy data/index/topic_centroids_meta.json`
   (or copy the blob-identical `_archived_pilotmm_*` back). NOTE: this does NOT restore v4 BM25 —
   `pilot_sparse.pkl` is untracked; its v4 state would need a rebuild from the 553483c chunk set
   (recoverable from git, but it is a rebuild, not a checkout) — and C0 proves the OPS-2 layer
   contributes zero drift, so this rollback would not recover B11.
3. **B11 remediation proper (separate decision, separate task):** BM25-side tuning (e.g., IDF
   floor / doc-frequency damping for the batch-02 vocabulary shift) measured against the same
   frozen harness. This is the only option that can actually recover B11@1.

## Provenance
HEAD `06b8129`; v4 tag commit `553483ca61c1650c13a4e1a090baeb5ea3045660`; blob identities via
`git rev-parse <tag>:<path>` vs `git hash-object`; sha16 = sha256[:16] of file bytes; C0/C1
artifact hashes from `eval/results/ops2_c1_drift.json` (committed in ddb5edf). Audit was
read-only; the only write is this report.
