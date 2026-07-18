# PROJECT HEALTH ASSESSMENT — CJP AI Persona Kiosk
**Stage-gate review before pilot report / Go-No-Go**
Date: 2026-07-15 · Auditor role: PM + senior dev · Method: read-only artifact audit, $0, nothing modified/committed.
Rule applied: every claim cites a path/commit/tag or is marked **UNKNOWN**; artifacts override prior run summaries; discrepancies flagged inline as **[DISCREPANCY]**.

---

## 1. CURRENT STATUS

### 1.1 Pipeline
- **HEAD:** `276cbdd` = `arch-baseline-v3-6-g276cbdd` (git describe). **Fully pushed** — `origin/feat/retrieval-pipeline` == HEAD (git rev-parse both = 276cbdd).
- **[DISCREPANCY — expectation vs actual]:** the task expects the pipeline "at arch-baseline-v3". Actual: HEAD is **6 commits past the v3 tag** (`fe75a3a`), and committed pipeline files **differ from the tag**: `git diff arch-baseline-v3..HEAD -- config.py app/service.py` = config.py +17 / app/service.py +2 lines — this is the **W3.7 OOS decline mechanism** (commit `2e40b2f`). So the running pipeline is **"v3 + OOS backstop"**, not v3. Retrieval/embeddings/sparse are byte-identical to the tag (empty diff).
- On top of that, the **working tree** modifies `app/retrieval.py` (uncommitted instrumentation — see §1.5); the added `timing` param is guarded (`timing=None` path unchanged) so behavior matches HEAD, but the file on disk ≠ any commit.
- Tags on origin: `arch-baseline` (caa3c8c), `arch-baseline-v2` (704c8a6), `arch-baseline-v3` (fe75a3a) — remote-confirmed earlier this session via `git ls-remote --tags`.

### 1.2 Corpus (counted from stores, not docs)
- `corpus/index/chunks.jsonl`: **8,887 chunks / 1,089 unique docs** (counted).
- `data/index/corpus_dense.npy`: shape **(8887, 1024)** (loaded, mmap).
- Pilot: `data/index/pilot_dense_meta.json` → **95 docs / 827 chunks**, `allowlist_version: v4`; `reports/pilot-eval subset/pilot_subset_frozen_v4.csv` → **95 doc_ids** (counted). Cross-check artifact: `eval/results/pilot_universe_report.json` asserts allowlist==pilot_index_docs==95, chunks==827, store==1089.
- verify_pin: **PASS** — most recent run this session ("1089 docs across 4 source files match corpus_snapshot.json", `scripts/verify_pin.py`).

### 1.3 Eval state
- **Frozen anchor:** sha `65492b650aec8dda...` in `reports/pilot-eval subset/draft_queries_v1.json` meta (commit `e43c199`); recomputed == stored at every gated run (most recently W3.2 FULL SC1, `eval/results/w3_2_FULL_v3_c1637cd.json` provenance).
- **Canonical gold:** `eval/results/gold_reference_set.csv` (v4-corrected), committed at `fc66b9e`. Coverage **40/40** with scope labels: in=34, meta=2 (X31,X32), out=2 (X35,X36), in(gap-v4)=1 (X33), in(gap)=1 (X39) (counted from the CSV). Working-copy diff is **CRLF-only** (`git diff --numstat` = 44/44, no content change).
- **Canonical scorecard:** `eval/results/w3_2_REGRADE_v3_v4gold.json` (committed `e18e1d1`) — v3 retrieval + v4 gold, re-grade (no re-run):
  - recall@1/3/5/10 = **0.735 / 0.941 / 0.971 / 0.971**, denominator **N=34** (X33/X39 GAP excluded).
  - recall@1 misses: **B9 = sole coverage miss** (gold CB005/6/7 never retrieved); ranking near-misses A2(r2), A4(r3), B10(r2), C17(r2), C18(r2), D23(r2), E28(r4), E29(r3).
  - Carried from the v3 canonical run: **fabrication 0/40, empty-cited 0, MIN_K=4 KEEP** (`w3_2_FULL_v3_c1637cd.json` §C/§E).

