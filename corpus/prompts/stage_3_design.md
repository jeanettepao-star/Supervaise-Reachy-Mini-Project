# Stage 3 Synthesis Design

## Goal
Two demo artifacts that let Reachy navigate the corpus:
- **topic_map.json** — canonical topics with associated docs, quotes, frameworks
- **topic_graph.json** — directed/weighted edges between topics for traversal

Plus supporting indexes (entity normalization, signature-phrase library, mnemonic frameworks).

## Architectural choices

### 1. Two-layer model
- **Layer A (raw)**: 89 per-doc JSON files. Already done. Untouched.
- **Layer B (canonical)**: synthesized topic_map.json + topic_graph.json + indexes.

Reachy queries Layer B for navigation; pulls Layer A for evidence-quality detail (full quotes, full anecdotes).

### 2. Canonical topics: human-curated, not auto-clustered
Auto-clustering on 1,054 sub_topics + 702 signature phrases would be lossy and noisy. Instead: define ~30 canonical topics by hand (based on having read all 89 docs during extraction), each with an explicit definition + a list of which raw docs feed it.

### 3. Entity normalization layer
Build alias maps for people, cases, and laws. Example: "Gloria Macapagal Arroyo" + "Gloria Macapagal-Arroyo" + "Arroyo" → canonical "Gloria Macapagal-Arroyo".

### 4. Speech-readiness
- All canonical topics have `source_types: [...]` so when speech docs arrive they slot in by re-running aggregation
- Schema includes `register_distribution` per topic so we see "this topic is mostly editorial + some doctrinal-formal" — speeches will add a third bucket
- Acceptance-address register reserved as a known-empty bucket awaiting speech ingestion

## Schemas

### topic_map.json
```
{
  "schema_version": "1.0",
  "generated_at": "...",
  "corpus_stats": {n_docs, n_words, ...},
  "topics": {
    "<canonical_topic_id>": {
      "id": "rule_of_law",
      "display_name": "Rule of Law",
      "definition": "...",
      "tier": "anchor" | "major" | "subordinate",
      "doc_count": 23,
      "doc_ids": [...],
      "register_distribution": {editorial: 18, doctrinal-formal: 5},
      "date_range": ["2011-07-03", "2026-03-30"],
      "signature_phrases": [
        {phrase, count, doc_ids}
      ],
      "key_stances": [...],  # stance-quality propositions distilled from raw stances
      "frameworks_invoked": ["four_ins", "twin_beacons"],
      "key_entities": {people: [...], cases: [...], laws: [...]},
      "anecdotes": [...],  # only the recurring ones
      "cross_topics": [
        {target_id, weight, relation}  # edges to other topics
      ]
    }
  }
}
```

### topic_graph.json
```
{
  "schema_version": "1.0",
  "nodes": [
    {id, display_name, tier, doc_count, ...}
  ],
  "edges": [
    {source, target, weight, relation_type}
    # relation_type: 'parent' | 'sibling' | 'illustrates' | 'contrasts' | 'precedes'
  ]
}
```

### entity_index.json
```
{
  "people": {
    "<canonical_id>": {
      "canonical_name": "Jovito R. Salonga",
      "aliases": ["Salonga", "Jovito Salonga", "Sen. Salonga", ...],
      "doc_count": 16,
      "doc_ids": [...],
      "role": "mentor",
      "key_anecdotes": [...]
    }
  },
  "cases": {...},
  "laws": {...}
}
```

### frameworks.json
```
{
  "<framework_id>": {
    "id": "four_ins",
    "display_name": "Four Ins",
    "components": ["integrity", "intelligence", "independence", "industry"],
    "domain": "judicial character",
    "primary_source_doc": "book_01_ch09",
    "secondary_doc_ids": [...],
    "verbatim_quotes": [...]
  }
}
```

### signature_library.json
```
{
  "<phrase_id>": {
    "canonical_form": "the rule of law",
    "variants": ["rule of law", "Rule of Law", ...],
    "count": 23,
    "doc_ids": [...],
    "register": ["editorial", "doctrinal-formal"],
    "category": "philosophical-anchor" | "self-deprecating" | "rhetorical-marker" | ...
  }
}
```

