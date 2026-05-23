# source_materials/ — MANIFEST

Original published writing by Artemio V. Panganiban — the substrate the
corpus pipeline turns into topic extractions. ~150K words across 65
*Philippine Daily Inquirer* "With Due Respect" columns (2011–2026) and
*A Centenary of Justice* (1 book, 19 chapters + 4 appendices + front
matter = 25 files).

| ID | File | Description |
|---|---|---|
| 0001 | [manifest.json](manifest.json) | Inventory and counts for the columns and book directories. Touch when adding new source material (e.g., Pass B speeches). |

## Subdirectories

| ID | Path | Description |
|---|---|---|
| S0001 | [columns/](columns/) | 65 *Philippine Daily Inquirer* "With Due Respect" columns, dated 2011-07-03 through 2026-03-30. Filename pattern `YYYY-MM-DD_slug.md`. Each is one column, one topic. Mirrored into per-doc extractions under `corpus/analysis/topics/col_YYYY_MMDD.json`. Do not edit — these are publication source-of-truth. |
| S0002 | [books/book_01_centenary-of-justice/](books/book_01_centenary-of-justice/) | *A Centenary of Justice* (2001) — 25 markdown files: `00_front-matter.md`, `01_*`…`19_*` (19 chapters), `appendix-a_*`…`appendix-d_*` (4 appendices), plus a `metadata.json`. Each file becomes one Stage-1 extraction (`book_01_ch01.json` … `book_01_appendix-d.json`). Do not edit. |
