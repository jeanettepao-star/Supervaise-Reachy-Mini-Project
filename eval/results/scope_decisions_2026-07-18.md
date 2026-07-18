# Scope decisions — week of 2026-07-18 (ADR-lite)

Format per entry: **decision · rationale · revisit-trigger · decided-by**. These record
scope/gating calls; they change no code except the signed Voice-Card edits (Part B, NEW-4b + NEW-6).

## D1 — OPS-3 execution (34 → 44 topics)
- **Decision:** APPROVED in principle, **HELD until post-N-1**. Do not add topics / rebuild
  centroids / regrade / tag this week.
- **Rationale:** a centroid rebuild moves the production baseline; doing it now would shift the
  numbers under the pilot-report while N-1 is still being locked.
- **Revisit:** N-1 landed + pilot-report numbers locked.
- **Decided-by:** Dev0 (+ Dok/Pao promotion gate for the eventual tag).

## D2 — Entity-rescue
- **Decision:** stays **DARK** (`ENTITY_RESCUE_ENABLED=False`). Verified @ `8d2fd64`; promotion is
  a separate post-N-1 decision.
- **Rationale:** the mechanism is proven (recall held 0.588/0.882/0.941/0.971, OOS silent, no junk)
  but enabling changes payload behavior; keep production behavior byte-identical until promotion.
- **Revisit:** N-1 landed + 1 paid composer-utterance verify (Museum-of-Liberty case answers from CB004).
- **Decided-by:** Dev0.

## D3 — Date index + expand-on-demand
- **Decision:** both stay **DARK** this week. Fire-rate gates are defined; no enable.
- **Rationale:** neither is on the N-1 critical path; enabling adds behavior to verify under
  numbers that aren't locked yet.
- **Revisit:** post-N-1, as separate promotion decisions with their own verification.
- **Decided-by:** Dev0.

## D4 — NEW-2 remaining docx refreshes
- **Decision:** DEFERRED until post-N-1 (write once against final directive-ON numbers). PNG + board
  v6 already refreshed.
- **Rationale:** avoid re-cutting the docx twice; the final numbers land with N-1.
- **Revisit:** N-1 numbers final.
- **Decided-by:** Dev0.

## D5 — Embedder
- **Decision:** CLOSED (ADR-006, bge-base-en-v1.5, Dok-ratified). Not revisited absent a new hard
  constraint from robot-side measurement (RI-202).
- **Rationale:** bake-off ratified; changing the embedder would invalidate the frozen baselines.
- **Revisit:** a hard on-device constraint surfaced by RI-202 (robot audio/compute budget).
- **Decided-by:** Dok (ratified); Dev0 (scope).

## D6 — W3.4 fusion tuning
- **Decision:** NOT this week. Re-derive targets on v4.2 first; **B11 is an accepted cost, not an
  open defect**.
- **Rationale:** tuning against pre-v4.2 targets would chase a moved baseline; B11 (−2.9pt @1) is
  the ratified batch-02 BM25/IDF cost (v4.2 provenance).
- **Revisit:** post-N-1, once v4.2-based targets exist.
- **Decided-by:** Dev0.

## D7 — Decision B (pilot universe)
- **Decision:** RE-AFFIRMED. Pilot = **95 docs / 827 chunks**; out-of-pilot questions **decline by
  design** (NEW-4b); full-corpus reachability is **DEPLOY-1** (deployment scope), not a retrieval fix.
- **Rationale:** the eval universe is frozen; Baron Travel / GC006-class misses are subset-exclusion,
  owned by the allowlist/re-freeze decision (→ v5 at deploy), not the matching layer.
- **Revisit:** DEPLOY-1 (v5 universe re-freeze).
- **Decided-by:** Pao + Sheena (eval universe); Dev0 (scope).

## ROBOT NOTE — delivery moved to NEXT week; three docs pulled BACK into this week ($0)
- **Reversal recorded:** robot *delivery* is now NEXT week. Consequently three **documentation**
  items are **pulled back into this week** as $0 tasks (no hardware, no spend):
  - **RI-101** — Pollen protocol docs.
  - **RI-102** — audio / SDK spec.
  - **RI-301** — Service interface contract.
- **Rationale:** de-risk the robot seam on paper now while delivery slips a week; keeps the
  Service↔robot contract ready without blocking on hardware.
- **Revisit:** robot delivery week (next week).
- **Decided-by:** Dev0.

---

## Voice-Card sign-off provenance (Part B)
- **NEW-4b (GAP decline):** signed; verbatim line hard-coded into `corpus/voice/voice_card.md`.
  Replaces the prior "I have not written about that" examples and adds the "never claim
  corpus-wide non-existence" rule (closes baron_travel_forensics §6).
- **NEW-6 (legal-advice deflect):** **signed-off-by Atty. Rae + Sir Jacob, 2026-07-18**
  (Dev0-relayed). Carries the four elements (not legal advice · may not reflect current PH law ·
  no lawyer-client relationship · consult a qualified Philippine lawyer / Scholars' Society) +
  value-preserving principle close; general/principle questions still answer normally; **no
  pre-classifier, no new call**. NOTE: the proposal docx `CJP_VoiceCard_Proposal_NEW4b_NEW6.docx`
  is **not present in the repo**, so the sign-off is recorded as attested (Dev0-relayed), not
  cited to an on-disk signed artifact.

## Part B verification (this session, $0)
- Files changed: **`corpus/voice/voice_card.md` only** — zero config-knob changes, no
  retrieval/dark-feature/tag changes.
- Voice-card delta: **+1574 chars ≈ ~400 tokens** (above the ~150-250 estimate; the overage is the
  verbatim NEW-4b line + the four mandatory NEW-6 elements + one in-voice example — all required).
- **Still cached:** the voice card is the `cache_control: ephemeral` system block
  (`service.py` compose path); the edit causes one cache re-write, then re-caches. Boundary intact.
