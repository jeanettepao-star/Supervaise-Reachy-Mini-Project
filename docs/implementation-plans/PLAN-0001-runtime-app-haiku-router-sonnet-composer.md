# PLAN-0001: Runtime app — evolve existing app/ to consume Phase 1-3 artifacts

* Status: draft
* Phase: 4
* Owner: TBD
* Depends on: Phases 1-3 complete (corpus + topic_map + voice_card)
* Verified by: [TS-001](../test-specs/TS-001-corpus-generator-contract.md),
  [TS-002](../test-specs/TS-002-topic-map-matchers.md),
  [TS-003](../test-specs/TS-003-topic-paths-derivation.md),
  [TS-004](../test-specs/TS-004-voice-card-protocol.md),
  [TS-005](../test-specs/TS-005-end-to-end-pipeline-smoke.md)
* Related ADRs:
  [0002](../decisions/0002-llm-tiering-haiku-router-sonnet-inference.md),
  [0003](../decisions/0003-reject-embeddings-for-v1.md),
  [0004](../decisions/0004-pattern-1-topic-routed-two-stage-api.md),
  [0010](../decisions/0010-anthropic-prompt-caching-voice-card.md),
  [0011](../decisions/0011-corpus-id-format-type-theme-number.md),
  [0015](../decisions/0015-topic-paths-derivation-rules.md),
  [0016](../decisions/0016-theme-anchored-register-selection.md)

## 1. Goal

Make the existing `app/cj_chat.py` + `app/dashboard.py` route, retrieve,
and compose responses from the Phase 1 corpus, the Phase 2 topic map,
and the Phase 3 voice card — replacing references to the previous
89-doc artifacts under `app/artifacts/`.

This is an **evolution**, not a rewrite. The runtime pipeline shape
(Haiku Input Gate → Haiku Router → Code lookup → Sonnet Composition →
Haiku Fidelity Check) is locked by ADR-0002 / ADR-0004 / PROJECT.md
§6. What changes is the *source of truth*:
- `app/artifacts/topic_map.json` → `corpus/voice/topic_map.json`
- `app/artifacts/voice_card.md` → `corpus/voice/voice_card.md`
- `app/artifacts/topics/*.json` → `corpus/{columns,speeches}/**/*.json`

## 2. Scope

**In scope**
1. Configurable artifact paths (env vars or constants) so the runtime
   reads from `corpus/voice/` and `corpus/{columns,speeches,
   biography}/` by default.
2. Doc-id format migration: every retrieval code path that assumed
   `col_YYYY_MMDD` / `book_01_chNN` shapes must accept
   `^[SCG][A-E]\d+$`. The retrieval step joins by `id`, not by file
   path.
3. Router prompt update to consume the new 35-topic taxonomy and the
   new register table (5 themes + META).
4. Context-block builder: assemble `<routed_topics>`, `<topic_data>`,
   `<source_documents>` blocks as described in
   [voice_card.md](../../corpus/voice/voice_card.md) §"Context block
   conventions".
5. Cache-control wiring on the voice card prefix
   (already in place per [ADR-0010](../decisions/0010-anthropic-prompt-caching-voice-card.md)).
6. Smoke tests using the six build-kit sanity questions
   (`corpus/build_kit/`).

**Out of scope**
- Frontend / web UI ([PLAN-0002](PLAN-0002-web-chat-ui.md)).
- Embedding audit ([PLAN-0003](PLAN-0003-embedding-audit-offline.md)).
- TTS / robot embodiment ([PLAN-0006](PLAN-0006-voice-tts-integration.md)).
- Book corpus ingestion ([PLAN-0005](PLAN-0005-book-corpus-addition.md)).

## 3. Pipeline (locked design — confirm wiring)

```
User input
  → Haiku Input Gate     (scope + identity-question check)
  → Haiku Router         (returns {primary_topic, secondary_topics,
                          confidence, reasoning})
  → Code lookup          (Topic Map → topic_paths intersection
                          → load whole .md + .json for top 1-3 docs)
  → Memory check         (last 6 turns; user-provided facts)
  → Sonnet Composition   (Voice Card + topic data + source docs)
  → Haiku Fidelity Check (hallucination + voice + guardrail)
  → Response
  → Memory update
```

## 4. Workstream A — Artifact-path migration (smallest blast radius)