### 1.4 Feature flags (config.py, loaded values)
| Flag | Value | Verification artifact | Tracked? |
|---|---|---|---|
| `DATE_INDEX_ENABLED` | **False** | `eval/results/w2_4_date_index_selfcheck.json` (no-regression PASS, idempotent sha) | TRACKED |
| `EXPAND_ON_DEMAND_ENABLED` | **False** | `eval/results/w2_6_expand_report.json` (flag-off verbatim, hard-cap=1) | TRACKED |
| `COMPOSER_OOS_DECLINE_ENABLED` | **True** (committed `2e40b2f`) | `eval/results/w3_7_oos_calibration_fc66b9e.json` | **LOCAL-ONLY** ⚠️ |

⚠️ Note the asymmetry: the OOS **mechanism** is committed+pushed, but its **verification evidence** (the calibration/re-verify artifact) exists only on this laptop. Same for the commit-gating A/B (`w3_compose_eval_0.json`, LOCAL-ONLY).

### 1.5 UNCOMMITTED WORK inventory (critical)
Tracked modifications (git status):
| Item | What | Produced by | Ever committed? | Risk if lost |
|---|---|---|---|---|
| `app/retrieval.py` (M) | `run_timed()` + guarded `timing` param in `_score_universe` (Table-2 instrumentation) | instrumentation task | **NEVER** | Table-2 harness breaks (imports `run_timed`); rework ~1h |
| `scripts/run_arch_baseline_v2.py` (M) | auto-populate hook for Tables 1/3 (`emit_from_records`, try/except-guarded) | instrumentation task | **NEVER** | next compose run won't auto-fill cost/latency tables |
| `eval/results/gold_reference_set.csv` (M) | **CRLF-only** renormalization (44/44 numstat, no content) | incidental | canonical version committed `fc66b9e` | none (cosmetic) |

Untracked, **never committed anywhere** (selected; full list in git status):
| Item | What | Risk if lost |
|---|---|---|
| `scripts/eval_instrumentation.py` | Table 1/3 schemas, rate constants, transport/degraded guards, cost+ttfa math with self-test | instrumentation layer gone; guards gone |
| `scripts/run_latency_retrieval.py` | Table-2 harness | re-writable; artifact re-runnable $0 |
| `eval/results/latency_retrieval_$0.json` + `latency_retrieval_per_query.csv` | the **only** per-sub-stage retrieval latency data (embed-bottleneck finding) | re-runnable $0, but the finding's evidence is local-only |
| `eval/results/w3_7_oos_calibration_fc66b9e.json` | **OOS verification evidence** (separation analysis + re-verify) | NOT re-runnable free (needs ~12 composes + credits); losing it orphans the committed OOS mechanism's evidence |
| `eval/results/w3_compose_eval_0.json` + `w3_compose_eval_ab_for_sheena.csv` | the **commit-gate A/B evidence** + Sheena's A/B input | A/B rows for Sheena lost; gate evidence lost |
| `eval/results/compose_telemetry_harvest{.json,ed.csv}` | measured composer cost/TTFT harvest | re-derivable from arch_baseline_v2.json ($0) |
| `eval/results/cost_per_query*.csv/json`, `compose_latency*` | Table 1/3 stubs + self-test rows | re-emittable $0 |
| `eval/results/pilot_universe_report.json` | pilot-universe discovery (allowlist/pin/reachability) | re-derivable $0 |
| `W1.10_Decisions_Memo.md` + `.docx` | **Week-1 lock decisions memo** (sign-off doc) | ⚠️ governance doc exists nowhere else |
| `CJP_*.xlsx/png`, `reports/pilot-eval subset/*` (v1/v2 selection notes, coverage tables, grading workbooks), `eval/results/CJP_TaskA_RAG_Eval_Metrics_w2_1_v4gold.xlsx` | human-produced planning/grading artifacts | not reproducible by code ⚠️ |
| `eval/results/_w3_7_phase1.json` | scratch (phase-1 cosines) | none |

### 1.6 Week-plan reconciliation
Full machine-readable table in **`eval/results/task_status.csv`** (planned W-rows + 16 UNPLANNED items). Headline: W1.1–W1.11 DONE; W2.1–W2.6 DONE (W2.4/2.6 dark); W2.7 PARTIAL (replay-TTFA real, live-TTFA + robot TTS unverified); W3.2 DONE (canonical = regrade); W3.3/W3.4 NOT_STARTED; W3.7 PARTIAL (3 re-verifies blocked on credits). W1.2 / W3.1 / W3.5 / W3.6: **UNKNOWN** — no evidence in repo or session that these were ever defined.

