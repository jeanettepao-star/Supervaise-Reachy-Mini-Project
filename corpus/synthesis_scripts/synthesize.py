"""
Stage 3 synthesis: produces canonical Layer B artifacts from Layer A raw extractions.

Inputs:
- /home/claude/corpus/analysis/topics/*.json  (89 raw extractions)
- /home/claude/taxonomy.py                    (canonical topic taxonomy)
- /home/claude/aliases.py                     (entity alias maps)

Outputs to /home/claude/corpus/analysis/synthesis/:
- topic_map.json
- topic_graph.json
- entity_index.json
- frameworks.json
- signature_library.json
- corpus_stats.json
"""
import json
import glob
import os
import sys
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, "/home/claude")
from taxonomy import TOPIC_TAXONOMY, FRAMEWORK_INDEX
from aliases import PEOPLE_ALIASES, CASE_ALIASES, LAW_ALIASES

CORPUS_DIR = "/home/claude/corpus"
TOPICS_DIR = f"{CORPUS_DIR}/analysis/topics"
OUT_DIR = f"{CORPUS_DIR}/analysis/synthesis"
os.makedirs(OUT_DIR, exist_ok=True)


# ============================================================
# Load all raw extractions
# ============================================================
def load_all_docs():
    docs = {}
    for f in sorted(glob.glob(f"{TOPICS_DIR}/*.json")):
        d = json.load(open(f))
        docs[d["doc_id"]] = d
    return docs


# ============================================================
# Entity normalization helpers
# ============================================================
def build_reverse_index(alias_dict):
    """variant_lowercase → canonical_id"""
    rev = {}
    for canonical_id, entry in alias_dict.items():
        for variant in entry["aliases"]:
            rev[variant.lower().strip()] = canonical_id
    return rev


def normalize_entity(raw, reverse_idx):
    """Return canonical id, or None if no match."""
    return reverse_idx.get(raw.lower().strip())


PEOPLE_REV = build_reverse_index(PEOPLE_ALIASES)
CASE_REV = build_reverse_index(CASE_ALIASES)
LAW_REV = build_reverse_index(LAW_ALIASES)


# ============================================================
# Build entity index
# ============================================================
def build_entity_index(docs):
    out = {"people": {}, "cases": {}, "laws_treaties": {}}

    for canonical_id, entry in PEOPLE_ALIASES.items():
        out["people"][canonical_id] = {
            **entry,
            "doc_count": 0,
            "doc_ids": [],
        }
    for canonical_id, entry in CASE_ALIASES.items():
        out["cases"][canonical_id] = {
            **entry,
            "doc_count": 0,
            "doc_ids": [],
        }
    for canonical_id, entry in LAW_ALIASES.items():
        out["laws_treaties"][canonical_id] = {
            **entry,
            "doc_count": 0,
            "doc_ids": [],
        }

    # Also track unrecognized variants for review
    unrecognized = {"people": Counter(), "cases": Counter(), "laws_treaties": Counter()}

    for doc_id, d in docs.items():
        ents = d.get("entities", {})

        # People
        seen_people = set()
        for p in ents.get("people", []):
            cid = normalize_entity(p, PEOPLE_REV)
            if cid:
                if cid not in seen_people:
                    out["people"][cid]["doc_count"] += 1
                    out["people"][cid]["doc_ids"].append(doc_id)
                    seen_people.add(cid)
            else:
                unrecognized["people"][p] += 1

        # Cases
        seen_cases = set()
        for c in ents.get("cases", []):
            cid = normalize_entity(c, CASE_REV)
            if cid:
                if cid not in seen_cases:
                    out["cases"][cid]["doc_count"] += 1
                    out["cases"][cid]["doc_ids"].append(doc_id)
                    seen_cases.add(cid)
            else:
                unrecognized["cases"][c] += 1

        # Laws
        seen_laws = set()
        for l in ents.get("laws_treaties", []):
            cid = normalize_entity(l, LAW_REV)
            if cid:
                if cid not in seen_laws:
                    out["laws_treaties"][cid]["doc_count"] += 1
                    out["laws_treaties"][cid]["doc_ids"].append(doc_id)
                    seen_laws.add(cid)
            else:
                unrecognized["laws_treaties"][l] += 1

    # Sort doc_ids
    for cat in out.values():
        for entry in cat.values():
            entry["doc_ids"].sort()

    return out, unrecognized


