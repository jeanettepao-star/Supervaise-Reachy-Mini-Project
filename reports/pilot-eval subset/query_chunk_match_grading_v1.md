# Query ↔ Top-Chunk Match Grading — draft_queries_v1.json

**Method:** Each query's 5 tagged `top_chunk_ids` were resolved to their actual
text in `corpus/index/chunks.jsonl` (142/142 unique chunks found, no dangling
IDs) and read against the query. Verdict = does the retrieved evidence let you
answer the query.

- **PASS** — top chunks on-topic, query well grounded
- **PARTIAL** — some relevant, lead chunk drifts, or specific fact absent
- **FAIL** — top chunks do not address the query
- **OOS** — out-of-scope query that *should have been refused*
- **N/A (identity)** — grounding not meaningful (handled at composition)

## Scoreboard

| Verdict | Count | Query IDs |
|---|---|---|
| PASS | 15 | A1, A6, B7, B9, B11, C13, D19, D20, D21, D23, E25, E26, E27, X37, X40 |
| PARTIAL | 18 | A2, A4, A5, B8, B10, B12, C14, C15, C17, C18, D22, D24, E28, E29, E30, X33, X38, X39 |
| FAIL | 3 | A3, C16, X34 |
| OOS — not refused | 2 | X35, X36 |
| N/A identity | 2 | X31, X32 |

## Per-query verdicts

| ID | type | verdict | note |
|---|---|---|---|
| A1 | def | PASS | Rule-of-law chunks on-topic |
| A2 | doc | PARTIAL | Lead chunk SB065 is *corporate* "independent director," not judicial independence |
| A3 | case | **FAIL** | "Morfe v. Mutuc" in no chunk; expected CA242 is "right to be forgotten" — unrelated case |
| A4 | stance | PARTIAL | CA377/SA049 relevant; CE003/SE036 off-topic |
| A5 | doc | PARTIAL | CA095 (tech reform) on-point; BE003/BE001 off-topic |
| A6 | def | PASS | All chunks squarely on due process |
| B7 | doc | PASS | Liberty & Prosperity doctrine well covered |
| B8 | doc | PARTIAL | Twin-beacons context near, but the literal quote absent |
| B9 | doc | PASS | MSME / law-and-business on-topic |
| B10 | def | PARTIAL | "Prosperity Fund" only defined at rank 5; top chunks are scholarship/FLP |
| B11 | stance | PASS | Law-and-economics chunks directly answer |
| B12 | multi | PARTIAL | "Go together" covered; the *tension* ("opposite directions") not addressed |
| C13 | stance | PASS | Faith-and-justice chunks on-topic |
| C14 | stance | PARTIAL | Mentor/bio anecdotes tangential to "lessons from SC years" (theme mismatch) |
| C15 | doc | PARTIAL | BC001 relevant; SB028/SE036 off-topic (theme mismatch) |
| C16 | stance | **FAIL** | Lead chunk is CPA/CFO philosophy; nothing on family life (theme mismatch) |
| C17 | stance | PARTIAL | Salonga character chunk loosely fits; about a mentor, not bench colleagues |
| C18 | stance | PARTIAL | Bio/grandkids tangential; no direct reflective answer |
| D19 | def | PASS | FLP definition well covered (content fits despite REVIEW flag) |
| D20 | def | PASS | Scholarship eligibility directly covered |
| D21 | orphan | PASS | Museum for Liberty & Prosperity on-topic |
| D22 | doc | PARTIAL | CB003/SB040 relevant; lead CA031 (Korea state visit) off-topic (theme mismatch) |
| D23 | def | PASS | FLP partners/donors covered |
| D24 | stance | PARTIAL | "Why I organized FLP" present, but lead chunks are George Ty tribute |
| E25 | def | PASS | 2016 Arbitral Award richly covered (content fits despite REVIEW flag) |
| E26 | stance | PASS | ICC / Duterte chunks on-topic |
| E27 | doc | PASS | International law vs sovereignty on-topic |
| E28 | case | PARTIAL | Roe→Dobbs in expected CE007 (rank 5); top chunks generic "how SC decides" |
| E29 | case | PARTIAL | RA 10173 not defined; expected CA034 at rank 1 but generic; passing mention only |
| E30 | doc | PARTIAL | BD001/BA009 relevant; BD004/CA005 off-topic (theme mismatch) |
| X31 | id | N/A | Identity — grounding not expected |
| X32 | id | N/A | Capability — chunks irrelevant, handled elsewhere |
| X33 | multi | PARTIAL | Only CE003 touches death penalty; Echegaray case undescribed |
| X34 | date | **FAIL** | "When was Echegaray decided" — no chunk mentions Echegaray; all economic/arbitration |
| X35 | oos | **OOS not refused** | Weather query; data itself flags `FAIL_grounded_oos` |
| X36 | oos | **OOS not refused** | Restaurant query; CE018 ("museum curation / tourists") is a spurious near-match |
| X37 | multi | PASS | Rule of law + economic governance both covered |
| X38 | multi | PARTIAL | Prosperity doctrine covered; "judicial reform" half largely absent |
| X39 | orphan | PARTIAL | Faint travel hints (Alaska/lunch anecdote); no clear narrative |
| X40 | persona | PASS | Advice-to-young-lawyer well served |

## Expected-doc checks

- **A3 → CA242:** present at **rank 1 structurally**, but **semantically wrong** —
  CA242 is "Right to be forgotten" (Google Spain case), not Morfe v. Mutuc. The
  expected-doc tag itself looks mis-assigned; the corpus appears to lack Morfe.
- **E28 → CE007:** present at **rank 5** (CE007::c003, covers Roe→Dobbs). OK.
- **E29 → CA034:** present at **rank 1** (CA034::c002). OK but generic.

## Headline findings

1. **Structural integrity is perfect** — all 142 unique tagged chunk IDs resolve
   to real text; none dangle.
2. **~82% are usable** (15 PASS + 18 PARTIAL); most PARTIALs are theme-mismatch
   cases where relevant content exists but the rank-1 chunk drifts off-topic.
3. **3 hard FAILs are all factual lookups the corpus can't answer** — A3 (Morfe
   v. Mutuc), C16 (duty vs family life), X34 (Echegaray decision date). These
   surface unrelated chunks instead of refusing.
4. **Neither OOS query (X35, X36) was refused** — the out-of-scope gate is
   uncalibrated; X36 even produced a spuriously plausible chunk.
5. **A3's expected-doc tag is suspect** — CA242 doesn't match the query; worth
   re-checking the gold label for that case query.