---

## 2. RISKS (likelihood × impact, mitigation cited or UNKNOWN)

| # | Risk | L×I | Evidence | Mitigation (exists / missing) |
|---|---|---|---|---|
| R1 | **Native-TLS flapping (Avast)** contaminates latency/streaming runs. Happened ≥2×: W3.2 partial run-1 forced to curl (`w3_2_PARTIAL_BC_73a4a12.json` §transport, incl. the **X33 curl-degraded ghost**); regression re-detected before the v3 canonical run. | High × High | artifacts cited | **EXISTS:** `scripts/preflight_transport.py` (committed `276cbdd`) fails loudly pre-run; `docs/RUNBOOK_transport.md` documents the profile. **MISSING:** the OS-side profile keeps reverting (reboot-fragile); no scheduled re-check. |
| R2 | **API credit exhaustion mid-run.** Happened 2×: W2.1-era (evidence: session logs only — **UNKNOWN in artifacts**) and W3.7 close (evidence: `w3_7_oos_calibration_fc66b9e.json` §credit_exhaustion_note, 400 "credit balance too low"; killed A1/D20/E27 re-verify). | High × Med | cited | **MISSING entirely:** grep for credit/balance monitoring in `app/ scripts/ config.py` → no API-credit monitor exists (only an incidental word-hit in `build_pilot_subset_v4.py`). No budget floor, no pre-run balance check. |
| R3 | **Single-machine loss.** Code: fully pushed (HEAD==origin). But §1.5 shows the instrumentation layer, OOS verification evidence, A/B gate evidence, W1.10 memo, and all human grading/planning xlsx are **local-only**. If the laptop dies today: code+tags survive; **the OOS evidence chain, Table-2 latency data, W1.10 memo, and Sheena-facing A/B CSV do not.** | Med × High | git status | **MISSING:** a commit+push of eval/instrumentation work (top do-now item, §9). |
| R4 | **Eval validity gaps:** OOS verified on n=2 probes (`w3_7...json` §caveat says PROVISIONAL); A1/D20/E27 in-scope never re-verified post-directive (billing); TTFA unmeasured (harvest: "not recoverable"); 6 low-confidence gold labels SME-unconfirmed (`gold_reference_set.csv` gold_confidence=low: B10,C14,C17,C18,D24,X40). | Med × High | cited | Partial: caveats are documented in artifacts; the closing runs are specified but blocked [CREDITS]/[Sheena]. |
| R5 | **Decision debt:** embedder ratification pending (Dok — bge pinned per `pilot_dense_meta.json`; repeated "pending Dok" notes in commit messages e.g. `fc66b9e`); wake word unconfirmed (`design/w2_7_reachy_seam.md` §f flags "Seejop"/"CJ" garble, parameterized); assessors Frank/Kate named in planning but **no A/B run artifact exists** (repo evidence: only `w3_compose_eval_ab_for_sheena.csv`, winner column blank). | Med × Med | cited | MISSING: owner deadlines. |
| R6 | **Scale path:** dense scoring is brute-force matmul over the 827-chunk pilot (`app/retrieval.py:_score_universe`, `mat @ qv`); fine at 8,887 (measured dense 2.5ms p50, `latency_retrieval_$0.json`) but **no ANN plan artifact exists — UNKNOWN**. Date-index + expand features are dark and unexercised in production paths. | Low × Med | cited | MISSING: documented full-corpus transition note. |
| R7 | *(artifact-revealed, not on the list)* **Tag-drift ambiguity:** "arch-baseline-v3" colloquially means the pipeline, but HEAD has diverged (OOS mechanism + uncommitted instrumentation). Any future "run at v3" instruction is ambiguous. | Med × Med | §1.1 diff | MISSING: a v3.1 tag (or explicit statement) once OOS verification closes. |
| R8 | *(artifact-revealed)* **Legacy app confusion:** `app/app.py`/`app/cj_chat.py`/`app/dashboard.py` still implement the pre-W1.8 pipeline (Haiku router, OpenAI STT/TTS — headers of those files). A demo launched from the old kiosk would bypass everything built since W1.8. | Low × High | file headers | MISSING: deprecation banner or removal decision. |

