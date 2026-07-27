# Supervaise FLP Project — CJ Panganiban Conversation App

A voice conversation app that speaks as retired Philippine Chief Justice
Artemio V. Panganiban, grounded in his published corpus via an embeddings
retrieval pipeline.

**Demo target:** first week of **August 2026** — on a Reachy Mini, **Path B**
(the conversation "brain" runs off-robot; the robot handles mic/speaker/motion).

> ## ⚠️ Two branches, two architectures — check `git branch` first
>
> | Branch | Surface | Retrieval |
> |---|---|---|
> | **`develop`** (this README) | retrieval pipeline + voice demo | **bge-base embeddings + BM25, RRF-fused, 34-topic centroid soft-prior, top-p nucleus cutoff** |
> | `pre-wake-word-integration` | push-to-talk kiosk (`app/app.py`) | no embeddings — Haiku router over a 35-topic taxonomy |
>
> This README describes **`develop`**. The single source of truth for the
> `develop` architecture is
> [`docs/handover_claude_code_2026-07-18.md`](docs/handover_claude_code_2026-07-18.md).
> Older top-level docs that describe a "no vector store / Haiku router" system
> refer to the **kiosk branch** — see that handover to disambiguate.

Current baseline: **arch-baseline-v4.2** (`9ef1f5c`). Retrieval recall (v4 gold,
N=34, retrieval-only): **recall@1 / @5 / @chunks-sent / @10 = 0.588 / 0.882 /
0.941 / 0.971**.

## Pipeline (the `develop` path)

```
[mic]
  ↓ STT — OpenAI whisper-1 (default; STT_BACKEND=local switches to faster-whisper)
User question (text)
  ↓ input_gate + route — LOCAL, ZERO-LLM: embed (bge-base, 768d, GPU) → cosine vs
    34 topic centroids → softmax soft-prior (biases retrieval, never gates)
  ↓ retrieve — dense pilot (827) + BM25 over the SAME docs → RRF (K=60) fuse →
    score = passage_sim + LAMBDA·topic_affinity → top-p NUCLEUS cutoff (floor MIN_K)
Selected chunks (adaptive nucleus, ~median 9)
  ↓ compose — ONE streamed Claude Sonnet 4.6 call (cached Voice-Card system block;
    prose streams first, then a ---ENVELOPE--- sentinel + JSON metadata, never spoken)
Response text (streamed)
  ↓ two-part theme+topic filler (v5) covers compose+TTS latency
  ↓ TTS — OpenAI tts-1, pipelined per-sentence → gapless Web-Audio playback
[speakers]
```

The router is **zero-LLM** (`llm_calls_before_composition = 0`); the streamed
Sonnet compose is the only API round-trip in the pipeline. STT and TTS are
separate OpenAI calls on the demo topology (the robot topology stays local:
Whisper/Piper-class on-device — see [`docs/robot/`](docs/robot/)).

## Quick start

You need **both** `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` (the demo uses OpenAI
STT/TTS). Put them in `app/.env` (gitignored) — see [`app/.env.example`](app/.env.example).

Fastest sanity check (headless, text-only — no audio, no STT/TTS):

```bash
.venv/Scripts/python.exe app/service.py --query "What is the rule of law?"
```

This prints the route, per-stage retrieval timing, the selected chunk_ids, and
the composed answer.

Full voice demo (mic input, streamed compose, gapless spoken playback):

```bash
.venv/Scripts/python.exe -m streamlit run streamlit_voice_demo.py
```

(A ready-made launch config is in [`.claude/launch.json`](.claude/launch.json) as
`voice-demo`.) A second Streamlit surface, `streamlit_voice_smoke.py`, runs the
same pipeline with local Whisper + SAPI TTS.

> **New clone?** The dense/sparse indices and filler clips are gitignored and
> must be rebuilt/regenerated. Follow
> [`docs/RUNBOOK_clean_clone.md`](docs/RUNBOOK_clean_clone.md) — it covers the
> index rebuild, filler-clip regen, the `pyarrow==21.0.0` pin, the Avast
> Service-host profile, and Piper.

> **Legacy entrypoints.** `app/cj_chat.py` and `app/dashboard.py` are the
> **pre-W1.8 kiosk** stack and now exit unless you set `CJ_ALLOW_LEGACY=1`. Do
> not use them on `develop`; the entrypoints above replace them.

## Repo layout

```
.
├── README.md                    ← you are here (develop)
├── config.py                    ← single source of truth for every knob
├── streamlit_voice_demo.py      ← the live voice demo host (OpenAI STT/TTS + filler v5)
├── streamlit_voice_smoke.py     ← alt voice surface (local Whisper + SAPI)
├── app/
│   ├── service.py               ← compose (streamed Sonnet) + envelope + service contract
│   ├── retrieval.py             ← route + hybrid RRF retrieve + nucleus cutoff
│   ├── embeddings.py            ← resident bge-base dense arm
│   ├── sparse.py                ← BM25 sparse arm + atomic-phrase dict
│   ├── filler_route.py          ← v5 two-part theme+topic filler routing/text
│   ├── voice_job.py             ← threaded filler+synth pipeline (Streamlit-free)
│   ├── voice_stream.py          ← SentenceChunker + pluggable TTS protocol (SAPI/Piper)
│   ├── voice_io.py              ← STT/TTS helpers
│   └── app.py, cj_chat.py, dashboard.py   ← legacy kiosk surfaces (CJ_ALLOW_LEGACY-guarded)
├── corpus/                      ← voice card, topic map, corpus md/json, corpus/index/chunks.jsonl
├── data/index/                  ← dense/sparse/centroid artifacts (large ones gitignored)
├── scripts/                     ← build + eval + verification scripts
├── eval/results/                ← eval outputs, provenance, thresholds, audits
└── docs/                        ← handovers, ADRs, lessons, plans, robot (RI-*) docs, runbooks
```

## Cost & performance (measured, for context)

| Stage | Warm number |
|---|---|
| Route (embed + centroid) | ~40 ms |
| Retrieval (RRF + nucleus) | 127 ms p50 |
| Compose TTFT (streamed Sonnet) | ~1.3 s |
| TTS floor (tts-1) | ~3 s |
| STT (OpenAI whisper-1) | ~1.5–2.5 s (the felt-TTFA driver) |
| Demo cost | ~5–6¢ per question (STT + compose + TTS) |

The two-part filler is what makes the felt latency acceptable: a themed opener
fires while compose+TTS run. STT sits before routing, so it is the one latency
the filler cannot hide.

## What's in scope for the August demo

- Voice conversation over the `develop` embeddings pipeline (mic + speakers)
- Full retrieval corpus (1,109 docs / 9,865 chunks; frozen pilot 95 docs / 827 chunks)
- OpenAI STT/TTS on the demo host; one streamed Sonnet call per turn
- Reachy Mini, Path B (brain off-robot)

## What's out of scope (deliberate)

- On-robot (in-process) STT/TTS/embedding — a deploy-topology decision (see RI-301)
- Web/multi-user session management
- Memory beyond the streamed turn

See [`PROJECT.md`](PROJECT.md) for the original Phase-1 corpus-pipeline document
(note: its runtime/retrieval sections predate `develop` — trust the handover for
architecture), and [`docs/handover_claude_code_2026-07-18.md`](docs/handover_claude_code_2026-07-18.md)
for the current engineering picture.

---

*Maraming salamat po.*
