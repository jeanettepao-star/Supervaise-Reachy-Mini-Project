# Taxonomy expansion PROPOSAL — OPS-2 Phase D ($0, read-only census) — 2026-07-17

**Status: PROPOSAL ONLY. No taxonomy, topic_map, or runtime changes applied.**
Data: [ops2_orphan_census.json](ops2_orphan_census.json) · centroids/embeddings: post-OPS-2
full-corpus artifacts (corpus_dense 9,865×768 bge-base; 34 full-corpus member-mean centroids).
Owners: Sheena/Pao (curation), W3.x (taxonomy evolution per PLAN-0007).

## 1. Headline: the curated map covers 5% of the corpus

Of **1,109 docs** with chunks, the hand-curated `topic_map.json` assigns topics to **56**
(79 unique doc_ids are listed; 23 of them have no chunk-bearing doc). **1,053 docs (95.0%)
are topic-orphans.** The Baron Travel finding (GC006 "belongs to NO topic") is therefore
**the norm, not an anomaly**: for 95% of the corpus the soft-prior arm contributes no
topic affinity and retrieval rides on dense+BM25 alone. (C0/C1 confirm the pilot eval is
unaffected — the pilot's gold docs are curated members — but any full-corpus universe
expansion will be operating mostly in soft-prior-blind territory until the map grows.)

## 2. Census mechanics (how to read the numbers)

- Doc vector = unit-mean of the doc's chunk vectors from the new `corpus_dense.npy`.
- **Adoptable bar** = cosine to nearest *real* centroid ≥ **0.854** — the p5 of curated
  members' cosine to their own topic centroid (i.e., at least as close as the weakest 5%
  of curated members). Distribution reference: member p25 = 0.889, p50 = 0.909.
- The two **gmean-fallback centroids** (`honors_received`, `robot_identity_meta` — zero
  member chunks, centroid = corpus mean) are **excluded** from nearest/adoption math:
  every generic doc scores ~0.95 against the corpus mean, so including them fabricates
  hundreds of false adoptions (measured: +338 before exclusion).
- New-topic pool clustered by k-means (k=21 by cosine-silhouette sweep; silhouette 0.102 —
  **weak separation, treat clusters as drafting aids, not ground truth**).

## 3. Adoptable into EXISTING topics: 557 docs

Top adoption targets (full lists with per-doc cosines in the census JSON):

| Existing topic | +docs | Existing topic | +docs |
|---|---|---|---|
| constitutional_doctrine | +187 | international_law_disputes | +27 |
| with_due_respect_persona | +50 | mentors_and_legal_lineage | +26 |
| faith_journey | +37 | rule_of_law | +21 |
| supreme_court_history | +34 | bar_exam_and_legal_education | +16 |
| icc_and_duterte | +31 | impeachment_accountability | +29 |

`constitutional_doctrine` absorbing 187 docs suggests it is functioning as a catch-all;
several of the new-topic clusters below would relieve it.

## 4. Needs a NEW topic: 496 docs in 21 clusters

Proposed consolidation into **10 candidate topics** (cluster ids from the census JSON):

| # | Candidate topic | Clusters | ~docs | Sample content |
|---|---|---|---|---|
| 1 | criminal_justice_and_prosecutions | C00, C19 | 101 | Revilla bail, plunder evidence, bank-deposit secrecy, Ligot acquittal |
| 2 | elections_comelec_and_candidacies | C04, C06, C07, C10 | 91 | BBM COC cases, Grace Poe citizenship, 2022 races, voter education |
| 3 | constitutional_reform_and_structure | C01, C17 | 53 | Cha-cha/federalism, DAP/PDAF budget doctrine, party-list reform |
| 4 | judicial_process_wdr_columns | C02, C09 | 59 | With Due Respect Vols. 2–3 chapters, JBC transparency, court procedure |
| 5 | governance_economy_and_democracy | C03 | 29 | ASEAN competitiveness, democracy-and-capitalism columns |
| 6 | us_politics_and_global_democracy | C05 | 27 | Trump elections/impeachment, SCOTUS-POTUS |
| 7 | judiciary_history_and_tributes | C08, C12 | 37 | CJ centenary material, eulogies/philanthropy tributes (overlaps `eulogies_and_passing`) |
| 8 | science_health_and_bioage | C11, C20 | 28 | Bio-Age book, stem cells, longevity/aging columns |
| 9 | leadership_formation_and_civic_service | C16 | 14 | Student activism, Rotary, FEU ambition — **includes GC006 (Baron Travel)** |
| 10 | church_and_sacred_spaces + christ_essays | C15, C18 | 27 | Manila Cathedral series; Christ-centered essays (or extend `faith_journey`) |

C13 (AI in justice, 15 docs) and C14 (West PH Sea, 15 docs) sit close to existing
`ai_and_technology` / `international_law_disputes` (cos 0.92–0.94) — recommend **adoption
review** rather than new topics.

## 5. Broken existing topics (fix regardless of expansion)

- **honors_received**: its only curated members (CC011, CE006) have **no chunk-bearing
  bodies** → the topic has a corpus-mean placeholder centroid. Re-point to chunked honors
  docs (candidates in the census adoption lists) or retire it.
- **robot_identity_meta**: zero members by design (meta/persona topic). If intentional,
  consider excluding it from the router's soft-prior instead of carrying a corpus-mean
  centroid that (until this census masked it) attracts everything.

## 6. Baron Travel closure (GC006/GC027)

- **GC027** *Lawyer in the Marketplace*: **adoptable** (nearest `philippine_political_landscape`,
  cos 0.880) — no new topic needed.
- **GC006** *Independence by Design*: not adoptable (best real-topic cos 0.801); clusters
  with the leadership-formation docs (candidate #9), which is a **cleaner home than the
  "entrepreneurship" bucket guessed in the forensics** — the doc's substance is
  independence/leadership, with Baron Travel as the vehicle. The existing
  `msme_and_entrepreneurship` centroid does not attract it.

## 7. Recommended sequence (all human-gated)

1. Fix the two broken topics (§5) — cheapest, unblocks honest soft-prior behavior.
2. Review + apply the 557 adoptions (batch by topic; per-doc cosines in the JSON).
3. Ratify a subset of the 10 candidate topics (§4) and curate their doc lists.
4. Re-run Phase B (one command: `build_centroids_fullcorpus.py`) after any map change;
   re-run the drift harness (`run_ops2_c1.py <label>`) to confirm pilot stability.

*Generated from ops2_orphan_census.json; clusters are k-means drafts (silhouette 0.102) —
titles were reviewed by eye for the consolidation above, but membership lists need human
curation before any map edit.*
