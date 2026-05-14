# Stage 1a: Per-Document Topic Extraction Prompt

You are analyzing a piece of writing by retired Philippine Chief Justice Artemio V. Panganiban ("CJ"), with the goal of building a structured representation of his intellectual terrain — what he thinks about, how he frames it, and his rhetorical fingerprints.

## Your task

Read the document carefully. Then produce a JSON object with this exact schema. No prose, no preamble, no markdown fences — just the JSON.

```json
{
  "doc_id": "string — copy from frontmatter",
  "doc_type": "column | book-chapter | book-appendix | book-front-matter",
  "title": "string — copy from frontmatter",
  "date": "YYYY-MM-DD | YYYY-MM | null",
  "voice_register": "editorial | doctrinal-formal",

  "primary_topics": [
    "2-5 top-level topics this document is primarily about. Use short, canonical noun phrases (e.g. 'rule of law', 'judicial independence', 'West Philippine Sea', 'liberty and prosperity', 'due process')."
  ],

  "sub_topics": [
    "5-12 more specific concepts, doctrines, cases, statutes, or events this document discusses (e.g. 'Arbitral Award 2016', 'UNCLOS', 'Article XI Section 13', 'nine-dash line')."
  ],

  "stances": [
    {
      "claim": "A specific argumentative claim CJ makes in this document. State it in his voice, ~1-2 sentences.",
      "rhetorical_move": "How he supports it — e.g. 'historical analogy', 'constitutional textual reading', 'personal anecdote', 'citation of jurisprudence', 'comparative law', 'biblical/spiritual reference', 'enumeration', 'rhetorical question'.",
      "confidence": "asserted | hedged | exploratory"
    }
  ],

  "entities": {
    "people": ["named individuals — justices, officials, mentors, opponents"],
    "institutions": ["named bodies — Supreme Court, ICC, FLP, FEU, etc."],
    "cases": ["named legal cases (italicized in original) — e.g. 'Estrada v. Desierto', 'Tañada v. Angara'"],
    "laws_treaties": ["named laws, treaties, conventions — e.g. 'RA 9262', 'UNCLOS', 'Rome Statute'"],
    "events": ["named historical events — e.g. 'EDSA II', 'First Quarter Storm', '1986 Constitutional Commission'"]
  },

  "signature_phrases": [
    "2-6 phrases that feel distinctively CJ — recurring formulations, signature metaphors, characteristic openings or hedges. Quote them verbatim, max 12 words each."
  ],

  "register_markers": [
    "Linguistic markers of the register — e.g. 'IMHO', 'in my humble opinion', 'Au contraire', 'sub silentio', Latin phrases, biblical citations, Tagalog code-switching. Tag what's actually present."
  ],

  "decision_framework_signals": [
    "Where in this document does CJ invoke a decision framework or evaluation lens? Examples: 'applies rule-of-law lens to maritime sovereignty', 'invokes constitutional textualism over original intent', 'frames issue as liberty vs prosperity tradeoff'. Empty array if none."
  ],

  "cross_references": [
    "Explicit references to his own prior columns, books, or decisions (e.g. 'as I wrote in my Dec. 11, 2023 column', 'see Chapter 22 of Transparency')."
  ],

  "notable_anecdotes": [
    "Brief tag of any personal stories or memorable scenes (e.g. 'wading through floodwaters to 1960 bar exam', 'first meeting Marixi Prieto'). One-line summary each."
  ]
}
```

## Extraction principles

1. **Use his canonical vocabulary, not yours.** If he says "rule of law" 14 times, the topic is "rule of law" — not "legal principles" or "governance norms".

2. **Stances are claims, not summaries.** "He discusses ICC jurisdiction" is not a stance. "The 2-year prescriptive period barred ICC jurisdiction over Duterte" is a stance.

3. **Signature phrases are gold for the alter-ego work.** Look for: recurring openings ("Mga kababayan", "I am overwhelmed"), hedges ("in my humble opinion", "though unworthy"), characteristic metaphors ("twin beacons", "the long shadow"), Filipino-English code-switching. Quote verbatim.

4. **Be parsimonious in primary_topics, generous in sub_topics.** Primary should be at the abstraction level a librarian would tag the document. Sub should include specific cases, statutes, doctrines.

5. **If a field has no content for this document, return an empty array — never null, never invent.**

6. **Output JSON only.** No "Here is the JSON" preamble. No trailing comments. Pure parseable JSON.
