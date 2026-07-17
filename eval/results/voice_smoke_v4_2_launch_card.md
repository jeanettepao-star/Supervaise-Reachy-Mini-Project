# Voice smoke test — v4.2 full-pipeline (human-driven) — launch card 2026-07-18

**Pre-flight: ALL PASS.** Not launched by CC — the human runs it and asks by voice.

## Pre-flight results
| Check | Result |
|---|---|
| HEAD ≥ arch-baseline-v4.2 | HEAD `029014d` ; v4.2 `9ef1f5c` is ancestor; changes since = **docs only** (CLAUDE.md + 2 handovers) → pipeline IS the v4.2 state |
| Pipeline state | full-corpus centroids (34×768), corpus_dense (9865×768), batch-02 BM25 — unchanged since the tag |
| Demo drives v4.2 | `streamlit_voice_demo.py`: `service._allowlist("v4")` → `retrieval.run` → `service._directives` → `service.compose_streamed`. NOT legacy. NEW-1 guard (c943c34) fences app.py/dashboard.py/cj_chat.py/run_smoke_test.py; this entry is unaffected. |
| Env pin | `pyarrow==21.0.0` pinned (d1547e8); bge-base loaded fine this session (not re-crash-tested) |
| TTS fix (b2e5984) | **per-sentence pipelined** producer/consumer + `gapless_audio` Web-Audio component; two-chunk fallback removed. "Fixed" = continuous audio, seam ≈ 0 ms |
| Credit gate | **live probe OK on BOTH** — Anthropic returned a completion, OpenAI tts-1 returned 9600 bytes. Not exhausted. transport = `native_sdk` (native TLS healthy). |

> Credit caveat: exact remaining balance is not API-queryable on either provider. The live probe proves **non-exhaustion** (the real gate — "cannot run creditless"). Ensure ~**$1** headroom before the 15-question run (≈ 5–6¢ each).

## Launch (PowerShell, from repo root)
```powershell
cd "C:\Reachy Mini Project 2026"
.\.venv\Scripts\Activate.ps1
$env:HF_HUB_OFFLINE = "1"          # avoids a hub round-trip on model load (optional)
streamlit run streamlit_voice_demo.py --server.headless false
```
- Keys load automatically from `app/.env` (both `ANTHROPIC_API_KEY` + `OPENAI_API_KEY` — the app hard-stops if either is missing).
- Opens **http://localhost:8501**. **Click "🔊 Enable audio" once** (browser autoplay rule) BEFORE the first question.
- **Allow microphone** when the browser prompts.
- Sidebar **Mode**: `TEST (confirm transcript)` first (lets you verify STT before compose) → switch to `DEMO (auto-submit)` for the flowing demo.
- **Ctrl+C** in the terminal to stop.
- **Q1 pays the ~30–40 s embedder cold load — judge latency from Q2 onward.**

## 12-question smoke script (pass-conditions)
| # | Ask by voice | Expected / PASS condition |
|---|---|---|
| 1 | "What is judicial independence, and why does it matter?" | ANSWERS, grounded, in-voice |
| 2 | "Tell me about the Foundation for Liberty and Prosperity." | ANSWERS, grounded (Q2 = first *fair* latency read) |
| 3 | "What does the rule of law mean to you?" | ANSWERS, grounded, in-voice |
| 4 | "What can you say about the Museum of Liberty and Prosperity?" | ANSWERS (in-pilot entity; note: entity-rescue is DARK, so this tests the normal path) |
| 5 | "What's the weather in Manila today?" | **DECLINES** via OOS wording ("that is not something I can speak to here"), clean + FAST, cites nothing |
| 6 | "Can you recommend a good restaurant near the museum?" | **DECLINES** cleanly; the bare word "museum" must NOT drag it into a Museum answer |
| 7 | "What can you say about your Baron Travel entrepreneurship?" | **Graceful decline** (out-of-pilot, Decision B). PASS = declines honestly, NO "does not exist in my record" false claim. FAIL only if it fabricates or crashes |
| 8 | "Who are you?" | Identity answer, in-voice (Chief Justice persona) |
| 9 | "Should I sue my neighbor over a property line dispute?" | NEW-6 not implemented → a normal answer is EXPECTED; **LOG whether it over-advises** (evidence for pending NEW-6, not pass/fail) |
| 10 | "What should I do about my pending court case?" | same as #9 — LOG over-advising |
| 11 | *(deliberately mumbled)* "What's your take on the **Echegaray** death-penalty ruling?" | STT robustness — **log the transcript verbatim**; watch "Echegaray" mishear + any lang=tagalog mis-tag |
| 12 | *(spoken clearly)* "How does a petition for **certiorari** reach the Supreme Court?" | STT robustness on a clear legal term — **log the transcript**; answer should be grounded |

## PRIMARY findings to capture (two columns + the CSV)
1. **Inter-chunk TTS gap** — THE thing under test (b2e5984). Must be continuous / < ~0.5 s between sentences. Note any audible seam.
2. **Felt-TTFA** from Q2 onward (Q1 is cold-load, ignore).
3. **STT mishears** — especially "Echegaray" / "certiorari"; any Tagalog mis-tag.
4. **Envelope text must NEVER be spoken** (the `---ENVELOPE---` JSON is metadata; the chunker stops at the sentinel). If you ever hear JSON/field names read aloud → FAIL.
5. **Decline quality** — in-character and warm vs robotic (Q5–7).

The app appends a row per question to **`eval/results/voice_demo_log.csv`** (STT/compose/TTS timings, packed per-chunk `i:synth_ms/gap_ms`, mean/max gap). It's operator state — do not clean it.
