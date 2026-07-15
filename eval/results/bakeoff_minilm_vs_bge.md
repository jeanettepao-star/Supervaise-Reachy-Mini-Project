# MiniLM vs bge-large — Embedder Bake-off Brief (for Dok)

**Purpose:** decision INPUT for the embedder + topology ratification. NOT a switch — production stays
pinned to bge-large; all MiniLM artifacts are parallel (`data/index/bakeoff_*`). $0 (local only).
Method: retrieval-only replay in MiniLM space (BM25/RRF/soft-prior/nucleus params unchanged), graded
with the canonical method (scope-aware, N=34, v4 gold, deduped parent-doc ranks). Evidence:
`eval/results/bakeoff_minilm_vs_bge.json`.

## Recall (N=34, v4 gold — same grading code path)
| recall@ | bge-large (canonical) | MiniLM (measured) | delta |
|---|---|---|---|
| 1 | 0.735 | 0.559 | -0.176 |
| 3 | 0.941 | 0.824 | -0.117 |
| 5 | **0.971** | **0.853** | **-0.118** |
| 10 | 0.971 | 1.0 | +0.029 |

**Read:** MiniLM loses **-11.8pts @5** and **-17.6pts @1** — a real quality cost — but reaches
**1.000 @10** (everything retrievable lands in the top-10, incl. **B9, bge's sole coverage miss,
which MiniLM retrieves at rank 5**). 14 queries change hit@1-or-@5 (A1, A2, A4, B8, B9, B10, B12, C13, D19, D23, D24, E26, E28, X37).
Rank-2/3 cluster: MiniLM fixes A2+B10 to rank-1 but worsens D23 (r2→8) and E28 (r4→9). A larger
composer top-k could mask MiniLM's @5 gap at extra token cost — a tunable, not a freebie.

## Query-embed latency (same box; CPU = CM4 proxy — CM4 ARM will be slower still)
| model | device | cold-first ms | warm p50 ms | 40-anchor p50 / p95 ms |
|---|---|---|---|---|
| MiniLM | cuda | 2254.4 | 25.7 | 26.8 / 33.3 |
| MiniLM | **cpu** | 211.5 | **40.0** | **44.0** / 52.3 |
| bge-large | cuda | 6486.5 | 88.9 | 90.5 / 307.2 |
| bge-large | **cpu** | 5819.1 | **766.8** | **858.6** / 1107.4 |

CPU: bge is **~20x slower** than MiniLM (858.6ms vs 44.0ms p50). Corroborates the
GPU-state instability finding: bge-cuda measured 90.5ms here vs 535ms in the Table-2 run
(latency_retrieval_$0.json) — same box, different GPU clock state.

## Footprint
| | MiniLM | bge-large |
|---|---|---|
| params | 22.7M | 335.1M |
| fp32 RAM est (params x 4B) | ~91 MB | ~1,340 MB |
| on-disk (HF cache) | 91.6 MB | 1341.7 MB |
| vectors 827 pilot | 1.27 MB | 3.39 MB |
| vectors 8,887 corpus | 13.65 MB | 36.4 MB |

(RSS-delta instrumentation failed — WorkingSet delta read 0.0; use the params-based estimate.)

## Centroid separation (mean pairwise cosine; lower = crisper dimensions)
- bge production (field+exemplar-built): 0.8354
- bge member-mean (like-for-like): 0.9218
- **MiniLM member-mean: 0.7736** — MiniLM's space is less cosine-compressed
  than bge's, so its member-mean dimensions are actually crisper like-for-like.
- Caveat: 3 topics have **zero pilot member chunks** (death_penalty_and_echegaray, honors_received, robot_identity_meta)
  and used a neutral fallback centroid — full-corpus membership would fix this for a real switch.

## Incident note (transparency)
The first grading pass ran against a stale gold (an uncommitted-v4 regression, since repaired from the
committed regrade record and re-graded at N=34). Non-grading gold columns (titles/summaries/
model_answer/review_status) may hold unrecovered v4 edits — **Sheena to re-verify**.

## RECOMMENDATION FRAME (not a decision)
- **Host-side topology → bge-large.** Recall is canonical (0.971 @5); RAM/CPU cost is irrelevant off-device;
  embed latency is GPU-state-managed on the host.
- **On-device (CM4) → MiniLM or quantized bge.** bge fp32 (~1.3GB) does not plausibly fit 4GB shared RAM,
  and its CPU embed (~858ms on a desktop core) lands in the seconds on ARM — it breaks the TTFA budget.
  MiniLM fits (~91MB, ~44ms CPU) at a measured recall cost of **-11.8pts @5 / -17.6pts @1**
  (partially maskable by a larger top-k; and it fixes B9).
- Third option to price before ratifying: **quantized bge (int8) or an mid-size model (e.g. bge-base)** —
  not measured here; worth one more $0 bake-off round if on-device topology is chosen.

*$0, local-only. Production config untouched. Dok ratifies.*
