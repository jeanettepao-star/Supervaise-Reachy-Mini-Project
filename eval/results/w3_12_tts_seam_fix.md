# W3.12 — TTS first-chunk truncation fix (gapless playback ordering) — 2026-07-18

## Symptom
Voice demo (v4.2): the spoken answer to "What is the Foundation for Liberty and Prosperity?"
began mid-sentence ("…freedom and food…"), dropping the opening ("The Foundation for Liberty and
Prosperity…").

## Fork: TEXT complete → AUDIO layer (Part 2A, TTS seam)
| Evidence | Finding |
|---|---|
| On-screen composed text | Full opening present ("The Foundation for Liberty and Prosperity — the FLP — is an organization I established on my 75th birthday…") |
| `voice_demo_log.csv` last row | 15 chunks / 1335 tts_chars synthesized (whole answer); filler `0:0/0` (cached, played, gap 0) |
| "…freedom and food…" | Located in **chunk 3** ("Justice and jobs; freedom and food; ethics and economics…") |

→ Text was complete; the **audio played out of order**. Not a compose/stream/envelope bug.

## Root cause — `components/gapless_audio/index.html` `drain()` (from b2e5984)
`drain()` fired `decodeAudioData` for chunks 1,2,3… **concurrently** in a `while`-loop and called
`schedule()` inside each `.then()` — i.e. in **decode-completion order, not index order**.
Sentences synthesize out of order (chunk 3 synth 1340 ms < chunk 1 synth 3321 ms) and short clips
decode faster, so whichever decoded first grabbed `now+0.02` and played first. The first
substantive audio became chunk 3; the real opening (chunk 1) was scheduled later → heard as
"opening dropped / mid-sentence start."

## Fix (delivery layer only — no pipeline/retrieval/compose change)
`drain()` now decodes + schedules **strictly one chunk at a time in `expected` index order**
(single decode in flight, self-chaining). Guarantees in-order, complete playback while keeping the
gapless `nextStart` butt-join. `schedule()`/synth/prefetch untouched.

## Verification
- **Deterministic by construction:** playback order == `expected` == submission index (0=filler,
  1=opening, …). Out-of-order scheduling is structurally impossible now.
- **Audible confirmation is the human's** (browser Web-Audio playback order is not observable from
  a headless compose, so a paid re-compose would NOT verify this bug — it only re-generates the
  same chunks). No spend incurred. Re-test: hard-refresh (Ctrl+Shift+R), ask the FLP question — the
  spoken answer must begin "The Foundation…" and remain gapless between sentences.

## Status
W3.12 prefetch seam: **fix applied, ordering verified by construction; awaiting one human audible
confirm in-browser.** Scope: wrapper/TTS delivery layer only.
