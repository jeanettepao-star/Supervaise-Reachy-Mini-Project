# CJ Panganiban Conversation App — `app/` (develop)

The runnable pipeline that speaks as retired Philippine Chief Justice Artemio V.
Panganiban, grounded in his published corpus via an embeddings retrieval
pipeline.

> **Branch check.** This describes the **`develop`** architecture (bge-base
> embeddings + BM25 + RRF + centroids + nucleus cutoff). The single source of
> truth is [`../docs/handover_claude_code_2026-07-18.md`](../docs/handover_claude_code_2026-07-18.md).
> The push-to-talk kiosk (`app/app.py`, Haiku router, no embeddings) belongs to
> the `pre-wake-word-integration` branch.

## Pipeline

```
[mic]
  ↓ STT — OpenAI whisper-1 (default; STT_BACKEND=local → faster-whisper)
User question (text)
  ↓ input_gate + route — LOCAL zero-LLM (embed bge-base 768d → cosine vs 34 centroids → softmax)
  ↓ retrieve — dense pilot (827) + BM25 (same docs) → RRF (K=60) → passage_sim + LAMBDA·affinity
              → top-p nucleus cutoff (floor MIN_K)
  ↓ compose — ONE streamed Claude Sonnet 4.6 call (cached Voice-Card; prose then ---ENVELOPE--- + JSON)
Response text (streamed)
  ↓ two-part theme+topic filler (v5) → OpenAI tts-1 (pipelined) → gapless playback
[speakers]
```

`llm_calls_before_composition = 0` — the router is deterministic and local; the
streamed compose is the only pipeline API round-trip. STT/TTS are separate OpenAI
calls on the demo topology.

## Quick start

Requires **both** `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` in `app/.env` (see
[`.env.example`](.env.example)).

```bash
# headless, text-only (no audio, no STT/TTS) — the fastest sanity check
../.venv/Scripts/python.exe service.py --query "What is the rule of law?"

# full voice demo (run from the repo ROOT, not app/)
../.venv/Scripts/python.exe -m streamlit run ../streamlit_voice_demo.py
```

`service.py --query` prints the route, per-stage retrieval timing, the selected
chunk_ids, and the composed answer.

> **Legacy, guarded.** `cj_chat.py` (CLI) and `dashboard.py` (Streamlit) are the
> pre-W1.8 kiosk stack; both `raise SystemExit(2)` unless `CJ_ALLOW_LEGACY=1`.
> They are **not** the develop entrypoints — use `service.py` /
> `streamlit_voice_demo.py`.

## Setup on a clean clone

Follow [`../docs/RUNBOOK_clean_clone.md`](../docs/RUNBOOK_clean_clone.md) — it
covers the venv, the `pyarrow==21.0.0` pin, `ANTHROPIC_API_KEY` + `OPENAI_API_KEY`,
rebuilding the gitignored dense/sparse indices, regenerating the filler clips,
the Avast Service-host profile, and Piper (for the local/robot TTS path).

## Modules

| File | Role |
|---|---|
| `service.py` | Streamed Sonnet compose, `build_payload`, envelope split/stream (`---ENVELOPE---` never spoken), the versioned `answer()` service contract, transport resolution (native_sdk / schannel_curl). |
| `retrieval.py` | `input_gate`, `route` (centroid soft-prior), `retrieve` (dense+BM25 RRF fuse + top-p nucleus), `run` (per-stage timing). Home of the DARK date-index / entity-rescue branches. |
| `embeddings.py` | Resident bge-base dense arm (`get_model`, `embed_query/documents`, `load_dense_index`, `dense_score`). Carries the pyarrow-before-torch DLL-order guard. |
| `sparse.py` | BM25 arm + curated atomic-phrase dictionary (shared tokenizer, greedy longest-match). |
| `filler_route.py` | v5 two-part theme+topic filler: `decide()` gates + the LOCKED clip text (theme variants, neutral pool, topic templates) + grammar check. |
| `voice_job.py` | Threaded filler+synth job machinery (Streamlit-free, `$0`-testable): the v5 sequencer, reservation-index invariant, watchdog. |
| `voice_stream.py` | `SentenceChunker` + the pluggable `TTS` protocol (`SapiTTS`, `PiperTTS` drop-in) + `speak_stream`. |
| `voice_io.py` | STT/TTS helper layer (reads the `OPENAI_*` config knobs). |
| `app.py`, `cj_chat.py`, `dashboard.py` | **Legacy kiosk surfaces** (`CJ_ALLOW_LEGACY`-guarded); belong to `pre-wake-word-integration`. |

All knobs come from [`../config.py`](../config.py); no module hardcodes a literal
that belongs in a sweep (see the audit for the few live-path exceptions being
cleaned up).

## Configuration

Every knob lives in `../config.py` and is env-overridable (`CJ_*`, plus a few
bare names like `OPENAI_API_KEY`, `STT_BACKEND`, `INFERENCE_MODEL`). The knobs a
demo operator actually flips:

| Var | Default | What |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Claude API key (compose) |
| `OPENAI_API_KEY` | (required) | OpenAI key (STT + TTS on the demo host) |
| `STT_BACKEND` | `openai` | `openai` (whisper-1) or `local` (faster-whisper, offline) |
| `LOCAL_STT_MODEL` | `base` | faster-whisper size when `STT_BACKEND=local` |
| `INFERENCE_MODEL` | `claude-sonnet-4-6` | composer model override |
| `CJ_EMBED_DEVICE` | `cuda` | `cuda` or `cpu` for the resident embedder |

## Sanity-check questions

Verify voice + routing before demo day (run via `service.py --query`):

| Question | Expected |
|---|---|
| "What is the rule of law?" | routes to the rule-of-law topic; answers on twin beacons / 1987 Constitution, cites chunks. |
| "What can you say about the Museum of Liberty and Prosperity?" | routes to the Foundation theme; answers from the FLP docs. |
| "What's your favorite color?" | out-of-domain → graceful in-voice decline, cites nothing. |

## Troubleshooting

- **`OPENAI_API_KEY missing` / `ANTHROPIC_API_KEY missing`** — the demo needs
  both; put them in `app/.env`.
- **Transport = schannel_curl / native TLS broken** — the Avast HTTPS-scanning
  regression; apply the Service-host profile per
  [`../docs/RUNBOOK_transport.md`](../docs/RUNBOOK_transport.md).
- **Segfault (exit 139) on model load** — pyarrow/torch DLL order; keep
  `pyarrow==21.0.0` pinned (see `requirements.txt`).
- **First question slow** — ~30–40s one-time embedder warm on boot; the demo
  warms on launch so question 1 is ready.

---

*Maraming salamat po.*
