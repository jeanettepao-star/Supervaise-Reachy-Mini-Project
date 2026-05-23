# corpus/ — MANIFEST

The source corpus and the deterministic pre-processing pipeline that
produced the artifacts the app consumes. `build_kit/` is the design
spec; `prompts/` holds the LLM-driven extraction/design prompts;
`synthesis_scripts/` is the deterministic Python that aggregates Stage-1
outputs into the Stage-3 canonical layer; `analysis/` is the output of
running that pipeline.

| ID | File | Description |
|---|---|---|
| 0001 | [manifest.json](manifest.json) | Top-level corpus manifest — counts and metadata for columns and books. Touch when the source-material inventory changes. |

## Subdirectories

| ID | Path | Description |
|---|---|---|
| S0001 | [build_kit/](build_kit/) | The original build-kit spec: `README.md` (design intent), `voice_card.md` (upstream inference prompt), `router_prompt.md` (upstream router prompt), `cj_chat.py` (reference implementation). Treat as the spec — edits cascade to `app/artifacts/` copies. |
| S0002 | [prompts/](prompts/) | LLM prompts for the corpus pipeline: `stage_1a_extraction.md` (per-doc extraction) and `stage_3_design.md` (synthesis design notes). |
| S0003 | [synthesis_scripts/](synthesis_scripts/) | Deterministic Python that turns Stage-1 per-doc JSON into the Stage-3 canonical artifacts: `taxonomy.py`, `synthesize.py`, `make_summary.py`, `aliases.py`, `stage_3_design.md`. Re-runnable. |
| S0004 | [analysis/](analysis/) | Pipeline outputs. `analysis/topics/` is the Stage-1 per-doc layer (89 JSON files, one per source document — source of truth). `analysis/synthesis/` is the Stage-3 canonical layer (`topic_map.json`, `topic_graph.json`, `entity_index.json`, `frameworks.json`, `signature_library.json`, `_unrecognized_for_review.json`, `corpus_stats.json`, `SUMMARY.md`). `app/artifacts/` mirrors these for the runtime. |