# ============================================================
# Build signature-phrase library
# ============================================================
def normalize_phrase(p):
    """Lowercase, strip, collapse whitespace, remove enclosing quotes."""
    p = p.strip().strip('"').strip("'").strip()
    p = re.sub(r"\s+", " ", p)
    return p.lower()


# Phrase canonicalization map: common variants → canonical form
PHRASE_CANONICAL = {
    "imho": "in my humble opinion",
    "in my humble view": "in my humble opinion",
    "i.m.h.o.": "in my humble opinion",
    "though i pale utterly": "though unworthy",
    "though undeserving": "though unworthy",
    "though unworthy and undeserving": "though unworthy",
    "though undeserving and unworthy": "though unworthy",
    "the twin and inseparable beacons": "twin beacons of liberty and prosperity",
    "twin beacons": "twin beacons of liberty and prosperity",
    "liberty and prosperity under the rule of law": "twin beacons of liberty and prosperity",
    "one is useless without the other": "twin beacons of liberty and prosperity",
    "unleash the entrepreneurial genius of people": "unleash the entrepreneurial ingenuity",
    "unleash the entrepreneurial ingenuity of people": "unleash the entrepreneurial ingenuity",
    "unleash the entrepreneurial genius": "unleash the entrepreneurial ingenuity",
    "katarungan at bayan magpakailanman": "katarungan at bayan, magpakailanman",
    "yours truly as chair": "yours truly",
    "maraming salamat po": "maraming salamat po",
}

# Phrase categories for Reachy voice selection
PHRASE_CATEGORIES = {
    # philosophical-anchor
    "twin beacons of liberty and prosperity": "philosophical-anchor",
    "the rule of law": "philosophical-anchor",
    "those who have less in life should have more in law": "philosophical-anchor",
    "justice and jobs; freedom and food; ethics and economics; peace and development; liberty and prosperity": "philosophical-anchor",
    "right is better than might; the pen, more powerful than the sword; and reason, more reliable than aggression": "philosophical-anchor",
    "to dispense quality justice is to do god's work": "philosophical-anchor",
    "law cannot be separated from life": "philosophical-anchor",

    # self-deprecating
    "though unworthy": "self-deprecating",
    "yours truly": "self-deprecating",
    "in my humble opinion": "epistemic-marker",

    # rhetorical-marker
    "au contraire": "rhetorical-marker",
    "to be fair": "rhetorical-marker",
    "to repeat": "rhetorical-marker",
    "sadly, however": "rhetorical-marker",
    "cheers!": "closing-flourish",
    "abangan!": "closing-flourish",
    "mabuhay!": "closing-flourish",
    "maraming salamat po": "closing-flourish",
    "salamat po": "closing-flourish",
    "katarungan at bayan, magpakailanman": "thematic-tagalog",

    # mentoring-tribute
    "lives of great men all remind us we can make our life sublime": "mentoring-tribute",
    "the source of all that is true, good and beautiful": "mentoring-tribute",
    "compañero": "collegial-address",
}


