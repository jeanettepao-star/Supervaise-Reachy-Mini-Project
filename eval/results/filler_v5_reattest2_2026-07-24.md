# Filler-v5 Phase-2c — re-attestation #2 (multi-turn)

**Date** 2026-07-24 · **Branch** `develop` @ `d54a19e` (Phase-2c fix). **Supersedes** `filler_v5_reattest_2026-07-24.md`
as the artifact Dev0 amends the W3.5 FINAL Felt-TTFA line from.

> **Standing protocol requirement:** single-turn or fresh-session testing cannot see this failure class.
> Re-attestation must be **8+ consecutive turns in one uninterrupted session, no page reloads**.

## Header

| Field | Value |
|---|---|
| Total spend | **$0.00** (≤ $0.75 cap). |
| Transport self-check | N/A — no paid calls. |
| Run mode | Headless: 8 **consecutive** `start_job` turns, accumulating `chunk_base` exactly as the host does; real local route, stubbed compose/TTS. |
| Evidence | `filler_v5_reattest2_2026-07-24.jsonl` (8 rows, all Phase-1/2/2c fields incl. `turn_state_reset`). |

## The limitation — what this run does and does NOT attest
This session is **headless**: it drives the Python pipeline (`start_job`) directly and **never instantiates
the browser gapless component**. So it attests the **Python-layer** invariants (index continuity across
turns, per-turn state reset, fire timing, watchdog behavior) — the parts where suspects **S2** and **S3**
were refuted. It **cannot attest that audio survives in the live browser across 8 turns**, because the
regression and its fix (base-clamp / context-resume / batched postback) live in the component, which only
runs in a real browser. **The live 8-turn audio-survival test is OWED** and is the true acceptance gate.

## Per-turn results (8 consecutive turns)

| Turn | base | chunk idx | fire_call | enqueue | turn_state_reset | watchdog fired | chain |
|---|--:|---|--:|--:|:--:|:--:|---|
| 1 | 0 | 0..2 | 0.0056 s | 0.01 s | ✓ | no | N-C |
| 2 | 3 | 3..5 | 0.0052 s | 0.01 s | ✓ | no | N-C |
| 3 | 6 | 6..8 | 0.0051 s | 0.01 s | ✓ | no | N-C |
| 4 | 9 | 9..11 | 0.0051 s | 0.01 s | ✓ | no | N-C |
| 5 | 12 | 12..14 | 0.0054 s | 0.01 s | ✓ | no | N-C |
| 6 | 15 | 15..17 | 0.0051 s | 0.01 s | ✓ | no | N-C |
| 7 | 18 | 18..20 | 0.0051 s | 0.01 s | ✓ | no | N-C |
| 8 | 21 | 21..23 | 0.0049 s | 0.01 s | ✓ | no | N-C |

**Global index space 0..23 — contiguous, no gap/overlap/duplicate.** Silent turns (Python layer): **0/8**.
Dead-air watchdog fired: **0/8**. `t_filler_fire_call` p50 **0.0051 s** / p95 **0.0056 s**. `turn_state_reset`:
**True on all 8**. `audible_onset_observable`: **False** (headless — no browser).

## Bisect verdict (full detail in `filler_v5_phase2c_bisect_2026-07-24.md`)
**S1** (browser component state loss) CONFIRMED as the class — but **commit 2 exonerated** (it added only a
field to the pre-existing per-item postback). **S2** (Python cross-turn hole) **REFUTED** (0..23 contiguous
above). **S3** (stale Python state) not a cause (`turn_state_reset=True`). Fix = branch A only: component
remount-recovery (base-clamp) + context-resume + batched postback + `base` passthrough.

## Before / after — **label the measurement basis**

| Metric | Phase-1 (ENQUEUE) | This fix (ENQUEUE, Python layer) | AUDIBLE basis |
|---|---|---|---|
| Filler fire-call p50 | — | **0.0051 s** | — |
| First audio enqueued p50 | 0.44 s | **0.01 s** | instrumented; **not captured** (needs live browser / stopwatch) |
| Silent turns, single-turn tests | 1 of 10 (the 9.79 s dead-air turn) | 0 (fixed in Phase-2) | — |
| Silent turns, **8 consecutive** (Python layer) | not tested | **0 of 8** | **live-browser test OWED** |

## Voiding note (mandatory)
- Any Felt-TTFA numbers taken from a **live session that went silent** after the first turns are **VOID** — a
  silenced session measures nothing.
- The **Phase-2 re-attestation** (`filler_v5_reattest_2026-07-24.md`) tested single turns headlessly and
  therefore **could not see this multi-turn failure class**; do **not** cite it for multi-turn audio survival.
- **This headless run does not attest browser audio survival either** — it attests the Python invariants only.
  Do **not** amend the KPI to a GREEN audible or multi-turn-audio number from any run to date.

## What Dev0 needs (two sentences for Dok)
"After the filler fix, a second bug made all audio die a couple turns into a session — the browser player kept
one global playback counter that couldn't recover when Streamlit re-created its frame. It now recovers per
turn (and resumes a suspended audio context), so it can't silently die mid-session — pending one live 8-turn
confirmation we couldn't run headlessly."

## Acceptance status
- 8+ consecutive turns, zero silent (Python layer) — **PASS (Python)**; **live-browser audio survival PENDING**.
- Felt-TTFA audible p50 ≤ 1.0 s — **PENDING** (audible unmeasurable headless; enqueue 0.01 s is a floor).
- Watchdog fires = 0 normal — **PASS** (0/8).
- Instrumentation not sacrificed; `audible_onset_observable:false` throughout this headless run → stopwatch for the live pass.
