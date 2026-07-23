# Filler-v5 Phase-2 — STOP report: filler-2 cannot be gated safe (routing-bound)

**Issued** 2026-07-24 · **Branch** `develop` · **Mode** WRITE/FIX → **STOPPED at Task C per boundary rule 2**

## Header

| Field | Value |
|---|---|
| HEAD sha (before) | `94c55b2` (Phase-1) |
| Verdict | **STOP — no code fix shipped.** No topic gate reaches the precision bar (0 wrong-topic fires) at usable recall; the blocker is routing top-1 accuracy, which boundary rule 2 walls off. |
| Transport self-check | N/A — **no paid calls made** (the fix was ruled out on $0 local evidence before any attestation). |
| Total spend | **$0.00** (≤ $0.90 cap). No attestation of a non-fix. |
| Probe set | `eval/results/gold_reference_set.csv` (frozen-40, human-reviewed; 34 in-scope) joined to `eval/results/filler_v5_route_bands.json`. |
| Machine-readable evidence | `eval/results/filler_v5_phase2_gate_sweep_2026-07-24.json` (per-query routes, correctness, full sweep). |

---

## 1 · What Phase-2 set out to do, and what the data said
Goal: make **filler-2 (the TOPIC sentence)** fire on the live path **when — and only when — the routed topic is trustworthy** (precision = 0 wrong-topic fires, the hard constraint), by recalibrating/redefining the topic gate (`clean_margin >= TOPIC_MARGIN_THRESHOLD`, [filler_route.py:183](app/filler_route.py:183); threshold [config.py:622](config.py:622)).

The $0 measurement on the 34 in-scope gold queries showed the gate is not the problem — **the router is.** No threshold or signal recovers precision at usable recall, so per boundary rule 2 ("if filler-2 cannot hit the precision bar without routing changes, STOP and report") the fix is **not shippable** as a gate change.

## 2 · Core evidence — routing top-1 is 35% accurate and unseparable by confidence

**Topic-identification accuracy (in-scope, fresh route at HEAD):**

| Signal | Accuracy | 
|---|---|
| Centroid top-1 topic (what filler-2 would speak) | **12/34 = 35%** |
| Centroid theme-anchor (what filler-1 speaks) | 14/34 = 41% |
| Retrieval-derived topic (majority topic of selected docs) | **3/34 = 9%** |
| _(sanity)_ top retrieved **doc** ∈ gold_source_docs | 20/34 = 59% |

Document *retrieval* is fine (59%), but naming a clean *topic* is not: the centroid router is right ~1 in 3, and deriving the topic from the retrieved docs (via `topic_map` membership) is **worse** (9%) because topic membership is thematic/overlapping. There is no better topic signal available within scope.

**Gate precision/recall sweep (fire only if speakable & non-fallback & condition):**

| Gate | Recall | Precision | Wrong-topic fires |
|---|---:|---:|---|
| `margin ≥ 0.01` (current) | 21% | **57%** | B11, D20, X38 |
| `margin ≥ 0.015` | 15% | 80% | B11 |
| `margin ≥ 0.02` | 12% | 75% | B11 |
| `margin ≥ 0.025` | **6%** | 100% | none (n=2) |
| `margin ≥ 0.03` | 3% | 100% | 1 fire |
| `cosine ≥ 0.60` | 44% | **27%** | many |
| `cosine ≥ 0.62` | 24% | 12% | many |
| `margin ≥ 0.02 AND cos ≥ 0.62` | 3% | 0% | B11 |

**Margin does not separate correct from incorrect top-1** — wrong topics routinely carry *high* margins. The only precision=1.0 gate (`margin ≥ 0.025`) fires on **6% of in-scope queries (n=2)** — statistically fragile and demo-useless. Everything with usable recall speaks wrong topics.

**The wrong high-margin fires are demo-breaking** — filler-2 would put these in the retired Chief Justice's voice ("You ask, in particular, about …"):

| qid | margin | question | filler-2 would speak | (gold) |
|---|---:|---|---|---|
| B11 | 0.0206 | "Why should economic development inform judicial…" | **"Maritime Resources and Sovereignty"** | economic_governance |
| D20 | 0.0149 | "Who is eligible for FLP scholarships?" | **"The Foundation's Donors and Partners"** | foundation |
| X38 | 0.0120 | "…your work on both judicial reform…" | **"Economic Governance and Business Law"** | judicial_reform |

