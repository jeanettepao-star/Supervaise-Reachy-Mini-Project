# Filler-v5 Phase-2 fix — re-attestation (gate inversion + dead-air watchdog)

**Date** 2026-07-24 · **Branch** `develop` · builds on commit 1 (`4a93651`, gate inversion + watchdog).
**This is the artifact to amend the W3.5 FINAL Felt-TTFA line from.**

## Header

| Field | Value |
|---|---|
| Total spend | **$0.00** (≤ $0.50 cap). Fire/watchdog behavior is fully demonstrable at $0; the one paid-run-only metric (audible onset) is unmeasurable headless regardless of spend — see below. |
| Transport self-check | N/A — no paid calls (no Anthropic/OpenAI network timing measured). |
| Run mode | Headless harness: real local route/retrieve + stubbed compose/TTS, `FILLER_FIRE_MODE=unconditional`, text-injected at the confirm boundary (STT is upstream of it). 8 turns. |
| Evidence | `eval/results/filler_v5_reattest_2026-07-24.jsonl` (8 turns, all Phase-1 + Phase-2 fields). |

## Method & the one limitation
Same question set as the Phase-1 re-run (6: foundation, book·red-lined, rule-of-law, recognitions·red-lined,
GAP, OOS) **plus 2 fault-injected turns** (the NEUTRAL deck's `deal()` forced to throw) to exercise the
dead-air watchdog. **Audible onset could not be measured** — a headless agent has no browser to run the
gapless component / AudioContext. The audible-onset instrumentation is shipped (commit 2) but its live
capture and the R-28 stopwatch cross-check are **still owed a human-at-the-demo pass** (`audible_onset_observable`
is `false` in every row of this run). Enqueue and fire-call are real.

## Per-turn results

| Turn | class | fire_mode | t_filler_fire_call | enqueue (first audio) | watchdog armed/fired | chain | audio? |
|---|---|---|--:|--:|---|---|:--:|
| 1 | in-scope | unconditional | 0.0061 s | 0.01 s | armed / no | N-C | ✓ |
| 2 | in-scope red-lined | unconditional | 0.0067 s | 0.01 s | armed / no | N-C | ✓ |
| 3 | in-scope | unconditional | 0.0054 s | 0.01 s | armed / no | N-C | ✓ |
| 4 | in-scope red-lined | unconditional | 0.0052 s | 0.01 s | armed / no | N-C | ✓ |
| 5 | GAP | unconditional | 0.0055 s | 0.01 s | armed / no | N-C | ✓ |
| 6 | OOS | unconditional | 0.0066 s | 0.01 s | armed / no | N-C | ✓ |
| 7 | **fault** (fire throws) | unconditional | 0.0052 s | **0.81 s** | armed / **FIRED** | **W-C** | ✓ |
| 8 | **fault** (fire throws) | unconditional | 0.0053 s | **0.81 s** | armed / **FIRED** | **W-C** | ✓ |

p50/p95 — `t_filler_fire_call`: **0.0055 / 0.0067 s** · enqueue (normal turns): **0.01 s** · enqueue (fault, watchdog backstop): 0.81 s (= `DEADAIR_WATCHDOG_MS`).

## Before / after — **read the measurement basis, the two are NOT the same event**

| Metric | Phase-1 (ENQUEUE basis) | This fix (ENQUEUE basis) | AUDIBLE basis (H-B corrected) |
|---|---|---|---|
| Filler fire call → | not measured | **0.0055 s p50** (unconditional) | — |
| First audio **enqueued** (felt-TTFA proxy), filler fired | 0.44 s p50 (N=9) | **0.01 s p50** (normal turns) | instrumentation shipped; **not yet captured** (needs live browser / stopwatch) |
| Silent / no-fire turns | **1 of 10** (the 9.79 s `chain=C` dead-air turn) | **0 of 8** | 0 (silence is no longer reachable) |
| Worst-case felt-TTFA | **9.79 s** (no filler → raw content path) | none (watchdog backstops at ≤ 0.81 s) | — |
| Dead-air watchdog fires (normal op) | n/a | **0 / 6** | — |

**Enqueue-basis is directly comparable Phase-1 ↔ now: 0.44 s → 0.01 s p50, and the 1-in-10 silent turn is
eliminated** (the gate inversion removes the 300 ms route-wait; the watchdog removes the residual failure
class). The **audible** column is the H-B correction the W3.5 KPI actually needs — the browser postback that
enables it is now in place (commit 2), but audible seconds require a live-demo capture I could not run
headlessly. Audible ≈ enqueue + AudioContext scheduling, so with enqueue at 0.01 s the audible p50 ≤ 1.0 s
target is very likely met, but **that must be confirmed with the stopwatch/live pass before the KPI is
re-attested GREEN**.

## Acceptance check
- Filler audio on **every** turn (fire or watchdog) — **PASS** (0/8 silent).
- `felt-TTFA audible p50 ≤ 1.0 s` — **PENDING** (audible unmeasurable headless; enqueue p50 = 0.01 s is a
  supporting floor). Owed: live-browser capture or R-28 stopwatch.
- Watchdog fired 0 times in normal operation — **PASS** (0/6). Fault turns fired 2/2 (injected — proves the net).

## For Dev0 (amending the W3.5 FINAL)
The old KPI line was an **enqueue** number presented as felt audible (H-B). Two honest options: (a) restate
it as an enqueue metric (now 0.01 s p50, 0 silent turns), or (b) hold the audible line until the stopwatch/
live-browser pass fills `t_filler1_audible_s` in `voice_demo_log.csv` (columns now exist). Do **not** amend to
a GREEN audible number from this run — it does not contain one.
