# Filler-v5 Phase-2c — multi-turn audio-death bisect + fix

**Issued** 2026-07-24 · **Branch** `develop` · builds on Phase-2 (`4a93651`, `7c884f7`). Commit 1 (`4a93651`) untouched.

## The honest constraint (read first)
The regression lives entirely in the **browser + live Streamlit runtime** (the gapless component,
the `AudioContext`, the rerun cycle). A headless agent has no browser and no live multi-turn
session, so the **empirical bisect (T1.1 live consecutive turns, T1.2 browser-console queue
autopsy) could not be run, and neither could the live audio-survival re-attestation.** The verdict
below is a **static bisect** — git history + code reading + a headless test of the parts that live
in Python. The browser-side fix's audio survival is **unverified** and owed a live 8-turn pass.

## Bisect verdict

| Suspect | Verdict | Evidence |
|---|---|---|
| **S1** — browser component state loss (AudioContext suspended / iframe remount) | **CONFIRMED as the failure class** — but **NOT introduced by commit 2** | see below |
| **S2** — cross-turn queue hole (Python index accounting) | **REFUTED** | 8 consecutive `start_job` turns produce a perfectly contiguous global index space **0..23, no gap/overlap/duplicate** (`tests/test_multiturn_continuity.py`, headless). The host's `chunk_base` accumulation is sound. |
| **S3** — stale turn state (Python) | **not a cause** | every turn is a fresh job dict → `first_chunk_ready_s` and the watchdog arm state start clean; `turn_state_reset=True` on all 8 turns. |

**Commit 2 is exonerated.** `git show 7c884f7 -- components/gapless_audio/index.html` shows commit 2
added **only a field** (`t_audible_epoch_ms`) to the **pre-existing** per-item `played` postback — it
added **no new `setValue` call**. So S1's stated premise ("commit 2 made the component post per item")
is factually wrong: the per-item postback (and its rerun churn) existed before Phase 2 and was
**surfaced by the new multi-turn usage pattern**, not introduced by commit 2.

**Root cause (static).** The gapless component holds **global, accumulating queue state**
(`expected`, `seen`, `pending`, `nextStart`, `ctx`) tied to a global index space. It works only while
the iframe persists AND indices stay contiguous — both of which the Python side guarantees within a
session. But if any rerun (the per-item postback is the churn source) **remounts the iframe**, the new
instance restarts at `expected=0` while the host's indices have climbed (e.g. 6+); `pending.has(0)` is
never true → `drain()` returns → **all audio dies permanently** ([components/gapless_audio/index.html:77-99](components/gapless_audio/index.html:77)).
A rerun that leaves `ctx` **suspended** produces the same silence (enqueues "succeed", nothing sounds).
This matches the reported timeline exactly: turn 1 plays on the gesture-blessed context, then a
perturbation desyncs and the rest of the session is silent.

## Fix — branch A (S1) only (per boundary 6; S2 refuted so branch B is absent)
- **Remount recovery (the load-bearing fix)** — [index.html](components/gapless_audio/index.html): the host passes the current turn's
  `base` index; the component clamps `expected` **forward** to `base` when `expected < base`, so a
  remounted/stale instance jumps to the current turn's chunks instead of waiting forever for indices
  that are never re-sent. Clamp is forward-only → within-turn holes (`expected >= base`) still wait
  for their fill (strict order + gaplessness preserved); in normal operation `expected == base` → no-op.
  Host passes `base` at [streamlit_voice_demo.py](streamlit_voice_demo.py) (`gapless(..., base=job["base"], key="gapless_player")`).
- **Context resilience (T2.3)**: `drain()` resumes a suspended `AudioContext` before scheduling.
- **Batched postback (T2.1)**: `setComponentValue` is debounced (`postPlayed()`, one post per ~tick)
  instead of once per scheduled chunk — fewer reruns, fewer remount triggers. Stable `key=` (T2.2) was
  already in place.
- **Task 5 resets**: the Python per-turn state already resets (fresh job dict); added `turn_state_reset`
  telemetry so multi-turn debugging can rule S3 out at a glance.

## Verification
- Python side (headless, verifiable): `tests/test_multiturn_continuity.py` — 8-turn contiguity + per-turn
  reset, PASS ×2. Regression: `test_deadair_watchdog`, `test_envelope_never_spoken`, `verify_filler_v5`
  (gated rollback) all PASS. Component JS parses (`node --check`).
- **Browser side (UNVERIFIED)**: the base-clamp / resume / batch changes cannot be exercised headlessly.
  The live 8-turn audio-survival test is the acceptance gate and is **owed** — see the re-attestation report.

## Found, not fixed
- The per-item postback churn is only *reduced* (debounced), not eliminated — a deeper redesign (turn-end
  batch) is deferred; the remount-recovery clamp makes it non-fatal regardless.
- compose-retry duplicate-emit, hardcoded model literals, dead `service._compose`, orchestration
  divergence — untouched.