## 3 · Why the frozen-40 threshold (0.01) was mis-derived
`filler_v5_route_bands.json` derived `TOPIC_MARGIN_THRESHOLD=0.01` from the in-scope **margin distribution** (min 0.0, p50 0.004, max 0.030) — i.e. it was set to "where the margins are," **without ever measuring whether a high-margin route is correct.** The margin band and the correctness band are unrelated, so the derived threshold was doomed to be imprecise. This is a methodology gap, not a bad number: the fix cannot come from re-reading the same margin band.

## 4 · Task A/B (route race A1) — deliberately NOT fixed, and why
- **Could not confirm A1 in-app** (headless agent: no live mic, no browser AudioContext unlock — same limitation as Phase-1). The Phase-1 telemetry will populate `route_latency_ms` automatically on the next real `streamlit run`; that measurement is still owed.
- **More importantly, fixing A1 in isolation is net-negative right now.** A1's route-race loss currently forces the **safe NEUTRAL** filler ("Permit me a moment"). Fixing A1 would make the **themed** filler-1 fire — but theme-anchor accuracy is only **41%**, so it would speak the wrong broad subject 3 times in 5. The route-race "bug" is, by accident, protecting the demo. Fixing it is a **product decision gated on the same routing-accuracy prerequisite**, not a clean bug fix — so I left it unchanged.

## 5 · Recommendation (this is now a product decision for Dev0)
Both fillers that **name a subject** (topic *and* theme) are blocked on routing accuracy the system does not have. Options, in recommended order:

- **D — Redesign to a subject-free characterful filler (recommended for May 30).** Replace the named theme/topic openers with a small pool of always-safe, in-voice hedges that name *nothing* ("A fine question — let me consult my record for a moment."). More characterful than the bare NEUTRAL, zero misattribution risk, and **removes the routing dependency entirely.** $0, low-risk, demo-ready. Keep the pre-synth/deck/sequencer machinery; only the *text* changes.
- **A — Keep filler-2 OFF; accept NEUTRAL-only.** The current live behavior. Safe, already shipped, but bland (the "no perceptible filler" the smoke test saw is the router protecting the demo).
- **C — Routing-accuracy track (the real prerequisite, out of Phase-2 scope).** Only this unlocks a *named* filler. Would need its own session (improve centroid separation, or a reranker/classifier over the retrieved docs). Target: top-1 topic accuracy high enough that a confidence signal becomes precise.
- **B — Ship the `margin ≥ 0.025` gate (NOT recommended).** Technically precision=1.0 but fires ~6% (n=2) — fragile and effectively invisible; misrepresents "filler-2 works."

**I did not implement any of these** — D and A are product calls; B is not worth shipping; C is out of scope. Awaiting your direction.

## 6 · What changed / did not change
- **No code change.** `config.py`, `app/filler_route.py`, `app/voice_job.py` untouched — the gate is left as-is because no in-scope value makes it safe.
- **Added (evidence only):** this report + `eval/results/filler_v5_phase2_gate_sweep_2026-07-24.json`.
- Phase-1 telemetry and both tests (`scripts/verify_filler_v5.py`, `tests/test_envelope_never_spoken.py`) are untouched and still pass.

## 7 · Found, not fixed (carried forward)
- Routing top-1 accuracy 35% / theme 41% — the root blocker (Recommendation C).
- Frozen-40 threshold methodology (§3): thresholds must be derived from **correctness**, not the margin distribution.
- Carried from Phase-1: truncated-sentinel ENVELOPE leak; empty-NEUTRAL-pool `filler_missing_pool`; stale "warm makes Q1 fast" caption; H-B enqueue-vs-audible KPI.

## 8 · Evidence artifacts
- `eval/results/filler_v5_phase2_gate_sweep_2026-07-24.json` — per-query routes, correctness, full margin/cosine sweep, retrieval-topic comparison, machine-readable verdict.
- Probe set reused: `eval/results/gold_reference_set.csv` + `eval/results/filler_v5_route_bands.json` (both pre-existing, human-reviewed).
