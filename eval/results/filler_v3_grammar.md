# Filler v3 — discourse-role grammar — 2026-07-18

Fixes the incoherent clip chains heard in the smoke test (e.g. "…reflect on that. Yes let me
continue. Let me put it this way." = speech-connectors misplaced pre-speech). Wrapper/`voice_job`
only. Synthesis: 3 new onyx extenders, **$0.0015 actual** (approved ~$0.02). No composes.

## A — Role-typed the pool (`voice_job._role_of` by filename prefix)
| clip | text | old role | NEW role | action |
|---|---|---|---|---|
| ack_01..10 | (10 openers) | ack | **opener** | kept — audited, none imply prior speech |
| bridge_01 | "If I may add…" | stage-2 bridge | **resumption** | RETIRED from stage-2 (implies prior speech); file kept as `resumption_01` for future barge-in |
| bridge_03 | "Yes… let me continue." | stage-2 bridge | **resumption** | RETIRED → `resumption_02` (implies prior speech) |
| bridge_02 | "Let me put it this way." | stage-2 bridge | **leadin** | → `leadin_01` (hand-off, rule B.6) |

## A — 3 NEW extenders (onyx, synthesized) — extend the THINKING state, never imply speech
| id | text | duration |
|---|---|---|
| extender_01 | "A moment more, please." | 1.32 s |
| extender_02 | "Bear with me, I want to answer this properly." | 2.45 s |
| extender_03 | "Let me be sure I have this right." | 1.97 s |

(leadin_01 "Let me put it this way." = 1.18 s; resumptions 0.94 / 1.39 s — reserved, not in stage-2.)

## B — Sequencer (replaces the flat stage-2 deck)
- **Position 1** = opener deck (shuffled, no-repeat, 120 s idle-reset). Fires at transcript-confirm.
- **Positions 2..N** = EXTENDER deck only, per-turn no-repeat, cap `MAX_FILLERS_PER_TURN=3` then silence.
- **Leadin** = fires at first-content **submit** (so its index precedes content → plays before it),
  ~30 % of eligible turns, **never on consecutive turns**, and **only under streaming-TTS** (first audio
  ~sub-second, so content is buffered before the ~1.2 s leadin ends → the no-gap promise). With
  non-streaming tts-1 (~3 s synth) a leadin would gap, so it stays dormant (correct with current TTS).
- **Only these chains are constructible:** `O-C · O-E-C · O-E-E-C · O-[E]-L-C`. Resumptions never
  play pre-speech; no clip ever plays after content.

## C — Harness verification ($0, stubbed composes) — chains printed verbatim
Extender grammar (streaming off), TTFT 2/6/12/18 s:
```
TTFT= 2s  O-E-C     [O] Permit me a moment. [E] Bear with me, I want to answer this properly. [C] answer
TTFT= 6s  O-E-E-C   [O] Permit me a moment. [E] Let me be sure I have this right. [E] Bear with me… [C] answer
TTFT=12s  O-E-E-C   [O] Allow me a moment to reflect. [E] Let me be sure… [E] Bear with me… [C] answer
TTFT=18s  O-E-E-C   [O] Let me gather my thoughts. [E] A moment more, please. [E] Let me be sure… [C] answer
```
Leadin (streaming on, forced-due over 4 turns):
```
turn1  O-L-C   leadin fired, index BEFORE content
turn2  O-C     BLOCKED (consecutive-turn guard)
turn3  O-L-C   fired (2 turns since)
turn4  O-C     BLOCKED
```
Asserts PASS: every chain ∈ {O-C, O-E-C, O-E-E-C, O-L-C, O-E-L-C}; leadin index always < content
index (never plays after content, never unbuffered); no two adjacent leadin turns.

## Telemetry
`voice_job` job carries `chain` (e.g. ["O","E","E","C"]); the demo logs **`chain_pattern`**
("O-E-E-C") alongside `filler_clip_id / filler_fired_ms / stage2_fired / stage2_rate_running`.

## Leadin gate (v3.1) — streaming-gated; currently DORMANT
- **`STREAM_TTS_ENABLED` is OFF**, so the leadin never fires today. **Live chains are
  `O-C / O-E-C / O-E-E-C` only** (opener → extenders → content). The leadin (`O-[E]-L-C`) activates
  ONLY when the gate opens — i.e. when first-content audio is buffered fast enough that the ~1.2 s
  leadin doesn't outrun it (the no-gap promise). With hosted tts-1 (~3 s synth) that never holds, so
  the leadin is correctly dormant.
- **Delivery-week re-evaluation (robot):** Piper's ~2 s *local* synth (no network RTT) may satisfy
  the buffered-in-time condition **natively** — in which case the leadin gate can key on measured
  first-audio latency rather than `STREAM_TTS_ENABLED`. Config note: RI-701 should re-measure robot
  first-audio and, if < ~1 s, either enable streaming or add a `CJ_LEADIN_GATE=piper-local` mode that
  fires the leadin when the robot TTS buffers fast enough. Until then the gate stays streaming-only.
