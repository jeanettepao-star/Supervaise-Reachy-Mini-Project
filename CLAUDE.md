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
| [docs/handover_claude_code_2026-05-16.md](docs/handover_claude_code_2026-05-16.md) | Implementation reality — what runs, what's wired, gaps between intent and reality (§7), open bugs (§8), immediate next actions (§10), questions for the human (§11). Supersedes the 05-15 handover. |
| [docs/handover_claude_code_2026-05-15.md](docs/handover_claude_code_2026-05-15.md) | The previous implementation snapshot — kept for diff context. The 05-16 doc lists what changed. |
| [PROJECT.md](PROJECT.md) | Runtime tuning detail — pipeline architecture, cost model, performance numbers, troubleshooting, config. |

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
| [`corpus/`](corpus/) | The source corpus and pre-processing pipeline — build kit, prompts, deterministic synthesis scripts, analysis outputs. Re-runnable. | [corpus/MANIFEST.md](corpus/MANIFEST.md) |
| [`source_materials/`](source_materials/) | Original published writing — 65 *Inquirer* columns (2011–2026) and *A Centenary of Justice* (25 chapter/appendix files). | [source_materials/MANIFEST.md](source_materials/MANIFEST.md) |
| [`docs/`](docs/) | Handover docs, ADRs (`docs/decisions/`), and lessons (`docs/lessons/`). | [docs/MANIFEST.md](docs/MANIFEST.md) |

## Conflict resolution

When documents disagree:

- **Implementation facts** (what code exists, file:line, what runs) → the latest Claude Code handover wins ([docs/handover_claude_code_2026-05-16.md](docs/handover_claude_code_2026-05-16.md)).
- **Design intent** (why a choice was made, scope, audience, the May 30 target) → the strategic handover wins when present; otherwise [PROJECT.md](PROJECT.md) and the relevant ADR in [docs/decisions/](docs/decisions/).
- **Corpus pipeline mechanics** (Stage 1 / Stage 3, prompts, synthesis scripts) → the corpus pipeline companion doc wins when present; otherwise [corpus/build_kit/README.md](corpus/build_kit/README.md) and [corpus/prompts/](corpus/prompts/).

## What this repo is NOT

- **Not RAG / no embeddings.** Routing is a Haiku call against a 37-topic hand-curated taxonomy; there is no vector store and no similarity search.
- **Not a robot embodiment for May 30.** Reachy Mini integration is explicitly out of scope per the build-kit README; the demo is a conversation app on a laptop.
- **No automated tests.** Intentional — verification is manual smoke tests against six build-kit sanity questions plus interactive dashboard runs. Adding a minimal pytest suite is the #1 next action in the 05-16 handover.
