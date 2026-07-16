# Embedder Bake-off — FINAL Brief for Dok (rounds 2+3, four candidates)

**Decision INPUT, not a switch.** Production stays bge-large fp32; every candidate artifact is
parallel (`bakeoff_*`). $0, local. Grading: canonical method, repaired v4 gold, **N=34**, deduped
parent-doc ranks; **recall@chunks-sent** graded at each query's canonical v3 nucleus size (median 9,
range 4-12) — the k the composer actually sees. Evidence: `eval/results/bakeoff_round3.json`.

## Recall (N=34)
| candidate | @1 | @5 | **@chunks-sent** | @10 |
|---|---|---|---|---|
| A bge-large fp32 (canonical) | 0.735 | 0.971 | **0.971** | 0.971 |
| B MiniLM 384d | 0.559 | 0.853 | **0.912** | 1.0 |
| C bge-base 768d | 0.618 | 0.882 | **0.941** | 0.971 |
| D bge-large int8 | 0.735 | 0.971 | **0.971** | 1.0 |

- **D (int8) == A on every metric that matters** (0 hit@5 diffs vs canonical; cluster ranks identical;
  int8-vs-fp32 cosine on sampled chunks: **1.0**). Quantization costs nothing measurable in quality.
- **B9** (canonical's sole coverage miss): still missed by C (rank 6) and D (rank 10); **only MiniLM
  retrieves it @5** — but MiniLM pays -11.8pts @5 / -5.9pts @sent overall.
- C (bge-base) sits between: -5.9pts @5, -2.9pts @sent vs canonical; 3 hit@5 diffs.

## Query-embed latency (ms; CPU = CM4 proxy — ARM will be slower)
| candidate | GPU warm p50 / anchor p50 | CPU warm p50 / anchor p50 | CPU cold-first |
|---|---|---|---|
| A bge-large fp32 | 88.9 / 90.5 | 766.8 / 858.6 | 5819.1 |
| B MiniLM | 25.7 / 26.8 | 40.0 / 44.0 | 211.5 |
| C bge-base | 35.0 / 35.1 | 203.5 / 216.3 | 220.2 |
| D bge-large int8 | n/a (CPU-targeted) | 705.8 / 780.4 | 728.0 |

int8's CPU speed gain over fp32 is marginal (~10%) — **its win is memory, not speed**. One-off index
build on CPU: D took **81.7 min** for 827 chunks (build host-side and ship vectors; not a runtime cost).

## Footprint (RSS probe failed twice -> params-based estimates, flagged)
| candidate | params | RAM est | vectors @8,887 chunks |
|---|---|---|---|
| A bge-large fp32 | 335.1M | ~1,340 MB | 36.4 MB |
| B MiniLM | 22.7M | ~91 MB | 13.65 MB |
| C bge-base | 109.5M | ~437 MB | 27.3 MB |
| D bge-large int8 | 335.1M | ~400-500 MB (int8 Linear + fp32 rest) | 36.4 MB |

## Centroid stats (per-model; NOT comparable across models — bge compresses cosine range)
A prod 0.8354 (p5-p95 0.741-0.9038) · B 0.7736 (0.5244-0.9568) · C 0.9171 (0.8197-0.984) · D 0.9218 (0.8333-0.9848).
3 topics have zero pilot members (neutral-fallback centroids) — carried flag.

## Decision frame (Dok ratifies — this is not a decision)
**Fits CM4 (4GB shared, no GPU)?** A: NO (~1.3GB + seconds/query CPU). B: YES (~91MB, 44ms).
C: YES (~437MB, 216ms). D: LIKELY (~0.5GB; **781ms/query CPU on desktop — ARM likely 1.5-3s: TTFA-budget risk**).
**What each costs in recall@chunks-sent vs canonical:** D **-0.0pts** · C **-2.9pts** · B **-5.9pts**.
- Host-side topology -> **A** (nothing to trade).
- On-device + quality-first -> **D** if ARM query latency proves acceptable (needs one CM4 measurement); else **C**
  as the balanced fit (437MB, 216ms desktop-CPU, -2.9pts @sent).
- On-device + latency-first -> **B** (44ms, 91MB, -5.9pts @sent; uniquely fixes B9).
