# docs/ — MANIFEST

Project documentation. Two kinds: dated handover snapshots
(`handover_claude_code_YYYY-MM-DD.md`) that record implementation state
at a point in time, and the governance subdirectories — `decisions/`
for MADR 4.0 ADRs and `lessons/` for 5-Why root-cause writeups.

| ID | File | Description |
|---|---|---|
| 0001 | [handover_claude_code_2026-05-15.md](handover_claude_code_2026-05-15.md) | Implementation handover snapshot, 2026-05-15. Superseded by the 05-16 doc — read only for diff context. |
| 0002 | [handover_claude_code_2026-05-15.pdf](handover_claude_code_2026-05-15.pdf) | PDF rendering of the 05-15 handover (61 KB, 16 pages). Generated via `xhtml2pdf`. |
| 0003 | [handover_claude_code_2026-05-16.md](handover_claude_code_2026-05-16.md) | Latest implementation handover — implementation reality as of 2026-05-16. Adds prompt caching (commit `f7e47a1`). This is the document to read first for "what's actually wired right now." |

## Subdirectories

| ID | Path | Description |
|---|---|---|
| S0001 | [decisions/](decisions/) | MADR 4.0 architecture decision records — see [decisions/MANIFEST.md](decisions/MANIFEST.md). |
| S0002 | [lessons/](lessons/) | 5-Why root-cause analyses for things that surprised us — see [lessons/MANIFEST.md](lessons/MANIFEST.md). |