---

## 3. CHALLENGES (engineering)

1. **The embed bottleneck.** `eval/results/latency_retrieval_$0.json`: query embed **535.1ms p50 (86% of the 620.7ms retrieval total)**; the soft-prior router math is **0.19ms**. **[DISCREPANCY resolved]:** prior summaries called this "the 542ms router" — the artifact proves the lumped `router_ms` in `arch_baseline_v2.json` (164.7ms p50) was embed+route, and the "router bug" was **mislabeled embed time**. Worse: embed is **GPU-state-variable** (165ms in the v2 run vs 535ms in the instrumented run — same box, warm). On-device implication is severe (§4/§5).
2. **Retrieval quality targets (W3.4):** one true coverage miss (**B9** — gold CB005/6/7 never retrieved at any rank) + a **rank-2/3 ordering cluster** (A2,A4,B10,C17,C18,D23,E28,E29) — all cited from `w3_2_REGRADE_v3_v4gold.json` §B. These are two different problems: coverage (B9) won't be fixed by re-ranking; the cluster likely will.
3. **OOS robustness for a public kiosk.** The cosine gate is **proven inert** (`w3_7_oos_calibration_fc66b9e.json` §phase1: OUT max 0.583 > in-scope min 0.5744; a separating threshold would false-decline C18/D24/E29/X32). The mechanism is a **composer prompt directive** (`config.COMPOSER_OOS_DECLINE_TEXT`) — verified on exactly 2 probes. For a public kiosk this is thin: no adversarial/prompt-injection probes, no profanity/safety probes, no non-English probes exist anywhere in the eval set (gold CSV has none). Hardening planned: more OOS probes (Sheena, flagged in the artifact); nothing else documented — **UNKNOWN**.
4. **Code sweep:** `grep -rnE "TODO|FIXME|HACK|XXX"` over app/, scripts/, config.py → **zero hits** (clean). Dead/deprecated paths (grep "deprecated|stale"): `scripts/generate_corpus_files.py` (old CSV generator; `generate_corpus_from_xlsx.py:3` calls its inputs "the stale 80-doc tracked CSVs"), `ROUTER_MODEL_ID` deprecated in config.py, legacy `MAX_TOKENS=300` still the default for the non-streamed `_messages()` path (`app/service.py:172`) while the streamed path uses 640 — a latent inconsistency if the curl path ever composes long answers. Legacy kiosk apps per R8.

---

## 4. REACHY MINI INTEGRATION READINESS

Hardware target: CM4, no GPU, ~4GB shared RAM (per task statement; no repo artifact specifies the hardware — **UNKNOWN in repo**).

**THE fit question — embedder:** current model is `BAAI/bge-large-en-v1.5`, 1024-d (`data/index/pilot_dense_meta.json`); ~335M params ≈ **~1.3GB fp32** (figure derived from model identity, not a repo artifact). On a 4GB CM4 sharing RAM with the robot stack, bge-large on-device is implausible without quantization; MiniLM-class (~90MB) or host-side embedding are the alternatives. **This is Dok's pending ratification and it now doubles as the topology decision.**

- **Seam design:** EXISTS — `design/w2_7_reachy_seam.md` + `design/w2_7_seam_stubs.py` (committed `d24fb0f`). Its **MUST-CONFIRM list, verbatim headings:** 1. LLM slot protocol; 2. In-process vs endpoint; 3. Who sentence-chunks; 4. Envelope side-channel; 5. Audio format; 6. Transport on the robot host; 7. Turn lifecycle / barge-in; 8. STT output contract. Open decisions flagged there: **wake word** ("Seejop"/"CJ" garble — parameterized as `wake_phrase`, unresolved) and **on-device vs host embedding**.
- **TTS:** SAPI is the Windows stand-in (real audio verified: `w2_7_ttfa_v2_report.json` — 39/39 overlap PASS, engine=sapi5). Piper: `piper-tts` **pip-installs fine on Windows** (same artifact §engine.piper_attempt) but the ~60–100MB voice model was never downloaded → **no Linux/on-device TTS is verified**. Plan per seam doc: Piper/Kokoro via the same `TTSBackend.synth` interface — design only.
- **ASR/mic:** repo evidence exists but is **legacy**: `app/cj_chat.py` (faster-whisper STT) and `app/app.py`/`voice_io.py` (OpenAI STT) — the pre-W1.8 kiosk stack. For the robot, the seam doc assigns ASR to the robot's s2s stack (Parakeet/Whisper) — assumption, MUST-CONFIRM #8. **No new-pipeline ASR integration exists.**
- **Deployment topology:** **UNDECIDED** — no artifact records a decision (the seam doc explicitly lists it as open). Deadline: robot arrival ~2–3 months (task statement; no repo artifact).

