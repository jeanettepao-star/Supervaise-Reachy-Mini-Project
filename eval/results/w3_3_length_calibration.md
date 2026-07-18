# W3.3-LITE — spoken-length calibration — 2026-07-18

One knob (Voice-Card length directive + `COMPOSER_MAX_TOKENS`). 4 anchors × 2 variants + 1 verify
compose = **~$0.23** (budget ~$0.25). Retrieval identical across variants (only the length directive
differs), so the grounding check is A-vs-B citation consistency + no fabrication.

- **A** = current (no concise directive, `max_tokens=640`).
- **B** = CONCISE directive ("4-6 sentences ~100 words, open short, depth over breadth; NEW-4b/NEW-6
  exempt") + `max_tokens=320` as trialed.

## Per-question
| q (kind) | words A→B | sentences A→B | out_tok A→B | spoken est A→B | cited A→B |
|---|---|---|---|---|---|
| E1 rule-of-law (easy) | 198 → **138** | 12 → 9 | 378 → 292 | 79s → **55s** | [CA031,SB028] → **same** |
| E2 jud-independence (easy) | 181 → **107** | 10 → 4 | 335 → 216 | 72s → **43s** | [BD005,BD006] → [BD005] (subset) |
| MS liberty↔prosperity (multi-chunk) | 204 → **116** | 11 → 6 | 401 → 244 | 82s → **46s** | [CB008,SB028,SB040,SD002] → [SA011,SB028,SD035] (valid re-selection, all in retrieved) |
| AR founding FLP (anecdote) | 229 → **167** | 12 → 10 | 484 → **320⚠** | 92s → **67s** | [6 docs] → **[] ⚠ envelope truncated** |

Averages: **A ~203 words / ~81s spoken → B ~132 words / ~53s spoken (~35% shorter).**

## Grounding grade
- **E1, E2, MS: PASS** — every B citation is within the identical retrieved set; no fabrication.
  MS's different picks are a valid re-selection from the same 6 retrieved docs (concise answer
  emphasized different real chunks), not a grounding break.
- **AR: the only defect** — B's concise prose ran 167 words ≈ **exactly the 320-token ceiling**, so
  the trailing ENVELOPE (citations) was cut → `cited=[]`. The **prose is complete and grounded**
  (ends "…Mabuhay!"), but citation tracking is lost. This is a **`max_tokens=320` problem, not a
  directive problem**.
- **Fix verified:** concise directive @ **`max_tokens=480`** → AR = 189 words, out_tok 394,
  **cited=[CB006,SB028,CB005,SB040,SD016] recovered**. 480 fits prose + envelope on the worst-case
  anecdote with headroom.

## Reads in-voice? YES (not clipped)
- **E2/B (107w, 4 sents):** lands the key facts + persona markers — *"plague of ships"*, *"majority
  of one"*, the four Ins, the biased-referee analogy. Complete, natural.
- **AR/B (189w @480):** twin beacons, Global Forum 2006, Metrobank/Tan Yan Kee/Ayala programs,
  Washington SyCip, *"unleash the entrepreneurial genius of our people"*, *"Mabuhay!"* — concise but
  rich; not clipped.

## DECISION — **B SHIPS**, at `max_tokens=480` (not 320)
Grounding holds (all prose grounded; citations within the retrieved set) AND the concise answers
read in-voice and land the key fact + a persona marker on every question. The only issue —
envelope truncation on the anecdote answer — is a ceiling artifact fixed by 480 (verified). Shipped:
- Voice Card: concise "Spoken-length directive (primary)" added atop the length section.
- `config.COMPOSER_MAX_TOKENS`: **640 → 480** (comment records the 320-truncation evidence; do not
  drop below ~440).
- NEW-4b / NEW-6 explicitly exempt from the length directive.

**N-1 / N-3 run on B as the shipping config.** Deviation from the spec'd 320 is deliberate and
evidence-backed (320 silently drops citations); Dev0 can override to 320 (accepting envelope loss)
or back to 640 if preferred. Scope: Voice-Card text + max_tokens only — no retrieval/knob/tag change.