## Canonical topic taxonomy (proposed)

### Anchor tier (corpus-defining; touch 10+ docs)
1. **rule_of_law** — the corpus's most-repeated organizing concept
2. **liberty_and_prosperity** — twin-beacons philosophy + FLP
3. **personal_formation** — Sampaloc → FEU → Salonga → JBC → SC
4. **flp_institutional_history** — Foundation programs, scholars, donors
5. **judicial_reform** — APJR, four Ins, three E-values, mnemonics

### Major tier (substantive doctrines; 4-9 docs)
6. **west_philippine_sea** — Arbitral Award, EEZ, China negotiations
7. **death_penalty** — Echegaray, international treaties, DNA exoneration
8. **icc_jurisdiction** — Duterte, two-year prescriptive period, complementarity
9. **citizenship_and_elections** — Frivaldo, Bengson, dual-citizenship
10. **party_list_system** — Veterans, Ang Bagong Bayani, marginalized/underrepresented
11. **judicial_activism** — Article VIII Sec 1, grave abuse of discretion
12. **edsa_ii_succession** — Estrada v Desierto, oath-taking, inhibition
13. **due_process** — Themistocles, Webster, hearing-before-condemning
14. **constitutional_globalization** — Tañada v Angara, WTO, paradigm shifts
15. **judicial_independence** — Act 136, financial autonomy, security of tenure

### Subordinate tier (3-5 docs)
16. **legal_education_reform** — Foundation for Enhancement of Legal Ed, bar exams
17. **alternative_dispute_resolution** — mediation, ADR, court backlog
18. **electronic_evidence_age** — ECA, paperless courts, digital
19. **freedom_of_expression** — exit polls, libel, actual malice
20. **environment_natural_resources** — IPRA, Oposa, Regalian doctrine
21. **medical_jurisprudence** — Batiquin, Ramos v CA, res ipsa loquitur
22. **theological_jurisprudence** — Justice as God's work, BLD, biblical citations
23. **lawyer_ethics** — Code of Professional Responsibility, threefold hierarchy
24. **decision_writing_craft** — 4 Cs, obra maestra, accessibility

### Personal-pantheon tier (4-8 docs each)
25. **mentor_salonga** — Salonga as guru, set-pieces, teachings
26. **chief_davide** — Davide leadership, four pillars, Bible-cutting
27. **leni_and_family** — Carpio family, Jose Sr., BLD journey
28. **diokno_teehankee** — Diokno-Salonga-Teehankee legal trinity
29. **carpio_legacy** — "the CJ we never had", WPS scholarship

### Civic/contemporary tier (3-8 docs)
30. **ai_and_law** — AI, liberty-prosperity ethics
31. **martial_law_critique** — anti-cha-cha, anti-authoritarianism
32. **media_freedom** — Ressa, cyberlibel, journalist awards
33. **religious_freedom** — separation of church-from-state-but-not-state-from-God

## Edge taxonomy

- **parent / child** — hierarchical (rule_of_law → liberty_and_prosperity)
- **invokes** — topic A regularly cites framework/topic B (judicial_reform → four_ins)
- **contrasts** — topic A is defined against topic B (judicial_activism ↔ judicial_restraint)
- **illustrates** — case-doctrine pair (citizenship_and_elections → Frivaldo, Bengson)
- **precedes** — biographical/causal (mentor_salonga → personal_formation → judicial_reform)
- **co-occurs** — high co-occurrence weight without typed relation

## Build order

1. Build entity alias maps (people, cases, laws) by canonicalizing variants
2. Define canonical topic taxonomy with doc_id assignments
3. Aggregate per-topic stats (counts, signature phrases, frameworks)
4. Build cross-topic edges from co-occurrence + manual relation tags
5. Build framework index
6. Build signature-phrase library
7. Serialize all artifacts
8. Validate (every doc appears in ≥1 topic; every framework has source doc; every edge has both endpoints)