**INTEGRATION READINESS TABLE**

| Component | On-device plan | Status | Blocker |
|---|---|---|---|
| Embed (bge-large 1024d) | UNDECIDED — bge ~1.3GB fp32 vs MiniLM ~90MB vs host-side | pinned to bge on dev GPU (`pilot_dense_meta.json`) | **Dok ratification + topology decision** |
| Dense + BM25 + RRF + nucleus | trivially portable (numpy + rank-bm25; 827×1024 matmul ~2.5ms on PC) | working, measured (`latency_retrieval_$0.json`) | none (CPU cost on ARM unmeasured) |
| Centroid router | portable (34×1024 matmul, 0.19ms) | working | none |
| Composer (Sonnet API) | off-device by definition; needs native TLS on host | working native on dev box (flaky — R1) | credits (R2); robot-host TLS = MUST-CONFIRM #6 |
| TTS | Piper/Kokoro via `TTSBackend` interface (design) | SAPI verified on Windows only | Piper voice model never obtained; Linux unverified |
| ASR/mic | robot s2s stack (Parakeet/Whisper) — assumption | legacy Windows STT only in repo | MUST-CONFIRM #8; no integration |
| Wake word | robot-side, parameterized `wake_phrase` | **word itself unconfirmed** | Dev0 decision |
| Seam (LLM slot) | OpenAI-compatible streaming endpoint or in-process | design + stubs only (`design/`) | MUST-CONFIRM #1/#2; not built (by instruction) |

---

## 5. LATENCY ANALYSIS (all figures from artifacts)

**Retrieval per-stage** (`eval/results/latency_retrieval_$0.json`, per-query CSV alongside; 40 queries, warmed, $0):

| stage | p50 ms | p95 ms | share of total p50 |
|---|---|---|---|
| query embed (bge, GPU) | **535.1** | 549.2 | **86%** |
| sparse BM25 | 71.2 | 111.4 | 11% |
| centroid affinity | 5.8 | 7.9 | ~1% |
| dense matmul | 2.5 | 3.8 | <1% |
| RRF fuse | 1.2 | 1.9 | <1% |
| nucleus cutoff | 1.2 | 1.9 | <1% |
| router math | 0.19 | 0.26 | ~0% |
| payload assembly | 0.02 | 0.03 | ~0% |
| **total** | **620.7** | 674.2 | |

**Instability finding:** the same embed measured ~165ms p50 inside the arch-baseline-v2 run (`arch_baseline_v2.json` router_ms p50 164.7 = embed+route lumped) vs 535ms in the instrumented run — **3.2× swing on the same warm box**, attributed (in the artifact) to GPU clock state. Retrieval latency is therefore **not a stable 250ms; it is 170–620ms depending on GPU state.**

