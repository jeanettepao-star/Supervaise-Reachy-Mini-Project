# Filler-v5 Phase-2 fix — gate inversion + dead-air watchdog (Step-0 forensics + fix)

**Issued** 2026-07-24 · **Branch** `develop` · **Mode** surgical fix · builds on Phase-1 telemetry (`94c55b2`).

## Step 0 — forensics on the no-fire turn (recorded BEFORE the inversion makes it unreachable)

**The 9.79 s dead-air turn is NOT in `filler_v5_trace_2026-07-24.jsonl`.** That trace is
the Phase-1 headless harness (6 turns, questions 1–6). The failure is a **live-demo**
turn logged to `eval/results/voice_demo_log.csv` (2026-07-24T01:42:58) — it predates the
Phase-1 telemetry, so the rich trace schema (`route_latency_ms`, `warm_pipeline_ran`,
`compose_path`) was never captured for it. The available forensic row, verbatim:

```
timestamp=2026-07-24T01:42:58  mode=DEMO  transcript="Hi CJ, are you a robot?"
stt_seconds=8.69  ttfa_felt_s=9.79  status=answered  tts_chars=839
chunk_timings=0:3742/?;1:3219/?;2:1510/?;...   theme_used=NEUTRAL  route_confidence=0.0
topic_used=(empty)  topic_margin=0.0  cache_hit=(empty)  fallback_used=True
silence_gap_ms=(empty)  queue_reserved=9  queue_submitted=9  queue_released=0
watchdog_backfills=0  chain_pattern=C  notes=(empty)
```

Mapped onto the Phase-2 schema (inferred, since the fields weren't logged then):
`gate_reason` ≈ **late_route** (route_confidence=0.0 is the `ri is None` literal branch) ·
`filler2_absent_reason` ≈ theme_gate_failed:late_route · `q2_watchdog_fill_fired`=**false**
(watchdog_backfills=0) · `compose_path`=normal (status=answered).

**Root-cause reading (one paragraph).** `chain_pattern=C` means the first enqueued chunk
was **content** (index 0), i.e. **no filler clip was placed at all** — not merely delayed.
`fallback_used=True` (the decision was "use NEUTRAL") but there is **no `N` in the chain**,
which happens only when `theme_decks["NEUTRAL"].deal()` returns `None` → the selected
voice's NEUTRAL pool was **empty** → `job["filler_missing_pool"]=True` and nothing is
enqueued. Implicated path: [app/voice_job.py:475-476](app/voice_job.py:475) (legacy gated
fillers: `if clip: _push(...) else: job["filler_missing_pool"] = True`). This is compounded
by a **late route** (route_confidence=0.0) — the fillers thread had waited out
`FILLER_ROUTE_WAIT_MS` before even reaching the empty deck. So two independent contributors:
(1) empty NEUTRAL pool for the selected voice, (2) route lost the 300 ms race. **The data is
somewhat ambiguous** (the definitive fields weren't logged), but both readings point to the
same class: *the filler can fail to enqueue anything, leaving the raw content path exposed.*

**Why the fix is class-removing, not point-fixing.** (a) The **empty-pool** cause is already
mitigated — all 6 voices now have clip pools (commit `cc25e13`). (b) The **route-race** cause
is removed by the gate inversion (Task 1): the clip fires before routing. (c) Any **residual**
fire failure (exception, still-empty pool) is caught by the dead-air watchdog (Task 2), which
force-enqueues a clip — or, in the last resort where no clip exists, a silent backfill that at
least advances the player. Silence stops being a reachable turn outcome.

## Task 1 — Gate inversion ([app/voice_job.py:455-490](app/voice_job.py:455))
`FILLER_FIRE_MODE=unconditional` (new default, [config.py](config.py)): at transcript-confirm
the fillers thread deals a subject-free clip from the NEUTRAL deck and enqueues it
**immediately**, with zero dependency on route result, router margin, topic cache, or
content-readiness. The only pre-check is `first_chunk_ready_s is None` (audio not already out).
The fire is wrapped in try/except → an exception sets `filler_fire_exception` and degrades to
the watchdog, never a crashed turn. Shuffled-deck rotation is reached from the same
`theme_decks["NEUTRAL"].deal()` (no reimplementation). The legacy route-then-decide path is
preserved verbatim below the branch and reachable via `FILLER_FIRE_MODE=gated` — the demo-week
rollback lever. New trace fields: `fire_mode`, `t_filler_fire_call`, `filler_fire_exception`;
`gate_decision` logs `"bypassed"` on this path.

## Task 2 — Dead-air watchdog ([app/voice_job.py:609-648](app/voice_job.py:609))
An independent thread armed at transcript-confirm, disarmed by the first enqueue of any audio
or by turn end. If nothing is enqueued by `t_confirm + DEADAIR_WATCHDOG_MS` (default 800 ms), it
force-enqueues a neutral clip. It lives **outside** the `fillers()` try-scope, so it fires even
if the fire path threw. Idempotent: the check-and-fill is atomic under `res_lock` (the clip is
dealt *before* taking the lock to avoid an AB/BA deadlock with the fire path's Deck→res_lock
order); if audio arrived first it is a no-op. Disarmed on `job["done"]`. New trace fields:
`deadair_watchdog_armed`, `deadair_watchdog_fired`. A firing in production is a defect signal —
that sentence is a comment at the fire site.

**Test:** `tests/test_deadair_watchdog.py` — (A) fire throws → watchdog backstops within timeout;
(B) normal fire → watchdog silent, exactly one filler chunk; (C) race → no double filler. Passes
deterministically twice. `scripts/verify_filler_v5.py` (gated path) and
`tests/test_envelope_never_spoken.py` still pass (regression).

## Found, not fixed (per boundary 3)
- compose-retry duplicate-emit; hardcoded `whisper-1`/`tts-1` literals; dead `service._compose`;
  two-orchestration divergence; stale docs — all untouched.
- H-B audible-onset: addressed by Task 3 (commit 2), see the re-attestation report.
- Legacy gated path's own late-route→NEUTRAL behavior is intentionally left intact (rollback).
