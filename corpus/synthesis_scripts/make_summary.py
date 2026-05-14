"""
Produce a human-readable markdown summary of the synthesis artifacts.
This is for human review during the demo build — not the machine artifact.
"""
import json
import os
from collections import Counter

SYN = "/home/claude/corpus/analysis/synthesis"
OUT = f"{SYN}/SUMMARY.md"

with open(f"{SYN}/topic_map.json") as f: tm = json.load(f)
with open(f"{SYN}/topic_graph.json") as f: tg = json.load(f)
with open(f"{SYN}/entity_index.json") as f: ei = json.load(f)
with open(f"{SYN}/frameworks.json") as f: fi = json.load(f)
with open(f"{SYN}/signature_library.json") as f: sl = json.load(f)
with open(f"{SYN}/corpus_stats.json") as f: cs = json.load(f)

lines = []
lines.append("# CJ Panganiban Corpus — Stage 3 Synthesis Summary\n")
lines.append(f"Generated: {tm['generated_at']}\n")
lines.append("## Corpus Overview\n")
lines.append(f"- Total documents: **{cs['n_docs']}**")
lines.append(f"- Document type distribution: {cs['doc_type_distribution']}")
lines.append(f"- Voice register distribution: {cs['voice_register_distribution']}")
lines.append(f"- Year range: {min(cs['year_distribution'])} – {max(cs['year_distribution'])}")
lines.append(f"- Canonical topics: **{cs['n_canonical_topics']}**")
lines.append(f"- Canonical people: **{cs['n_canonical_people']}**")
lines.append(f"- Canonical cases: **{cs['n_canonical_cases']}**")
lines.append(f"- Frameworks indexed: **{cs['n_frameworks']}**\n")

lines.append("## Topic Map by Tier\n")
tier_order = ["anchor", "major", "personal-pantheon", "subordinate"]
for tier in tier_order:
    tier_topics = [t for t in tm["topics"].values() if t["tier"] == tier]
    tier_topics.sort(key=lambda t: -t["doc_count"])
    lines.append(f"### Tier: {tier.upper()}\n")
    for t in tier_topics:
        lines.append(f"#### {t['display_name']} ({t['id']})")
        lines.append(f"- **{t['doc_count']} docs**, {t['date_range'][0]} → {t['date_range'][1]}")
        lines.append(f"- Definition: {t['definition']}")
        lines.append(f"- Registers: {t['register_distribution']}")
        if t["signature_phrases"]:
            top_phrases = [f"{sp['count']}× '{sp['phrase']}'" for sp in t["signature_phrases"][:5]]
            lines.append(f"- Top phrases: {', '.join(top_phrases)}")
        if t["frameworks_invoked"]:
            lines.append(f"- Frameworks: {t['frameworks_invoked']}")
        if t["key_entities"]["people"]:
            top_p = [f"{p['id']} ({p['count']}×)" for p in t["key_entities"]["people"][:4]]
            lines.append(f"- Top people: {', '.join(top_p)}")
        if t["key_entities"]["cases"]:
            top_c = [f"{c['id']} ({c['count']}×)" for c in t["key_entities"]["cases"][:4]]
            lines.append(f"- Top cases: {', '.join(top_c)}")
        lines.append("")

lines.append("## Topic Graph: Top-Connected Nodes\n")
deg = Counter()
for e in tg["edges"]:
    deg[e["source"]] += 1
    deg[e["target"]] += 1
for n, d in deg.most_common(15):
    display = next((t["display_name"] for tid, t in tm["topics"].items() if tid == n), n)
    lines.append(f"- **{d}** edges: `{n}` ({display})")
lines.append("")

lines.append("## Edge Type Distribution\n")
etypes = Counter(e["relation_type"] for e in tg["edges"])
for t, c in etypes.most_common():
    lines.append(f"- {t}: {c}")
lines.append("")

lines.append("## Frameworks (Mnemonic Library)\n")
for fid, f in fi.items():
    lines.append(f"### {f['display_name']} (`{fid}`)")
    lines.append(f"- Components: {', '.join(f['components'])}")
    lines.append(f"- Domain: {f['domain']}")
    lines.append(f"- Verbatim anchor: \"{f['verbatim_anchor']}\"")
    lines.append(f"- Primary source: `{f['primary_source_doc']}`")
    lines.append(f"- Doc coverage: {f['doc_count']} docs")
    lines.append("")

lines.append("## Top Signature Phrases (count ≥ 2)\n")
sorted_phrases = sorted(sl.values(), key=lambda x: -x["count"])
for sp in sorted_phrases:
    if sp["count"] < 2: break
    cat = sp["category"]
    lines.append(f"- **{sp['count']}× [{cat}]** \"{sp['canonical_form']}\"")
lines.append("")

lines.append("## Entity Index — Top People (5+ doc coverage)\n")
top_people = sorted(
    [(pid, p) for pid, p in ei["people"].items() if p["doc_count"] >= 5],
    key=lambda x: -x[1]["doc_count"]
)
for pid, p in top_people:
    lines.append(f"- **{p['doc_count']} docs**: {p['canonical_name']} (`{pid}`)")
    lines.append(f"    - role: {p['role']}")
lines.append("")

lines.append("## Entity Index — Cases (3+ doc coverage)\n")
top_cases = sorted(
    [(cid, c) for cid, c in ei["cases"].items() if c["doc_count"] >= 1],
    key=lambda x: -x[1]["doc_count"]
)
for cid, c in top_cases:
    lines.append(f"- **{c['doc_count']} docs**: {c['canonical_name']} (`{cid}`)")
    lines.append(f"    - doctrine: {c['doctrine']}")
lines.append("")

lines.append("## Demo Workflow for Reachy\n")
lines.append("""
This synthesis provides Reachy with a navigable knowledge layer:

1. **User asks**: "What is the rule of law?"
   - Reachy queries `topic_map.json` for the `rule_of_law` topic node
   - Returns: definition, top signature phrases, key stances, top cases/people/laws
   - For deeper questions, follows `doc_ids` back to raw extractions

2. **User asks**: "Tell me about CJ's mentor."
   - Reachy queries `mentor_salonga` topic node
   - Returns: anecdotes (1956 FEU strike, 1960 bar wading, etc.) + signature phrases

3. **User asks**: "What did CJ think about the death penalty?"
   - Reachy queries `death_penalty` topic node
   - Returns: structured stances + Echegaray case + international-treaty argument

4. **User asks**: "What is liberty and prosperity?"
   - Reachy queries `liberty_and_prosperity`
   - Returns: twin-beacons definition + FLP + Tañada v Angara doctrinal basis
""")

with open(OUT, "w") as f:
    f.write("\n".join(lines))

print(f"Summary written: {OUT}")
print(f"Lines: {len(lines)}")
