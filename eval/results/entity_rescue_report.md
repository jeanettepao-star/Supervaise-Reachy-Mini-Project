# Entity-rescue fix — deterministic exact-entity reachability ($0, ships DARK) — 2026-07-18

**Goal:** guarantee that an exact curated-entity match (atomic phrase like "Museum of Liberty
and Prosperity") reaches the composer instead of being buried by RRF fusion / soft-prior / the
top-p cutoff. Ships **DARK** (`ENTITY_RESCUE_ENABLED=False`); production behavior is byte-identical
until promoted. **Baron Travel is NOT the target** — GC006 is subset-excluded from the v4 pilot
(f961ca3), so no matching-layer fix can reach it; this mechanism is what it will need once a v5
re-freeze puts GC006-class docs in the searched universe.

## In-pilot burial case chosen (the analog to Baron Travel)
Hunt over distinctive in-pilot curated phrases wrapped in natural questions found **105 burials**.
Chosen demonstrator: **"Museum of Liberty and Prosperity" → CB004** (a flagship FLP entity; the
chunk CB004::c002 directly describes it: *"Interactive Museum of Liberty and Prosperity to be
built in partnership with the Supreme Court…"*).

| query | container | sparse rank | fused rank | nucleus kept | in payload (before) |
|---|---|---|---|---|---|
| "what can you say about the Museum of Liberty and Prosperity" | CB004::c002 | — | **9** | 8 | **NO (buried)** |

## The fix — deterministic rescue at the fusion boundary
1. **Trigger (analyzer-normalized).** The query is run through the SAME analyzer used at index
   time (`sparse.tokenize`: NFKC→lower→collapse-ws→greedy longest phrase match). Any token that is
   a curated **≥2-word** phrase_key is an exact-entity hit. Before/after on the demo:
   - raw: `What can you say about the Museum of Liberty and Prosperity?`
   - normalized: `what can you say about the museum of liberty and prosperity?`
   - word_units: `[what, can, you, say, about, the, museum, of, liberty, and, prosperity]`
   - tokenized: `[…, the, «museum of liberty and prosperity»]`  ← 5 words collapse to 1 atomic token
   - phrase_hit: `['museum of liberty and prosperity']`
2. **Distinctiveness bar (`ENTITY_RESCUE_MAX_DOC_FREQ=25`).** Only rare ENTITIES rescue; common
   doctrinal phrases are already well-served and must not fire. Measured corpus doc-frequencies:
   distinctive entities top out ~24 (museum=4, Baron Travel=7, Roe v. Wade=4, data privacy act=3,
   prosperity fund=11, ICC=20, arbitral award=24); common phrases start ~45 (international law=45,
   FLP=54, "with due respect"=137, "due process"=124, "rule of law"=145, "the Philippines"=347,
   "the Supreme Court"=706). The default 25 sits in that gap. **Effect: rescue firing on the 34
   in-scope anchors dropped from 19 → 8, dropping exactly the common-phrase fires.**
3. **Injection (bounded, append-only).** Container chunks (exact atomic-token match, read from the
   BM25 per-doc term table, restricted to the searched universe) that are not already kept are
   ranked by their existing fused score; the top **N=2** are APPENDED to the nucleus (never
   replacing a normal chunk) and forced into the payload (`build_payload` is rescue-aware). Deduped.

## Verification (mandatory gates)
| Gate | Result |
|---|---|
| **Demo surfaces (step 4, retrieval)** | rescue ON → CB004::c002 injected into `selected` AND payload; OFF → absent. Diag: `fired, phrase="museum of liberty and prosperity", injected CB004::c002`. |
| **40-anchor recall holds (step 5)** | recall @1/@5/@sent/@10 = **0.588 / 0.882 / 0.941 / 0.971** — identical to canonical v4 (structurally invariant: rescue appends to the payload, never alters the ranked order that grading reads). |
| **No junk (step 5)** | rescue fires on 8/34 anchors; every injected chunk is a genuine exact-entity container (several are gold: D21→SD002/SC007, E25→CA009, E28→CE007). Zero off-entity injections. |
| **OOS silence (step 6)** | X35 "weather in Manila" and X36 "restaurant near the museum" → phrase_hits=[], rescue_fired=False. The adversarial bare "museum" in X36 correctly does NOT match "museum of liberty and prosperity". |
| **Dark no-op** | `ENTITY_RESCUE_ENABLED=False` → selection set + order + payload byte-identical to arch-baseline-v4; diag=None. |

## Not closed at $0 (needs a paid call — gated)
Step 4's **composer utterance** ("answers from CB004 with a real citation") requires one live
Sonnet call, which the task's `$0, no API` boundary excludes. The retrieval precondition is proven
($0): CB004::c002 — which directly describes the museum — is in the payload, so the composer has
the grounded material to cite. Structural fabrication argument: rescue only ADDS on-entity,
exact-match container chunks (append-only), so it can only increase grounded material, never
introduce fabrication; the OOS decline path is untouched (rescue stays silent there). A one-query
paid confirmation is available on request/credit.

## Files (fix shipped DARK; promotion = flip the default, a SEPARATE decision)
- `config.py` — `ENTITY_RESCUE_ENABLED` (False), `ENTITY_RESCUE_TOP_N` (2), `ENTITY_RESCUE_MAX_DOC_FREQ` (25).
- `app/sparse.py` — `query_phrase_hits`, `chunks_with_phrase`, `phrase_doc_freq`.
- `app/retrieval.py` — rescue at the fusion boundary in `retrieve()` (diag under `cutoff.entity_rescue`).
- `app/service.py` — rescue-aware `build_payload` (additive; guarantees rescued chunks survive top_k).
No index/config artifact was rebuilt or promoted; no embedder/centroid/MIN_K/cutoff/lambda/taxonomy change.
