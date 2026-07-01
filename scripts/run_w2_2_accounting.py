"""W2.2 Phase 1-2 (FREE, no API): token accounting old-lean vs new-slim payload
over all 40 frozen queries + grounding guard. Estimator = chars/4 (consistent
with corpus n_tokens_est; the paid probe gives ground-truth usage)."""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Reachy Mini Project 2026")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
import config, service, retrieval  # noqa: E402

OUT = ROOT / "reports" / "pilot-eval subset" / "w2_2_free_accounting.json"
SLIM_TOP_K = 6            # grounding-safe (worst first-grounded rank = 5)
def tok(s): return len(s) // 4
def did(c): return c.split("::")[0]

allow = service._allowlist("v4")
Q = json.loads((ROOT / "reports/pilot-eval subset/draft_queries_v1.json").read_text(encoding="utf-8"))["queries"]
docj = service._doc_json()
ENRICH_FIELDS = ["signature_phrases", "stances", "decision_framework_signals",
                 "target_audience", "register_markers", "one_paragraph_summary"]

rows = []
ground_losses = []
for q in Q:
    r = retrieval.run(q["query"], allow)
    sel = r["retrieval"]["selected"]
    directives = service._directives(q["query"], r["route"])
    lean = service.build_payload(q["query"], sel, directives, top_k=12, signature=False)
    slim = service.build_payload(q["query"], sel, directives, top_k=SLIM_TOP_K, signature=False)
    # RICH (hypothetical workbook payload) = lean + per-unique-doc enrichment
    docs12 = list(dict.fromkeys(did(c) for c, _, _ in sel[:12]))
    enrich = "".join(json.dumps({f: (docj.get(dd, {}) or {}).get(f) for f in ENRICH_FIELDS},
                                ensure_ascii=False) for dd in docs12)
    rich = lean + "\n<doc_enrichment>\n" + enrich + "\n</doc_enrichment>"
    # component estimates
    chunk_txt = service._chunk_text()
    ch_lean = sum(len(chunk_txt.get(c, "")) for c, _, _ in sel[:12]) // 4
    ch_slim = sum(len(chunk_txt.get(c, "")) for c, _, _ in sel[:SLIM_TOP_K]) // 4
    # grounding guard: expected docs still present in slim top-k?
    exp = q.get("expected_grounding_doc_ids") or []
    slim_docs = {did(c) for c, _, _ in sel[:SLIM_TOP_K]}
    lost = [e for e in exp if e not in slim_docs]
    if lost:
        ground_losses.append((q["id"], lost))
    rows.append({"id": q["id"], "type": q["type"], "theme": q["theme"],
                 "lean_tok": tok(lean), "slim_tok": tok(slim), "rich_tok": tok(rich),
                 "chunk_tok_lean": ch_lean, "chunk_tok_slim": ch_slim,
                 "n_sel": len(sel), "exp": exp, "ground_lost": lost})

def mean(k): return round(float(np.mean([r[k] for r in rows])), 1)
lean_m, slim_m, rich_m = mean("lean_tok"), mean("slim_tok"), mean("rich_tok")
red = lean_m - slim_m
print(f"n={len(rows)} | SLIM_TOP_K={SLIM_TOP_K}")
print(f"mean input tokens (chars/4):  lean(12)={lean_m}  slim({SLIM_TOP_K})={slim_m}  "
      f"rich(12+enrich)={rich_m}")
print(f"SLIM vs LEAN reduction: {red:.0f} tok/query  ({red/lean_m*100:.1f}%)")
print(f"  breakdown: chunks lean={mean('chunk_tok_lean')} -> slim={mean('chunk_tok_slim')} "
      f"(the ENTIRE reduction is chunk-side); directives+scaffold ~unchanged")
print(f"ENRICHMENT AVOIDED (lean vs rich): rich would add {rich_m-lean_m:.0f} tok/query "
      f"({(rich_m-lean_m)/lean_m*100:.0f}% bloat) — the lean contract already omits it")
print(f"GROUNDING GUARD at top_k={SLIM_TOP_K}: losses={ground_losses or '0 (all expected docs retained)'}")

OUT.write_text(json.dumps({
    "slim_top_k": SLIM_TOP_K, "estimator": "chars/4 (matches corpus n_tokens_est)",
    "mean_input_tok": {"lean_12": lean_m, "slim_6": slim_m, "rich_12_plus_enrichment": rich_m},
    "slim_vs_lean_reduction_tok": round(red, 1),
    "slim_vs_lean_reduction_pct": round(red / lean_m * 100, 1),
    "chunk_tok_mean": {"lean_12": mean("chunk_tok_lean"), "slim_6": mean("chunk_tok_slim")},
    "enrichment_avoided_tok_per_query": round(rich_m - lean_m, 1),
    "grounding_losses_at_slim": ground_losses,
    "per_query": rows,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("wrote", OUT.name)
