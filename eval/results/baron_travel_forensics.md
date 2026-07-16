# Baron Travel retrieval forensics ($0, read-only) — 2026-07-17

**Demo transcript:** "What can you say about your baron travel entrepreneurship?" → composer declined
with *"does not appear anywhere in my record."*

## 1. Corpus — the material EXISTS (13 docs mention Baron Travel)
`corpus/index/chunks.jsonl` grep, doc_id → title:
GC006 *Independence by Design* · GC027 *Chapter 7: Lawyer in the Marketplace* (the two
entrepreneurship-substance docs) · CC006 *For the alumni of Mapa High* · CC070 *Henry Sy Sr.* ·
CD017 *FLP's 21 scholars…* · BC014/BC019 *Justice and Faith* · SB079 *Safeguard Liberty…* ·
SC003/SC018/SC053/SC084/SC121 (ADL/family speeches).

## 2. Subset — GC006 (and 10 of 13) are NOT in the v4 pilot
`pilot_subset_frozen_v4.csv` membership: **GC006 ✗, GC027 ✗**, CC070 ✗, CD017 ✗, BC014 ✗, BC019 ✗,
SB079 ✗, SC018 ✗, SC053 ✗, SC084 ✗, SC121 ✗ — only **CC006 ✓** and **SC003 ✓** (passing mentions)
are reachable. → **Structurally unreachable: same class as the A4/X33 out-of-pilot gold finding.**
Per the task rule, ranking analysis stops here.

## 3. Taxonomy — GC006 is ALSO an orphan (the documented GC006 pattern, confirmed live)
`corpus/voice/topic_map.json`: **GC006 belongs to NO topic** (as do CC070, CD017, BC014, BC019,
SB079, SC018, SC053, SC084, SC121 — 12 of the 13 Baron docs are topic-orphans; only CC006 has
topics). So even after an allowlist expansion, GC006 gets no soft-prior affinity (bias-only —
retrievable via dense+BM25, but unassisted).

## 4. BM25 dictionary — NOT the gap
`sparse_phrase_dict.json` carries **5 Baron Travel forms**: "baron travel", "baron travel corp.",
"baron travel corporation", "baron travel corporation founded 1967" (+1). The sparse arm was ready
to rescue this entity **if the doc were in the universe**.
*(Live rank measurement for the 3 query variants was attempted but aborted by a NEW environment
incident — see §7. Not required for the verdict: subset exclusion ends the ranking analysis.)*

## 5. VERDICT: **SUBSET-EXCLUSION** (primary) + **ORPHAN-TOPIC** (compounding secondary)
- Primary: GC006/GC027 are outside the 95-doc pilot universe → no retrieval mechanism can reach them.
  **Fix owner: the allowlist decision (Pao + Sheena — same eval-universe decision as A4/X33).**
- Secondary: 12/13 Baron docs are topic-orphans → **fix owner: taxonomy rebuild (W3.x full-corpus
  centroid rebuild — already flagged for the 3 zero-member topics; add the orphan sweep).**
- NOT ranking (W3.4) and NOT dictionary (BM25 entries exist).

## 6. PERSONA TRUTHFULNESS FLAG (proposed, NOT applied — Dev0 to approve)
The composer asserted *"does not appear anywhere in my record"* — **factually false** (GC006/GC027
exist; the retrieval universe simply excludes them). The model cannot see the full corpus, so it
must never assert corpus-wide non-existence. Note: commit 2c69cc5 already forbids global-record
claims for **OOS** declines; this gap is the **GAP/in-domain** decline path (voice card,
`corpus/voice/voice_card.md` "decline gracefully" block).
**PROPOSED wording (for Dev0):** extend the voice card decline guidance with one line:
> *"When the context lacks the material, say 'I don't have that material at hand right now' or
> 'that is not something I can speak to here' — NEVER assert that something does not exist in your
> record or writings; you can only see what is in front of you."*
Not applied — voice card is production persona surface; Dev0 approves.

## 7. NEW ENVIRONMENT INCIDENT (mid-forensics, blocks embed-dependent work)
During step 4, `python.exe` began **segfaulting (exit 139) on ANY transformer model load** —
bge-base via hub or snapshot path, CUDA **and CPU** — including a bare sentence-transformers repro
that had succeeded minutes earlier. Plain torch matmul still works; the crash is at model
load/encode. This is the machine's recurring injection signature (same class as the W1.5-era
model-load hard-aborts attributed to Avast). **Impact: the voice demo/smoke apps will crash at
warm-up until resolved.** Remedy per prior incidents: reboot + re-verify the Avast Service-host
profile (docs/RUNBOOK_transport.md); note the TLS preflight does NOT catch this — proposal (not
applied): extend preflight with a 1-line embed probe.
