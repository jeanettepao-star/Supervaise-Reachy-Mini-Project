# RUNBOOK — clean clone → talking demo (`develop`)

The shortest correct path from a fresh clone of `develop` to a running voice
demo. Covers the venv, the load-bearing pins, both API keys, the gitignored
artifacts you must regenerate, and the two environment gotchas (pyarrow, Avast).

Source of truth for the architecture: [`handover_claude_code_2026-07-18.md`](handover_claude_code_2026-07-18.md).

---

## 0. What's committed vs what you must regenerate

A fresh clone already has the runtime dense index (`data/index/pilot_dense.npy`),
the 34 topic centroids (`topic_centroids.npy`), the phrase dictionary
(`sparse_phrase_dict.json`), and the chunk store (`corpus/index/chunks.jsonl`).

Gitignored — **you must regenerate these** (reproducible from committed scripts):

| Artifact | Needed for | Regenerate with | Cost |
|---|---|---|---|
| `data/index/pilot_sparse.pkl` | **retrieval (BM25 arm) — REQUIRED** | `scripts/build_sparse_index.py` | ~1 min, $0 |
| `assets/filler_clips/onyx/**` (v5 `.mp3`) | the spoken themed opener | `scripts/gen_v5_theme_clips.py` | ~50+3 `tts-1` calls (small $) |
| `data/index/corpus_dense.npy` | rebuilding centroids / full-corpus tooling **only** (not the demo) | `scripts/build_corpus_dense.py` | GPU ~17 min |
| `app/voices/piper/*.onnx` | local/robot Piper TTS **only** (not the OpenAI demo) | [`robot/PIPER_SETUP.md`](robot/PIPER_SETUP.md) | ~63 MB dl |

The bge-base embedding model auto-downloads from the HF hub on first use (no
token needed — it's a public model).

---

## 1. Python venv + dependencies

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -U pip
.venv/Scripts/python.exe -m pip install -r app/requirements.txt
```

> **Do NOT relax the hard pins in `app/requirements.txt`.** `pyarrow==21.0.0` is
> load-bearing: pyarrow 24's `arrow.dll` access-violates (exit 139) when loaded
> after torch, killing every `sentence_transformers` import. `rank-bm25==0.2.2`
> is pinned so the sparse index rebuilds byte-reproducibly. See the requirements
> comments for the full rationale.

## 2. API keys

The demo uses OpenAI STT/TTS **and** Claude compose, so you need **both** keys.
Copy the template and fill them in:

```bash
cp app/.env.example app/.env
# edit app/.env — set ANTHROPIC_API_KEY and OPENAI_API_KEY
```

`app/.env` is gitignored (never commit it). `app/.env`, `.env`, and cwd `.env`
are all searched, with `app/.env` winning.

## 3. Rebuild the sparse index (REQUIRED)

```bash
.venv/Scripts/python.exe scripts/build_sparse_index.py
```

Produces `data/index/pilot_sparse.pkl`. Retrieval's dense and sparse arms must
cover the same universe, so this is mandatory before the pipeline will answer.

## 4. Regenerate the filler clips (recommended)

```bash
# needs OPENAI_API_KEY (reads app/.env); voice=onyx (the demo default)
.venv/Scripts/python.exe scripts/gen_v5_theme_clips.py
```

Produces the 50 theme + 3 neutral `.mp3` clips under
`assets/filler_clips/onyx/…`. Without them the demo still answers, but the
themed opener falls back to a text spinner (`filler_missing_pool`). The TOPIC
clips (Filler 2) are synthesized on demand at runtime and disk-cached.

## 5. Verify $0 (no API), then run

```bash
# (a) every knob surfaces from one import — no network, no model load
.venv/Scripts/python.exe config.py

# (b) filler-v5 routing/sequencer harness (stubbed compose; $0)
.venv/Scripts/python.exe scripts/verify_filler_v5.py

# (c) headless, one grounded answer end-to-end (needs ANTHROPIC_API_KEY; no audio)
.venv/Scripts/python.exe app/service.py --query "What is the rule of law?"
```

Then launch the voice demo (needs both keys; first launch warms the embedder
~30–40s so question 1 is ready):

```bash
.venv/Scripts/python.exe -m streamlit run streamlit_voice_demo.py
```

(Equivalent to the `voice-demo` config in [`.claude/launch.json`](../.claude/launch.json).)

---

## 6. Environment gotchas (will bite you)

1. **Transport / Avast.** If the demo reports `transport != native_sdk` (or
   compose fails on TLS), Avast's HTTPS scanning is breaking native Python TLS.
   Fix with the **Service-host profile** (HTTPS scanning OFF, all other shields
   ON) — [`RUNBOOK_transport.md`](RUNBOOK_transport.md). The code auto-falls back
   to `schannel_curl` (Windows curl) where native TLS is shadow-aborted; on a
   clean host / the Linux Service host it uses `native_sdk` (streaming).
2. **pyarrow pin** — see §1. Do not upgrade without re-running the bare-import
   probe (`eval/results/postreboot/probe_report.json`).
3. **"HF token" is a red herring.** No code reads `HF_TOKEN`; bge-base is public.
   The one HF gotcha is Piper: something injects a bad `Authorization` header →
   HF returns 401 on public files. Clear the header (`-H "Authorization:"`) per
   [`robot/PIPER_SETUP.md`](robot/PIPER_SETUP.md). Only relevant if you install
   Piper (local/robot TTS); the OpenAI demo doesn't need it.
4. **GPU warm** — the resident bge-base model loads on GPU (cuda_fp32); first
   warm-up is ~30–40s. The demo warms on boot so no visitor pays it.

## 7. Offline / no-spend mode (optional)

Flip STT to the local backend to run without OpenAI STT spend:

```bash
# in app/.env
STT_BACKEND=local        # faster-whisper base/int8/cpu (offline)
```

TTS still uses OpenAI `tts-1` on the demo host; the fully-offline TTS path is
Piper (§0, robot topology).