def build_signature_library(docs):
    phrase_to_docs = defaultdict(list)
    phrase_to_variants = defaultdict(set)
    phrase_register = defaultdict(Counter)

    for doc_id, d in docs.items():
        register = d.get("voice_register", "unknown")
        for raw in d.get("signature_phrases", []):
            normalized = normalize_phrase(raw)
            canonical = PHRASE_CANONICAL.get(normalized, normalized)
            phrase_to_docs[canonical].append(doc_id)
            phrase_to_variants[canonical].add(raw)
            phrase_register[canonical][register] += 1

    library = {}
    for canonical, doc_ids in phrase_to_docs.items():
        # Generate a slug id
        slug = re.sub(r"[^a-z0-9]+", "_", canonical)[:60].strip("_")
        if not slug:
            continue
        library[slug] = {
            "canonical_form": canonical,
            "variants": sorted(phrase_to_variants[canonical]),
            "count": len(doc_ids),
            "doc_ids": sorted(set(doc_ids)),
            "register_distribution": dict(phrase_register[canonical]),
            "category": PHRASE_CATEGORIES.get(canonical, "uncategorized"),
        }
    return library


# ============================================================
# Build framework index with doc evidence
# ============================================================
def build_framework_index(docs):
    out = {}
    for fid, finfo in FRAMEWORK_INDEX.items():
        # find all docs that mention this framework's components
        comp_words = [c.lower() for c in finfo["components"]]
        verbatim = finfo.get("verbatim_anchor", "").lower()

        evidence_doc_ids = set()
        for doc_id, d in docs.items():
            blob = json.dumps(d).lower()
            # require either verbatim match OR all components present in same doc
            if verbatim and any(part in blob for part in verbatim.split(";")[:1]):
                # use first clause of verbatim
                if verbatim.split(";")[0].strip() in blob:
                    evidence_doc_ids.add(doc_id)
            if all(c in blob for c in comp_words):
                evidence_doc_ids.add(doc_id)

        # ensure primary source is included
        evidence_doc_ids.add(finfo["primary_source_doc"])

        out[fid] = {
            **finfo,
            "doc_count": len(evidence_doc_ids),
            "doc_ids": sorted(evidence_doc_ids),
        }
    return out


# ============================================================
# Build per-topic aggregate stats
# ============================================================
def aggregate_topic(topic_id, topic_def, docs, frameworks):
    doc_ids = topic_def["doc_ids"]
    topic_docs = [docs[d] for d in doc_ids if d in docs]

    if not topic_docs:
        return None

    # date range
    dates = sorted([d.get("date", "") for d in topic_docs if d.get("date")])
    date_range = [dates[0], dates[-1]] if dates else [None, None]

    # register distribution
    registers = Counter(d.get("voice_register", "unknown") for d in topic_docs)

    # source-type distribution (will get speech bucket later)
    source_types = Counter(d.get("doc_type", "unknown") for d in topic_docs)

    # collect signature phrases
    phrases = Counter()
    phrase_doc_map = defaultdict(set)
    for d in topic_docs:
        for raw in d.get("signature_phrases", []):
            norm = normalize_phrase(raw)
            canonical = PHRASE_CANONICAL.get(norm, norm)
            phrases[canonical] += 1
            phrase_doc_map[canonical].add(d["doc_id"])

    sig_phrases_out = [
        {"phrase": p, "count": c, "doc_ids": sorted(phrase_doc_map[p])}
        for p, c in phrases.most_common(20)
    ]

    # collect entities used in this topic (normalized)
    people_count = Counter()
    cases_count = Counter()
    laws_count = Counter()
    for d in topic_docs:
        ents = d.get("entities", {})
        seen_p, seen_c, seen_l = set(), set(), set()
        for p in ents.get("people", []):
            cid = normalize_entity(p, PEOPLE_REV)
            if cid and cid not in seen_p:
                people_count[cid] += 1
                seen_p.add(cid)
        for c in ents.get("cases", []):
            cid = normalize_entity(c, CASE_REV)
            if cid and cid not in seen_c:
                cases_count[cid] += 1
                seen_c.add(cid)
        for l in ents.get("laws_treaties", []):
            cid = normalize_entity(l, LAW_REV)
            if cid and cid not in seen_l:
                laws_count[cid] += 1
                seen_l.add(cid)

    # frameworks invoked (from definition + evidence overlap)
    fw_invoked = list(topic_def.get("invokes_frameworks", []))
    for fid, finfo in frameworks.items():
        if fid in fw_invoked:
            continue
        overlap = set(finfo["doc_ids"]) & set(doc_ids)
        if len(overlap) >= 2:
            fw_invoked.append(fid)

    # collect key stances (one representative from each doc)
    key_stances = []
    for d in topic_docs:
        for s in d.get("stances", [])[:1]:  # take first stance from each doc
            key_stances.append({
                "doc_id": d["doc_id"],
                "claim": s.get("claim", ""),
                "rhetorical_move": s.get("rhetorical_move", ""),
            })

    # collect anecdotes
    anecdotes = []
    for d in topic_docs:
        for a in d.get("notable_anecdotes", [])[:2]:
            anecdotes.append({"doc_id": d["doc_id"], "text": a})

    return {
        "id": topic_id,
        "display_name": topic_def["display_name"],
        "definition": topic_def["definition"],
        "tier": topic_def["tier"],
        "doc_count": len(topic_docs),
        "doc_ids": sorted(doc_ids),
        "date_range": date_range,
        "register_distribution": dict(registers),
        "source_type_distribution": dict(source_types),
        "signature_phrases": sig_phrases_out,
        "frameworks_invoked": fw_invoked,
        "key_entities": {
            "people": [{"id": p, "count": c} for p, c in people_count.most_common(15)],
            "cases": [{"id": c, "count": n} for c, n in cases_count.most_common(10)],
            "laws_treaties": [{"id": l, "count": n} for l, n in laws_count.most_common(10)],
        },
        "key_stances": key_stances[:8],
        "anecdotes": anecdotes[:10],
        "relations": topic_def.get("relations", []),
    }


