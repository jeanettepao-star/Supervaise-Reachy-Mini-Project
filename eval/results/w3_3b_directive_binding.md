# W3.3-B — make the concise directive BIND (directive strengthening) — 2026-07-18

6 composes, ~$0.13. **max_tokens stays 480** (safety ceiling only). One knob: Voice-Card length text.

## Problem (from n1_verification_run)
The concise directive was inert at 480 — in-scope **p50 198 words** (target ~100-130); first sentence
p50 24 words (the "short opener" also inert). Cause: the length rule was buried at line 328 of a
400-line card AND the bands right below still licensed "up to 150 words."

## Fix applied — S1 (PROMINENCE + FORCE); S2/S3 not needed
1. Added a **`## ⚠ HARD LENGTH RULE`** block at the **TOP** of the card (right after the intro,
   before Identity): *"Exactly 4-6 spoken sentences, ~100-130 words. FIRST sentence under 10 words.
   One key point made well; never survey everything. Stop when the point lands."* NEW-4b/NEW-6 exempt.
2. Repointed the buried directive to the hard rule (removed the soft "depth over breadth" version).
3. **Killed the contradicting license** — the "Up to 150 words for … anecdotes" band → "**130 words
   is the absolute ceiling**, even walk-throughs/anecdotes."

## Verify (4 composes: easy, multi-chunk, anecdote, legal-adjacent control)
| q | kind | words | 1st-sent words | cited (fab) | hit gold |
|---|---|---|---|---|---|
| A1 | easy | 136 | 17 | CA031, SB028 (0) | ✓ |
| B12 | multi-chunk | 112 | 10 | CB008, SB028, SD016 (0) | ✓ |
| D24 | anecdote | 110 | 7 | SB040, CB005, CC006 (0) | ✗* |
| CTRL | legal-adjacent | 122 | 9 | BD005 (0) | n/a |

\* D24 cited within the retrieved set (no fabrication); its gold docs (SB050/SD035/SD016) are a
curation choice — the answer is grounded and on-topic.

- **words p50 = 117** (was 198) → **in 100-150 ✓ PASS.** All 4 within band.
- **first sentence: mean ~10.75 words** (was 24) — big improvement; **2/4 strictly <10** (A1=17,
  B12=10 miss). The "under 10" opener is mostly, not perfectly, binding. Minor residual — S2's
  escalation trigger (p50 still >150) was NOT met, so no further step taken.
- **Envelope INTACT** on all non-control (citations present, all in retrieved set). **Fabrication 0.**
- **Reads in-voice ✓** (side-by-side below). **NEW-6 control answered normally** (no false deflect).
- **Filler-sizing update:** first-sentence synth p50 = **3460 ms** (~unchanged from N-1's 3477 ms).
  Shorter openers DO synth faster (D24 7-word → 3557 ms) but **tts-1 has a ~3 s floor** regardless —
  the filler still needs to bridge ~3-3.5 s. Length reduction did not move this floor.
- **Prefix delta:** +446 chars (~112 tokens); voice card stays the `cache_control: ephemeral` system
  block (one cache re-write, then cached).

## Side-by-side (anecdote — "Why did you establish the foundation?")
**Before (N-1, @480, directive inert): ~189 words.**
**After (S1, 110 words):**
> Liberty without prosperity is an empty promise.
>
> When I retired from the Court in December 2006, I saw that our Constitution, born from centuries
> of struggle against foreign domination, had given primacy to liberty — but prosperity, justice and
> jobs, freedom and food, had been treated as mere aspirations rather than enforceable rights. In my
> humble opinion, one is useless without the other. So on my 75th birthday in 2011, I organized the
> Foundation for Liberty and Prosperity to give equal primacy to those twin beacons — through
> professorial chairs, legal scholarships, and dissertation contests — planting the philosophy where
> it matters most: in the next generation of lawyers. Cheers!

Lands the key facts (2006 retirement, twin beacons, 75th-birthday founding, three programs) + persona
markers ("in my humble opinion," "Cheers!") in 110 words with a 7-word opener. In-voice, not clipped.

## Verdict
S1 SHIPS. words p50 198 → 117; envelope intact; fabrication 0; in-voice; NEW-6 unaffected. Residual:
first-sentence "under 10" is ~2/3 binding (cosmetic; tts-1 floor caps the filler-sizing gain anyway).
No tag (v4.1 stands; this is config lineage on top). max_tokens unchanged at 480.
