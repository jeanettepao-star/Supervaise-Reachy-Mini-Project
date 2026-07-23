# Filler-v5 Option D — subject-free filler pool (implemented 2026-07-24)

Follows the Phase-2 STOP ([`filler_v5_phase2_STOP_2026-07-24.md`](filler_v5_phase2_STOP_2026-07-24.md)):
named theme/topic fillers are unsafe at the router's real top-1 accuracy (~35% topic /
41% theme). Option D removes the routing dependency entirely — the filler speaks a
characterful, in-voice hedge that **names nothing** — keeping all the deck/sequencer/
pre-synth machinery and changing only the **text** + a mode switch.

## What changed (surgical)
- **`app/filler_route.py`**
  - New `SUBJECT_FREE_MODE` flag (module const, env `CJ_FILLER_SUBJECT_FREE_MODE`, **default ON**).
  - `decide()` short-circuits to `{use_neutral: True, topic_gated: False, reason: "subject_free_mode"}`
    when the flag is on — the theme/topic gating code below is **preserved, inert**, for a future
    routing-accuracy track (Option C) that would flip the flag off.
  - `NEUTRAL_TEXTS` enriched 3 → **10** subject-free, in-voice, two-clause hedges (~2.8–3.8s at
    1.25×) that mask the content compose the way the theme clips did (the old neutral clips were
    0.74–1.44s — too short to mask).
- **`scripts/gen_v5_subject_free_clips.py`** (new) — regenerates the pool with tts-1 at 1.25×,
  clears stale clips, and syncs `filler_v5_clip_durations.json`. `python scripts/gen_v5_subject_free_clips.py`
  (onyx) or `--all` (every voice). `.mp3`s stay gitignored; the script makes them reproducible.
- **`scripts/verify_filler_v5.py`** — forces `SUBJECT_FREE_MODE=False` (so the 10 theme/topic cases
  still run) + a new subject-free assertion (confident route that *would* be T-P-C stays N-C).
- **`streamlit_voice_demo.py`** — stale "a themed opener fires" caption → "a brief spoken opener fires".
- **`eval/results/filler_v5_clip_durations.json`** — neutral entries re-synced to the new clips.

## Nothing was fixed that shouldn't ship
- **A1 (route race) intentionally left as-is.** In subject-free mode the filler no longer depends on
  the route resolving in time — whether the route wins or loses the 300 ms race, the clip is
  subject-free. So A1 is **moot** for the filler (verified: `route_got=True/False` both yield N-C).
- The named theme/topic path is untouched (inert behind the flag) for Option C.

## Verification
- `scripts/verify_filler_v5.py` — 10/10 theme/topic cases PASS (behavior-preserved) + subject-free
  assertion PASS.
- End-to-end ([`filler_v5_optionD_trace_2026-07-24.jsonl`](filler_v5_optionD_trace_2026-07-24.jsonl),
  real route/retrieve + real onyx clips + stubbed compose/TTS): **6/6 turns** (in-scope, red-lined,
  GAP, OOS) fire a subject-free clip — `chain=N-C`, `theme=NEUTRAL`, `topic=None`,
  `reason=subject_free_mode`, real clip bytes, durations 2.8–3.8s. Deck rotation gives variety
  (neutral_02/04/05/06/07/10, no repeats).
- Not run: live-mic Streamlit / audible playback (headless-agent limitation, as in Phase-1/2).
- Spend: **~$0.01** (10 onyx tts-1 clips). `.mp3`s not committed (gitignored).

## To revert to named fillers (Option C, after routing is fixed)
Set `CJ_FILLER_SUBJECT_FREE_MODE=0` (or `filler_route.SUBJECT_FREE_MODE=False`). The theme/topic
sequencer, decks, and gates are all intact — but do **not** flip it until top-1 topic accuracy is
high enough for a precise gate (see the Phase-2 STOP report).
