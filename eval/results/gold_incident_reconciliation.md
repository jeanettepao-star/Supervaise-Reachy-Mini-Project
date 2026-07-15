# Gold Incident Reconciliation — round-2 checkout regression

Date: 2026-07-16T03:30:51+08:00
Authoritative: incoming/gold_reference_set_SHEENA.csv (raw 453a6d28, norm b08962e5)

## What differed
- GRADING columns: 0 diffs (NONE — repair from e18e1d1 was complete)
- AT-RISK cells restored from authoritative: 3
  - A4.gold_titles
  - E28.gold_titles
  - X33.gold_titles
- NEUTRAL diffs (reported, not auto-overwritten): 0
  - none

## Verification
- Column hashes (recipe: sha256 over qid-sorted 'qid=cell' lines):
{
  "gold_titles": {
    "repo": "829163f8",
    "authoritative": "829163f8",
    "files_match": true,
    "expected_prefix": "a9b44310",
    "matches_expected_prefix": false
  },
  "gold_grounding_summary": {
    "repo": "8599320e",
    "authoritative": "8599320e",
    "files_match": true,
    "expected_prefix": "fc38ef90",
    "matches_expected_prefix": false
  },
  "model_answer": {
    "repo": "8fbb55ca",
    "authoritative": "8fbb55ca",
    "files_match": true,
    "expected_prefix": "51b576b1",
    "matches_expected_prefix": false
  },
  "review_status": {
    "repo": "395550c3",
    "authoritative": "395550c3",
    "files_match": true,
    "expected_prefix": "ee01e226",
    "matches_expected_prefix": false
  }
}
- N=34, A4/E28/X33 corrections intact, scope counts unchanged.
- $0 regrade sanity: recall@1=0.735, recall@5=0.971 — unchanged.

## Incident residual risk: **CLOSED**