**Compose** (provenance: `eval/results/compose_telemetry_harvest.json`, harvested from `arch_baseline_v2.json` — 40 real composes, **directive-OFF**, native, v3-equivalent config; directive-ON latency was never captured):
- TTFT p50/p95: **1533 / 2617 ms** (arch_baseline_v2.json `ttft_ms`; harvest's sorted-index method gives 1560/2678 — method difference, flagged, immaterial).
- Full compose p50/p95: **10,443 / 12,142 ms** (arch_baseline_v2.json) — the answer is complete long after speech should have begun; streaming is what makes this acceptable.
- Throughput: ~41 tok/s p50 (harvest).

**TTFA: UNMEASURED — plainly stated.** The only TTFA figures on disk are **replayed** (recorded answers re-streamed through SAPI: `w2_7_ttfa_v2_report.json`, p50 2505ms) — no live compose→TTS chain has ever been timed. The closing run: **~5–10 live composes routed through the W2.7 streaming TTS harness** (`app/voice_stream.py` + `scripts/run_w2_7_ttfa_v2.py --live-probe` pattern) on native transport. [CREDITS], est. <$0.30.

**On-device projection (CM4, no GPU):** the embed — already the bottleneck at 535ms on a discrete GPU — moves to ARM CPU: bge-large on CPU is typically seconds/query (no repo measurement — **UNKNOWN**, but directionally certain). Dense/BM25/centroid stages are small and portable. TTFT is network-bound (unchanged). Conclusion: **on-device bge is the single number that breaks the ≤3s TTFA budget; MiniLM-or-host is the decision that fixes it.**

---

## 6. EVALUATION ANALYSIS

**Canonical quality** (`eval/results/w3_2_REGRADE_v3_v4gold.json`, committed `e18e1d1`):
- recall@1/3/5/10 = 0.735/0.941/**0.971**/0.971 over **N=34** in-scope (X33/X39 GAP excluded). The regrade IS the reachable set under v4 gold; **B9 is the single coverage exception** (gold never retrieved).
- Fabrication **0/40**, empty-cited **0** (carried from `w3_2_FULL_v3_c1637cd.json` §C — pipeline identical, gold-only regrade).
- Special-5 scope behavior (`w3_2_FULL_v3_c1637cd.json` §D + `w3_7_oos_calibration_fc66b9e.json` re-verify): X35 declined (both runs); X36 declined **only with the OOS directive ON**; X31/X32 identity OK; X39/X33 graceful, 0 fabrication.

**NOT yet evaluated** (each: evidence of absence):
- End-to-end A/B with assessors — only `w3_compose_eval_ab_for_sheena.csv` exists, winner column blank; no Frank/Kate artifact — **not run**.
- Persona quality post-OOS-directive on the full 40 — directive-ON composes exist for only 9 queries (`w3_7...json`); full-40 directive-ON never run.
- OOS beyond 2 probes — gold CSV contains exactly 2 `out` rows.
- TTFA — §5.
- Directive-ON cost — harvest coverage report: "not_captured" for all W3.7 rows.

**Eval infrastructure health:**
- Ranked `retrieved_docs` now persisted in the harness's own artifacts: `scripts/run_w3_2_regrade.py` CSV (committed `e18e1d1`, verified header) and `scripts/run_w3_2_full.py` (fix committed `803a7f9`). The **only run that predates the fix** is the v3 FULL itself — its retrieval record lives in Sheena's gold CSV `retrieved_docs` column (authenticity cross-checked in the regrade artifact §method). Future runs: self-contained.
- Instrumentation Tables 1/3 wired to auto-populate (`scripts/eval_instrumentation.py` + hook in `run_arch_baseline_v2.py`) with transport-single-assert and degraded-exclusion guards — **but all of it is uncommitted** (§1.5).

---

## 7. COST ANALYSIS

**Measured** (`eval/results/compose_telemetry_harvest.json`, from arch_baseline_v2's 40 real composes, directive-OFF; rates logged: $3/$3.75/$0.30/$15 per MTok, `claude-sonnet-4-6`):
- **Uncached: $0.028/query mean ($0.029 p50), $1.12 per 40-query run.**
- Cached: $0.0155/query mean (`arch_baseline_v2.json` cost_per_query_usd.mean_cached).
- **Uncached is the honest kiosk regime**: Anthropic prompt-cache TTL ~5 min (`w2_3_cache_report.json` §ttl_reality_note); museum visitors arrive sporadically, so the 4,596-token cached prefix expires between queries.

**Projections (assumptions stated):**
| Scenario | Assumption | Cost @ $0.028/q uncached |
|---|---|---|
| 1,000 questions | — | **~$28** |
| Demo day | ~150 queries (assumed, no artifact) | **~$4.20** |
| Kiosk month | 50 q/day × 30 d = 1,500 q (assumed) | **~$42/mo** |
Caveats: directive-ON cost unmeasured (declines are shorter → marginally cheaper); prices per logged constants — re-derivable if pricing changes.

**Dev spend to date:** recorded in artifacts: $0.665 (`arch_baseline.json`) + $0.768 (`w2_1_baseline.json`) + $0.115 (`w2_2_payload_report.json`) + $0.054 (`w2_3_cache_report.json`) + $0.620 (`arch_baseline_v2.json`) = **$2.22 recorded**. At least five further paid runs captured **no** cost telemetry (W1.9 partial, 2× W3.2 partials, W3.2 FULL, W3.7, plus two credit-exhaustion abort runs) — true total **UNKNOWN, plausibly $4–6**. **Credit exhaustion hit twice** (§2 R2). **Recommendation:** set a **$20 balance floor**; extend `scripts/preflight_transport.py` into a pre-run preflight that (a) checks native TLS and (b) makes one $0.001 haiku-class ping to detect billing-death before a 40-query run commits; alert at floor.

---

## 8. KPIs — pilot scorecard

| KPI | Target | Current | Status | Justification (evidence) |
|---|---|---|---|---|
| recall@5 (reachable, v4 gold) | ≥0.95 | **0.971** | 🟢 | `w3_2_REGRADE_v3_v4gold.json`, N=34 |
| recall@1 | (no target set) | 0.735 | 🟡 | 8 rank-2/3 near-misses + B9; W3.4 target |
| Fabricated citations | 0 | **0/40** | 🟢 | `w3_2_FULL_v3_c1637cd.json` §C (carried by regrade) |
| Empty-cited in-scope | 0 | **0** | 🟢 | same |
| TTFA p50 | ≤3s | **UNMEASURED** (replay proxy 2.5s) | 🔴 | `w2_7_ttfa_v2_report.json` is replay-only; live chain never timed |
| TTFT p50 | ≤2s | **1.53s** | 🟢 | `arch_baseline_v2.json` (directive-OFF, native) |
| Cost/answer (uncached) | ≤$0.05 | **$0.028** | 🟢 | `compose_telemetry_harvest.json` |
| OOS decline on probes | verified | 2/2 — **n too small** | 🟡 | `w3_7_oos_calibration_fc66b9e.json`; PROVISIONAL caveat in-artifact |
| In-scope false-declines | 0 | **0 verified / 3 unverified** (A1,D20,E27) | 🟡 | same artifact; billing-blocked |
| Degradation behavior | graceful | verified (in-voice fallback under real billing failure) | 🟢 | `w3_7...json` credit_exhaustion_note; `w2_1` run-2 behavior |
| Corpus | 95-doc pilot live | 95/827 pilot; 1,089/8,887 indexed | 🟢 | stores counted §1.2 |
| Retrieval latency p50 | (no target set) | 621ms, embed-dominated, unstable 170–620 | 🟡 | `latency_retrieval_$0.json` |
| **Uncommitted-work items** | 0 | **3 modified + 16 untracked code/eval files** | 🔴 | git status §1.5 |
| Robot integration | seam confirmed | design-only; 8 MUST-CONFIRMs open; TTS/ASR unverified on Linux | 🔴 | `design/w2_7_reachy_seam.md` |

---

## 9. RECOMMENDED PATH (sequenced, owner-tagged)

**Critical path to demo-ready:** commit/push local work → top up credits → close the 3 verification gaps (A1/D20/E27 + TTFA + directive-ON cost, one combined run) → Dok embedder/topology decision → Frank/Kate A/B → pilot report.

**Do now ($0):**
1. **[Dev0] Commit + push the local-only work** — instrumentation (retrieval.py, eval_instrumentation.py, run_latency_retrieval.py, the hook), the OOS verification artifact, the A/B gate artifacts, the W1.10 memo, and the human xlsx/planning files (or move the latter to shared storage). This clears the 🔴 durability KPI in one commit.
2. **[Sheena] SME-confirm the 6 low-confidence gold labels** (B10,C14,C17,C18,D24,X40) and **author 4–6 new OOS probes** (sports/cooking/personal-advice/current-events + one adversarial/injection probe) — pure labeling, no spend.
3. **[Dev0, $0 GPU-local] MiniLM bake-off prep:** embed the 827-chunk pilot with MiniLM locally and re-run the recall regrade offline — no API needed — so Dok's ratification is a data-backed decision (recall delta + 90MB-vs-1.3GB fit).

**Post-top-up [CREDITS]:**
1. **One combined verification run (~15 composes, <$0.50):** A1/D20/E27 directive-ON re-verify + full Tables 1/3 auto-populate (directive-ON cost + TTFT) — the instrumentation hook makes this free-riding.
2. **Live TTFA run (~5–10 composes, <$0.30):** compose→sentence-chunk→SAPI, stopwatch end-to-end; closes the last 🔴 measurement KPI.
3. **Full-40 directive-ON persona pass (~$1.20):** gives Frank/Kate their A/B corpus (pairs with the archived directive-OFF answers in `arch_baseline_v2.json`).

**Human decisions owed:**
- **Dok:** embedder ratification (bge vs MiniLM vs host-side) — now coupled to topology; the MiniLM bake-off (do-now #3) de-risks it.
- **Dev0:** wake word (unblock the seam doc's `wake_phrase`); credit floor + monitoring adoption; name a topology owner with a decision date ahead of robot arrival (~2–3 months).
- **Sheena:** the 6 label confirms + OOS probe expansion (do-now #2); A/B winner column in `w3_compose_eval_ab_for_sheena.csv`.
- **Frank/Kate:** A/B kickoff once the directive-ON corpus exists ([CREDITS] #3).

---
*Audit complete: $0 spent, no API calls, nothing modified or committed. Two prior-summary-vs-artifact discrepancies flagged: the "542ms router" (was mislabeled embed time — §3.1) and "pipeline at arch-baseline-v3" (HEAD is v3+OOS+6 commits — §1.1). One expectation-mismatch documented: TTFT KPI cites 1533ms (artifact) vs the harvest's 1560ms (percentile-method difference).*

---

## N-1 verification update (2026-07-18) — supersedes directive-OFF KPIs

Combined verification run on the shipping config (v4.2 + concise directive @ max_tokens=480),
15 composes, $0.27, fabrication 0. Evidence: `eval/results/n1_verification_run.json`.

- **R4 OOS re-verify gap → CLOSED.** A1/D20/E27 (the three never re-verified under the decline
  directive) all **ANSWER**, grounded, hit gold — no false declines. GAP→NEW-4b decline,
  LEGAL→NEW-6 deflect, OOS(weather)→in-voice decline all correct.
- **Cost/query (directive-ON, cached) = ~$0.0177 avg** (cache-write query $0.031; cached
  $0.011–0.020) — **supersedes the $0.028 directive-OFF** figure (§compose).
- **TTFT (directive-ON, current provenance): p50 1889 ms.** p95 is skewed by one 17.3 s outlier
  (GAP-baron, transient API spike); excluding it, max TTFT ≈ 5.5 s. Supersedes the directive-OFF
  1533/2617 ms harvest.
- **Filler-sizing data:** first-sentence p50 = 24 words; tts-1 synth p50 = 3477 ms (~3.5 s). The
  TTFA filler must bridge ~3.5 s of first-sentence synthesis + the compose-to-first-sentence gap.
- **⚠ Concise-length KPI: NOT MET.** In-scope answers ran **p50 198 words** (target ~100). The
  concise directive is nearly inert at max_tokens=480 — W3.3's conciseness came from the 320
  hard-cap, which was raised to 480 to stop the citation-envelope truncation. **Follow-up: re-tune
  `COMPOSER_MAX_TOKENS` to ~400–440** (the 320-truncates-envelope vs 480-not-concise tension is
  unresolved). Out of N-1 scope (measure, don't tune).
- **Tag:** `arch-baseline-v4.1` created (W3.7 OOS-close verified). The length KPI miss above is the
  one open item against the shipping config.

## W3.3-B update (2026-07-18) — concise directive now binds

Directive strengthening (hard length rule at the top of the Voice-Card; no cap change). Verify (4
composes, `eval/results/w3_3b_directive_binding.md`):
- **In-scope answer length: words p50 198 → 117** (all in 100–150). The concise directive is no
  longer inert; the length KPI (open item against v4.1) is now **MET**.
- Envelope intact, fabrication 0, reads in-voice, NEW-6 control answers normally.
- Cost/query (directive-ON, cached) **$0.0177** (N-1) unchanged; max_tokens stays 480.
- Filler-sizing: first-sentence 24 → ~11 words, but tts-1 synth floor ~3.0–3.5 s unchanged — the
  filler still bridges ~3 s (streaming-TTS path built + held to attack this, `STREAM_TTS_ENABLED`).
