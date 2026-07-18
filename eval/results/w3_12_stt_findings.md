# W3.12 — STT findings (durable record) — 2026-07-18

Findings from the voice-demo sessions (OpenAI `whisper-1`, `response_format=verbose_json`). The raw
per-question log `eval/results/voice_demo_log.csv` is **operator state (not committed)**; the
relevant evidence is captured here so the findings survive without the log.

## Finding #1 — STT latency (swappable edge)
Real human-speech STT ran **~1.1–2.6 s** per question (log `stt_seconds`: 5.42 / 1.14 / 2.56 / 1.66
across the FLP-question sessions on 2026-07-18). This is an OpenAI-hosted demo edge; the robot
re-measures with on-device STT at RI-701. Not on the transferable core.

## Finding #2 — mishears on legal / proper-noun terms
Domain terms are the STT failure surface — flagged for the demo script: **"Echegaray"**,
**"certiorari"**, Filipino proper nouns. Mitigation is TEST mode (confirm/edit transcript before
compose) and, on the robot, a domain-biased STT or a small correction map. No pipeline change.

## Finding #3 — Tagalog language mis-tag (the quirk)
`whisper-1` intermittently returns **`language="tagalog"`** for questions that are **entirely in
English** but carry Philippine legal/proper-noun context (e.g. "Foundation for Liberty and
Prosperity", "Echegaray"). Observed live in the demo's STT caption (`lang=…`) across multiple runs.

**Impact: cosmetic / none.** The pipeline uses only the **transcript text**, never the detected
language — routing, retrieval, and compose are language-tag-agnostic. The transcript itself was
correct English in every observed case; only the `language` field was mislabeled. No fix required;
recorded so a future reader who sees "tagalog" in an STT payload knows it is a known benign quirk,
not a routing input.

*Basis: 2026-07-18 voice-demo sessions. The `language` value is surfaced in the demo UI caption but
is not a column in the (operator-state) CSV, so it is documented here as an observed finding rather
than a committed data row.*
