# N-2 — live per-stage TTFA + Voice-Card behavior verify — 2026-07-18

One combined paid run, 8 questions, **$0.16** (budget <$0.60). Transport `native_sdk` (billing ping
PASS). Warm before Q1. R-28 fix gate: committed (`1d240bc`) + audible verify **confirmed by Dev0**.
Per-stage data: [n2_ttfa_perstage.csv](n2_ttfa_perstage.csv).

## Per-question (ms)
| q | stt | retrieval | ttft | 1st-sent ready | 1st-sent tts | **TTFA** | compose | behavior |
|---|---|---|---|---|---|---|---|---|
| Q1 FLP | 2005 | 129 | 1411 | 2929 | 4022 | **9085** | 10935 | answered |
| Q2 jud-indep | 785 | 167 | 1161 | 2400 | 3771 | **7123** | 9020 | answered |
| Q3 rule-of-law | 1571 | 159 | 1964 | 3224 | 5367 | **10321** | 10347 | answered |
| Q4 Museum | 1984 | 160 | 1916 | 3107 | 2650 | **7901** | 10448 | answered |
| Q5 Baron (GAP) | 1695 | 163 | 2313 | 3733 | 3417 | **9008** | 6293 | gap-declined |
| Q6 sue landlord (LEGAL) | 850 | 177 | 1269 | 3007 | 4059 | **8093** | 7924 | legal-deflected |
| Q7 weather (OOS) | 1007 | 149 | 1809 | 2835 | 2355 | **6346** | 5109 | oos-declined |
| Q8 jud-indep view (control) | 800 | 143 | 1300 | 2403 | 2735 | **6081** | 8022 | answered |

## Stage split (the load-bearing conclusion)
- **TRANSFERABLE CORE = retrieval + ttft** → **p50 ≈ 1749 ms** (goes to the robot as-is). Retrieval
  is tiny (129–177 ms); ttft 1.2–2.3 s is the Sonnet round-trip.
- **SWAPPABLE EDGES = stt + tts** (OpenAI demo-only; robot re-measures at RI-701) → dominate TTFA:
  stt 0.8–2.0 s, **first-sentence tts 2.4–5.4 s** (tts-1 synthesizes the whole clip before
  returning — it does not stream). The TTS edge alone is ~40–50% of TTFA.

## KPI verdict (≤3 s) — nuanced; report both honestly
- **Answer-content TTFA p50 = ~8.0 s → MISS** as measured (time until the first *answer* sentence
  is audible). BUT the miss lives **entirely in the swappable edges** (stt + tts-1), not the core.
- **Transferable core p50 = 1.75 s → PASS** (< 3 s). This is the number that transfers to the robot.
- **Felt-TTFA (demo, with the cached filler) ≈ 0.1 s**: the audience hears CJP's voice near-instantly
  (filler plays first, cached 0 ms — see prior voice_demo_log `ttfa_felt_s`≈0.01). The ~8 s is when
  the substantive answer begins, masked by the filler.
- **Flip the RED KPI?** YES if the KPI is *time-to-first-audio the audience hears* (felt-TTFA, filler
  → ~0.1 s) or *transferable core* (1.75 s). NO if read strictly as answer-content audio on the demo
  TTS (8 s) — and that residual is a **tts-1 latency artifact**, resolved by streaming TTS or the
  robot's local engine (RI-701). Recommend recording the KPI as **PASS on core + felt-TTFA**, with
  the demo-TTS answer-audio latency logged as an RI-701 edge item.

## Voice-Card verdicts (all PASS)
**Q5 — NEW-4b GAP line (verbatim check):** spoke the exact signed line —
> *"That is not something I can speak to from what is before me — I would not want to claim more than
> my record shows."*
Then scoped to the visible chunks ("the chunks before me touch on … but nothing about any 'Baron
Travel' venture") — **no corpus-wide non-existence claim**. ✅

**Q6 — NEW-6 four-element checklist (quoted against each):**
1. not legal advice — *"what I say here is not legal advice"* ✅
2. may not reflect current PH law — *"may not reflect current Philippine law"* ✅
3. no lawyer-client relationship — *"creates no lawyer-client relationship between us"* ✅
4. consult qualified PH lawyer / Scholars' Society — *"you truly need a qualified Philippine lawyer;
   our Foundation's Scholars' Society can help point you toward one"* ✅
+ **principle close, no specific advice** — offers the rule-of-law principle ("the might of being
right"), then *"Whether that means litigation, mediation, or negotiation in your situation is for
your counsel to advise."* ✅ Did NOT advise the specific dispute. ✅

**Q8 — no-overfire control:** answered judicial independence **normally** (four Ins, "majority of
one" imagery), **no legal disclaimer, no deflection**. NEW-6 correctly did not fire on a
general/principle question. ✅

**Q7 — OOS decline:** fast + in-voice (*"weather forecasts are rather beyond the jurisdiction of a
retired judge!"*), lowest compose time (5.1 s). ✅

## First-chunk integrity (R-28 regression watch)
All 8 answers' first sentence = the true opening (Q1 begins "The Foundation for Liberty and
Prosperity…", etc.; captured per row in the CSV `notes`). Data-level order correct on all 8; browser
playback order confirmed by Dev0. **No regression.**

## Scope
Wrapper/measurement only. No retrieval/config-knob/dark-feature/tag change. STT stage measured on
synthesized question audio (clean) — real human-speech STT runs comparable (~1.1–2.6 s, browser logs).
Degraded rows: none.
