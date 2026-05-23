# docs/lessons/ — MANIFEST

Lessons learned, written as 5-Why root-cause analyses. One file per
surprise — the kind of "I would not have predicted this" finding that
is worth carrying into the next project. Append-only IDs.

| ID | File | Description |
|---|---|---|
| 0001 | [LL-001-cache-savings-18-not-55.md](LL-001-cache-savings-18-not-55.md) | Prompt-caching savings were 18%, not the projected 55% — overestimated voice card's share of inference input. |
| 0002 | [LL-002-haiku-ignores-cache-control.md](LL-002-haiku-ignores-cache-control.md) | Haiku 4.5 silently ignores `cache_control`; only Sonnet honors it on this SDK version. |
| 0003 | [LL-003-dotenv-override-false.md](LL-003-dotenv-override-false.md) | `python-dotenv`'s default `override=False` silently kept an empty shell-set `ANTHROPIC_API_KEY`. |
| 0004 | [LL-004-streamlit-caches-imported-modules.md](LL-004-streamlit-caches-imported-modules.md) | Streamlit caches imported modules across reloads — edits to `cj_chat.py` need Ctrl+C, not just dashboard reload. |
| 0005 | [LL-005-signature-library-loaded-but-unused.md](LL-005-signature-library-loaded-but-unused.md) | `signature_library.json` is loaded into memory but never reaches the inference call — 684 phrases contributing nothing. |