# ============================================================
# Build topic graph (nodes + edges)
# ============================================================
def build_topic_graph(topic_map):
    nodes = []
    edges = []

    for tid, t in topic_map["topics"].items():
        nodes.append({
            "id": tid,
            "display_name": t["display_name"],
            "tier": t["tier"],
            "doc_count": t["doc_count"],
        })
        for rel in t.get("relations", []):
            edges.append({
                "source": tid,
                "target": rel["target"],
                "weight": rel.get("weight", 1),
                "relation_type": rel.get("type", "co-occurs"),
            })

    # add implicit co-occurrence edges (docs shared between topics)
    topic_doc_sets = {tid: set(t["doc_ids"]) for tid, t in topic_map["topics"].items()}
    for tid_a, docs_a in topic_doc_sets.items():
        for tid_b, docs_b in topic_doc_sets.items():
            if tid_a >= tid_b:  # avoid dupes + self-edges
                continue
            shared = docs_a & docs_b
            if len(shared) >= 2:
                # check if edge already exists explicitly
                existing = any(
                    (e["source"] == tid_a and e["target"] == tid_b) or
                    (e["source"] == tid_b and e["target"] == tid_a)
                    for e in edges
                )
                if not existing:
                    edges.append({
                        "source": tid_a,
                        "target": tid_b,
                        "weight": len(shared),
                        "relation_type": "co-occurs",
                        "shared_docs": sorted(shared),
                    })

    return {
        "schema_version": "1.0",
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "n_nodes": len(nodes),
            "n_edges": len(edges),
            "n_explicit_edges": sum(1 for e in edges if e["relation_type"] != "co-occurs"),
            "n_cooccur_edges": sum(1 for e in edges if e["relation_type"] == "co-occurs"),
        }
    }


