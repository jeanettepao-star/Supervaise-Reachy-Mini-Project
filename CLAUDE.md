# CLAUDE.md

A conversation app that speaks as retired Philippine Chief Justice
Artemio V. Panganiban, grounded in his published corpus; demo target
**May 30, 2026**.

This file is the navigational entry point for any Claude Code or LLM
agent opening this repo. It points to where things live — not what
they do.

## Read first

Three documents are the source of truth. Read them in this order before
making changes:

| Doc | What it gives you |
|---|---|
| [docs/handover_claude_code_2026-05-26.md](docs/handover_claude_code_2026-05-26.md) | Latest implementation reality — what runs, what's wired, gaps between intent and reality. Supersedes the 05-16 handover. |
| [docs/handover_claude_code_2026-05-16.md](docs/handover_claude_code_2026-05-16.md) | Prior implementation snapshot — kept for diff context. |
| [PROJECT.md](PROJECT.md) | Runtime tuning detail — pipeline architecture, cost model, performance numbers, troubleshooting, config. |

For **planning artifacts** introduced during the Phase 1-3 corpus
work, the entry points are:

| Doc | What it gives you |
|---|---|
| [docs/MANIFEST.md](docs/MANIFEST.md) | Index of all governance subdirectories — handover snapshots, ADRs, lessons, plans, test specs, persona guides. |
| [docs/implementation-plans/MANIFEST.md](docs/implementation-plans/MANIFEST.md) | 7 phase-aligned plans (runtime app, web UI, embedding audit, biography ingest, book corpus, voice/TTS, taxonomy evolution). |
| [docs/test-specs/MANIFEST.md](docs/test-specs/MANIFEST.md) | 5 verification specs (generator contract, matchers, topic_paths, voice card protocol, end-to-end smoke). |
| [docs/guides/MANIFEST.md](docs/guides/MANIFEST.md) | 4 persona-scoped guides (end-user, reviewer, admin, manager). |

The strategic handover (`docs/handover_strategic_2026-05-17.md`) and a
corpus pipeline companion are referenced elsewhere but are **not on
disk in this repo** as of the time this file was written. If they
appear later, they take precedence over implementation docs for
*design intent* questions.

## Subdirectory index

| Path | Purpose | MANIFEST |
|---|---|---|
| [`app/`](app/) | The runnable conversation app — CLI entrypoint, Streamlit dashboard, requirements, voice/Piper local assets. | [app/MANIFEST.md](app/MANIFEST.md) |
| [`app/artifacts/`](app/artifacts/) | Corpus artifacts loaded at app startup — voice card, router prompt, topic map/graph, entity index, frameworks, signature library, 89 per-doc topic extractions. | [app/artifacts/MANIFEST.md](app/artifacts/MANIFEST.md) |
| [`corpus/`](corpus/) | The source corpus and pre-processing pipeline. Phase 1-3 added: `corpus/columns/`, `corpus/speeches/`, `corpus/biography/` (79 paired `.md` + `.json`), and `corpus/voice/{topic_map.json,voice_card.md}`. Re-runnable. | [corpus/MANIFEST.md](corpus/MANIFEST.md) |
| [`scripts/`](scripts/) | The Phase 1-3 pipeline scripts: `generate_corpus_files.py`, `build_topic_map.py`, `apply_topic_paths.py`. Idempotent. | — |
| [`data/`](data/) | Phase 1 inputs: `data/csv/` (3 curated CSVs) and `data/text/` (80 source `.txt` files). | — |
| [`docs/`](docs/) | Handover docs, ADRs (`docs/decisions/`), lessons (`docs/lessons/`), implementation plans (`docs/implementation-plans/`), test specs (`docs/test-specs/`), persona guides (`docs/guides/`). | [docs/MANIFEST.md](docs/MANIFEST.md) |

> The earlier `source_materials/` tree (65 *Inquirer* columns + 25
> *A Centenary of Justice* chapter/appendix files) is being retired
> in favour of the curated `data/csv/` + `data/text/` inputs that
> drive Phases 1-3. The deletion is staged but not yet committed;
> the book sections will return under `corpus/books/` per
> [PLAN-0005](docs/implementation-plans/PLAN-0005-book-corpus-addition.md).

## Conflict resolution

When documents disagree:

- **Implementation facts** (what code exists, file:line, what runs) → the latest Claude Code handover wins ([docs/handover_claude_code_2026-05-16.md](docs/handover_claude_code_2026-05-16.md)).
- **Design intent** (why a choice was made, scope, audience, the May 30 target) → the strategic handover wins when present; otherwise [PROJECT.md](PROJECT.md) and the relevant ADR in [docs/decisions/](docs/decisions/).
- **Corpus pipeline mechanics** (Stage 1 / Stage 3, prompts, synthesis scripts) → the corpus pipeline companion doc wins when present; otherwise [corpus/build_kit/README.md](corpus/build_kit/README.md) and [corpus/prompts/](corpus/prompts/).

## What this repo is NOT

- **Not RAG / no embeddings.** Routing is a Haiku call against a hand-curated taxonomy (35 topics post-Phase-2; previously 37); there is no vector store and no similarity search.
- **Not a robot embodiment for May 30.** Reachy Mini integration is explicitly out of scope per the build-kit README; the demo is a conversation app on a laptop. See [ADR-0005](docs/decisions/0005-defer-robot-embodiment-for-may-30.md).
- **No automated tests yet.** Verification is currently manual via the six build-kit sanity questions plus interactive dashboard runs. Test *specifications* exist in [docs/test-specs/](docs/test-specs/); converting them into a runnable suite is part of the runtime work in [PLAN-0001](docs/implementation-plans/PLAN-0001-runtime-app-haiku-router-sonnet-composer.md).
