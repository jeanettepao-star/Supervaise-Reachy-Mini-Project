# app/ — MANIFEST (develop)

The runnable retrieval + voice pipeline for the **`develop`** architecture
(bge-base embeddings + BM25 + RRF + 34-topic centroids + top-p nucleus cutoff;
streamed Sonnet compose; two-part theme+topic filler → gapless TTS). Source of
truth: [`../docs/handover_claude_code_2026-07-18.md`](../docs/handover_claude_code_2026-07-18.md).

**Entrypoints (develop):** the headless text seam is
`python app/service.py --query "…"`; the live voice demo is
`streamlit run streamlit_voice_demo.py` (repo root). `cj_chat.py` and
`dashboard.py` are legacy-guarded (`CJ_ALLOW_LEGACY=1`) and are **not** used on
`develop`.

## Core pipeline modules

| ID | File | Description |
|---|---|---|
| 0001 | [README.md](README.md) | App-scoped run instructions (develop). Touch when install steps, env vars, or quick-start commands change. |
| 0002 | [service.py](service.py) | Streamed Sonnet composer (`compose_streamed`), `build_payload`, envelope split/stream (`_split_envelope` / `_stream_native` — the `---ENVELOPE---` sentinel + JSON is never spoken), the versioned `answer()` service contract, and transport resolution (`native_sdk` / `schannel_curl`). |
| 0003 | [retrieval.py](retrieval.py) | Deterministic retrieval: `input_gate`, `route` (centroid soft-prior), `retrieve` (dense+BM25 RRF fuse → top-p nucleus), `run`/`run_timed`. Home of the DARK-by-default date-index and entity-rescue branches. |
| 0004 | [embeddings.py](embeddings.py) | Resident bge-base-en-v1.5 dense arm (loaded once). Carries the pyarrow-before-torch DLL-order guard. |
| 0005 | [sparse.py](sparse.py) | BM25 sparse arm + curated atomic-phrase dictionary (shared tokenizer, greedy longest-match). |
| 0006 | [filler_route.py](filler_route.py) | Filler v5 routing + LOCKED clip text: `decide()` gates (theme/topic thresholds, NEUTRAL triggers), theme variants, neutral pool, topic templates, grammar check. Pure `$0` logic. |
| 0007 | [voice_job.py](voice_job.py) | Threaded filler+synth job machinery, **Streamlit-free and `$0`-testable**: the v5 sequencer, reservation-index invariant, watchdog. Reused by the voice demo (and the intended robot loop). |
| 0008 | [voice_stream.py](voice_stream.py) | `SentenceChunker` + the pluggable `TTS` protocol (`SapiTTS`; `PiperTTS` robot drop-in) + `speak_stream` (latency harness backbone). |
| 0009 | [voice_io.py](voice_io.py) | STT/TTS helper layer; reads the `OPENAI_*` config knobs. |
| 0010 | [requirements.txt](requirements.txt) | Runtime deps. NOTE the hard pins `pyarrow==21.0.0` (torch DLL-order fix) and `rank-bm25==0.2.2` (byte-reproducible sparse index) — do not touch. |

## Legacy kiosk surfaces (CJ_ALLOW_LEGACY-guarded)

| ID | File | Description |
|---|---|---|
| L0001 | [app.py](app.py) | Push-to-talk "museum kiosk" (pre-W1.8, Haiku router). Belongs to `pre-wake-word-integration`; imports `cj_chat`. |
| L0002 | [cj_chat.py](cj_chat.py) | Pre-W1.8 CLI + kiosk pipeline. Exits unless `CJ_ALLOW_LEGACY=1`; the develop entry is `service.py`. |
| L0003 | [dashboard.py](dashboard.py) | Pre-W1.8 Streamlit operator UI. Exits unless `CJ_ALLOW_LEGACY=1`; the develop voice surface is `streamlit_voice_demo.py`. |

## Subdirectories

| ID | Path | Description |
|---|---|---|
| S0001 | voices/ | Local TTS assets. On-device/robot TTS uses Piper (`en_US-ryan-medium`, `app/voices/piper/`) — gitignored, installed per machine; see [../docs/robot/PIPER_SETUP.md](../docs/robot/PIPER_SETUP.md). |

## Removed

`app/artifacts/` previously held the 89-doc legacy pipeline's materialised topic
map, voice card, router prompt, frameworks, entity index, signature library,
topic graph, and per-doc extractions. PLAN-0001 §A migrated the runtime to
consume `corpus/voice/` and `corpus/{columns,speeches}/` directly (and, on
`develop`, the chunked retrieval index at `corpus/index/chunks.jsonl` +
`data/index/`); the legacy directory was deleted in the cleanup commit that
followed.