# ============================================================
# Build corpus stats
# ============================================================
def build_corpus_stats(docs):
    n_words_estimate = 0
    type_dist = Counter()
    register_dist = Counter()
    year_dist = Counter()
    for doc_id, d in docs.items():
        type_dist[d.get("doc_type", "?")] += 1
        register_dist[d.get("voice_register", "?")] += 1
        dt = d.get("date", "")
        if dt and len(dt) >= 4:
            year_dist[dt[:4]] += 1

    return {
        "n_docs": len(docs),
        "doc_type_distribution": dict(type_dist),
        "voice_register_distribution": dict(register_dist),
        "year_distribution": dict(sorted(year_dist.items())),
        "n_canonical_topics": len(TOPIC_TAXONOMY),
        "n_canonical_people": len(PEOPLE_ALIASES),
        "n_canonical_cases": len(CASE_ALIASES),
        "n_canonical_laws": len(LAW_ALIASES),
        "n_frameworks": len(FRAMEWORK_INDEX),
    }


# ============================================================
# Main
# ============================================================
def main():
    print(">> Loading 89 raw extractions...")
    docs = load_all_docs()
    assert len(docs) == 89, f"expected 89 docs, got {len(docs)}"

    print(">> Building corpus stats...")
    stats = build_corpus_stats(docs)

    print(">> Building entity index (people / cases / laws)...")
    entity_index, unrecognized = build_entity_index(docs)

    print(">> Building framework index...")
    frameworks = build_framework_index(docs)

    print(">> Building signature-phrase library...")
    sig_library = build_signature_library(docs)

    print(">> Aggregating per-topic stats...")
    topic_map = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_stats": stats,
        "topics": {},
    }
    for tid, tdef in TOPIC_TAXONOMY.items():
        agg = aggregate_topic(tid, tdef, docs, frameworks)
        if agg:
            topic_map["topics"][tid] = agg

    print(">> Building topic graph...")
    graph = build_topic_graph(topic_map)

    # ============== Write all artifacts ==============
    print(">> Writing artifacts...")
    with open(f"{OUT_DIR}/topic_map.json", "w") as f:
        json.dump(topic_map, f, indent=2, ensure_ascii=False)

    with open(f"{OUT_DIR}/topic_graph.json", "w") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    with open(f"{OUT_DIR}/entity_index.json", "w") as f:
        json.dump(entity_index, f, indent=2, ensure_ascii=False)

    with open(f"{OUT_DIR}/frameworks.json", "w") as f:
        json.dump(frameworks, f, indent=2, ensure_ascii=False)

    with open(f"{OUT_DIR}/signature_library.json", "w") as f:
        json.dump(sig_library, f, indent=2, ensure_ascii=False)

    with open(f"{OUT_DIR}/corpus_stats.json", "w") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    # Unrecognized entities for review (Pass B speech ingestion will use this)
    review = {
        "people_unrecognized": dict(unrecognized["people"].most_common(50)),
        "cases_unrecognized": dict(unrecognized["cases"].most_common(50)),
        "laws_unrecognized": dict(unrecognized["laws_treaties"].most_common(50)),
    }
    with open(f"{OUT_DIR}/_unrecognized_for_review.json", "w") as f:
        json.dump(review, f, indent=2, ensure_ascii=False)

    print()
    print("============= STAGE 3 COMPLETE =============")
    print(f"Topics: {len(topic_map['topics'])}")
    print(f"Graph nodes: {graph['stats']['n_nodes']}")
    print(f"Graph edges: {graph['stats']['n_edges']} "
          f"({graph['stats']['n_explicit_edges']} explicit + "
          f"{graph['stats']['n_cooccur_edges']} co-occurrence)")
    print(f"Sig phrases: {len(sig_library)}")
    print(f"Frameworks: {len(frameworks)}")
    print(f"Recognized people: {sum(1 for p in entity_index['people'].values() if p['doc_count'] > 0)}/{len(entity_index['people'])}")
    print(f"Recognized cases: {sum(1 for p in entity_index['cases'].values() if p['doc_count'] > 0)}/{len(entity_index['cases'])}")
    print(f"Unrecognized people (top 10):")
    for n, c in unrecognized["people"].most_common(10):
        print(f"  {c}× {n}")


if __name__ == "__main__":
    main()