**Status: complete** (see commit following this plan section's update).

1. ✅ Introduced `Config` dataclass at the top of `cj_chat.py` with
   defaults `CORPUS_ROOT = ../corpus`, `VOICE_DIR = ../corpus/voice`,
   `ROUTER_PROMPT = ./artifacts/router_prompt.md` (legacy until §B
   ships). All three paths overridable via env vars.
2. ✅ `CorpusArtifacts` rewritten to read `topic_map.json` and
   `voice_card.md` from `config.voice_dir`. Legacy artifact loads
   removed (`topic_graph.json`, `entity_index.json`, `frameworks.json`,
   `signature_library.json`) — these belonged to the prior 89-doc
   pipeline and were either unused at inference (LL-005) or redundant
   with per-doc `.json` fields.
3. ✅ `load_raw_doc(doc_id)` resolves
   `corpus/{type_dir}/{theme_folder}/{doc_id}.json` via the new
   `_doc_paths()` helper. ID parsing is strict on the
   `^[SCG][A-E]\d+$` regex; unknown ids return `None` (router-output
   schema validation already guards the surface — see Workstream B).
4. ✅ New `load_doc_body(doc_id)` returns the body of the paired `.md`
   for verbatim quoting by the composer. YAML frontmatter and the
   `# Title` line are stripped.
5. ✅ Back-compat alias: `ARTIFACTS_DIR = DEFAULT_CONFIG.voice_dir`
   keeps `app/dashboard.py`'s existing import working unchanged.
6. ✅ `build_context()` updated: the trimmed source-doc record now
   reads from the new `.json` schema (`id` not `doc_id`, plus
   `theme`, `theme_label`, `one_paragraph_summary`).
7. ✅ Smoke-test: `Config.from_env()` + `CorpusArtifacts()` load 35
   topics; `_doc_paths` resolves real ids (SA136, CA001, CA024) and
   correctly returns `None` for absent (`GC001` — biography skipped)
   and malformed (`BOGUS`, `ZZ999`) ids; `load_raw_doc('CA004')`
   returns a record whose `topic_paths.primary` matches Phase 2
   expectations.

**Acceptance** (partial): the artifact loader runs against the new
corpus. Full end-to-end smoke against the six build-kit sanity
questions ([TS-005](../test-specs/TS-005-end-to-end-pipeline-smoke.md))
requires Workstream B (router prompt update) and depends on a live
Anthropic API key; that is the next workstream's acceptance.

## 5. Workstream B — Router prompt update

**Status: complete.**

1. ✅ New router prompt at
   [`corpus/voice/router_prompt.md`](../../corpus/voice/router_prompt.md)
   — 35-topic Phase 2 taxonomy organised by tier + theme letter,
   explicit META branch for the honesty rule, 6 worked examples
   (clean doctrinal, biographical, contemporary, multi-theme, META,
   OOC).
2. ✅ Output shape: `{primary_topic, secondary_topics (≤3),
   confidence, reasoning}` — names match the existing
   `route_question` consumer; secondaries cap raised from 2 to 3 to
   match Phase 2 topic_paths schema.
3. ✅ `Config.from_env()` prefers
   `corpus/voice/router_prompt.md`; falls back to
   `app/artifacts/router_prompt.md` if the new file is missing.
4. ✅ `route_question()` validator hardened:
   - Primary topic id validated against `valid_topic_ids`;
     invalid → fallback to `rule_of_law` with `confidence: low`.
   - Secondaries: filtered to known ids, distinct from primary,
     capped at 3.
   - Confidence normalised to one of `{high, medium, low}`.
   - Reasoning trimmed to 200 chars.

**Acceptance**: the new prompt loads cleanly (9,606 chars). Router
output validation is unit-checkable; end-to-end routing accuracy is
measured by [TS-006](../test-specs/TS-006-smoke-test-questions.md)
once it runs against the live API.

## 6. Workstream C — Context-block builder

Assemble the `<routed_topics>` / `<topic_data>` / `<source_documents>`
block per
[voice_card.md](../../corpus/voice/voice_card.md) §"Context block
conventions".

1. For each routed topic id, copy its node from `topic_map.json`
   (definition + signature phrases + entities + register).
2. For source docs: intersect router output with `topic_paths`. Pick
   top 1-3 docs by combined primary/secondary hit count. Load whole
   `.md` body and key `.json` fields (`stances`, `notable_anecdotes`,
   `signature_phrases`, `one_paragraph_summary`).
3. Enforce a soft 12K-token budget on the assembled context. If
   exceeded, drop the lowest-priority source doc; never truncate
   mid-doc.

**Acceptance**: assembled context is ≤12K tokens for 95% of the
build-kit sanity questions.

## 7. Workstream D — Honesty rule wiring

The voice card's META branch
([voice_card.md](../../corpus/voice/voice_card.md) §"Honesty rule —
when asked what you are") triggers when:
- The router returns `robot_identity_meta` as primary, OR
- The Input Gate flags the question as an identity probe regardless
  of router output.

Implementation:
1. Input Gate (Haiku call before router): classifier returns
   `{scope: in_corpus | out_of_corpus | identity_probe, ...}`.
2. If `identity_probe`, override router primary to
   `robot_identity_meta`; the composer then activates the
   `transparent_curatorial` register.
3. Both branches still flow through the Sonnet composer; the META
   path uses the canonical *"I am a robot rendering of my own voice…"*
   self-description as the anchor response.

**Acceptance**:
[TS-004](../test-specs/TS-004-voice-card-protocol.md) §"Honesty rule
trigger" eval passes — every variant of *"are you the real CJ?"*
yields a robot-honest first-person response.

## 8. Workstream E — Fidelity check

Post-composition Haiku call: given the Sonnet draft + the assembled
context block, return:
- `hallucination`: any specific factual claim (case ruling, vote
  count, date) not grounded in the source docs?
- `voice_drift`: response violates the voice card's "Never" list?
- `guardrail_violation`: takes a stance on a `sub judice` case?

If any flag is true, retry the composition once with the flag fed
back as a system note. After one retry, return the safe fallback
*"I have not written specifically on this; let me speak to the
principle…"*

**Acceptance**: fidelity check correctly flags ≥80% of seeded
hallucination examples in
[TS-004](../test-specs/TS-004-voice-card-protocol.md) §"Fidelity
check sensitivity".

## 9. Failure modes and observability

| Failure mode | Detection | Response |
|---|---|---|
| Router returns invalid topic id | Schema validator | Fall back to wide route (anchors only) |
| Router timeout / API error | Per-call timeout (5s) | Fall back to wide route; log incident |
| Context exceeds token budget | Pre-flight count | Drop lowest-priority source doc |
| No source doc has the routed topic | Empty intersection | Return the source-less voice-only response |
| Sonnet returns malformed output | Output validator | One retry with a sterner system note; then safe fallback |
| Fidelity flags hallucination | Fidelity Haiku | One retry, then safe fallback |
| Memory layer corrupted | Load-time check | Reset memory for the session |

Observability (operator dashboard):
- Per-turn timeline: input gate (ms) | router (ms, topics, confidence)
  | context assembly (ms, tokens) | composition (ms, input/output
  tokens, cache hit ratio) | fidelity check (ms, flags) | total.
- Sources panel: every source doc id used, with its
  `theme/theme_label` and `topic_paths` for spot-checking.
- Cost panel: per-turn $; rolling session $.

## 10. Edge cases

- **Question routes to META + non-META primary.** META wins (honesty
  trumps topic).
- **Question routes to two themes equally.** First-primary rule
  decides register ([ADR-0016](../decisions/0016-theme-anchored-register-selection.md));
  composer notes the cross-theme nature in its reasoning.
- **Question references a current case (`sub judice`).** Fidelity
  check rejects substantive opinions; composer falls back to the
  principle.
- **Question references a topic absent from corpus (e.g., book
  chapters not yet ingested).** Out-of-corpus policy fires —
  composer reasons from nearest principles with the *"I have not
  written specifically on this…"* marker.

## 11. Verification

Tests (specified, not run):
- [TS-005](../test-specs/TS-005-end-to-end-pipeline-smoke.md) — full
  pipeline smoke against the six build-kit sanity questions.
- [TS-004](../test-specs/TS-004-voice-card-protocol.md) §6-§8 —
  honesty rule, register selection, OOC policy adherence.
- Cost & latency targets: ≤$0.05/turn, ≤25s warm
  ([ADR-0004](../decisions/0004-pattern-1-topic-routed-two-stage-api.md)).

Manual:
- Operator runs the six build-kit questions in the dashboard, spot-
  checks Sources panel, signs off the
  [GUIDE-reviewer.md](../guides/GUIDE-reviewer.md) checklist.

## 12. Out-of-scope discoveries to surface

If any of these surface during execution, file separate plans/ADRs:
- Memory layer schema is non-trivial — promote to its own plan if
  the existing `conversation_history` array proves insufficient.
- Streamlit caching pitfalls
  ([LL-004](../lessons/LL-004-streamlit-caches-imported-modules.md))
  affect hot-reload during development.
- Voice card prefix length changes — re-check cache savings against
  [LL-001](../lessons/LL-001-cache-savings-18-not-55.md).
