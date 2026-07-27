# SETUP.md — pilot dev environment (`develop`)

> **Full clean-clone → talking-demo path lives in
> [`docs/RUNBOOK_clean_clone.md`](docs/RUNBOOK_clean_clone.md).** This page is the
> quick reference for the venv, the hard pins, env vars, and a $0 sanity check on
> the `develop` embeddings pipeline. (For the pre-W1.8 kiosk on
> `pre-wake-word-integration`, see that branch's docs.)

## 1. Python

- **Python 3.11 / 3.12** (validated on 3.12, Windows 10). The code uses `X | Y`
  unions and `list[str]` generics (3.10+).
- Use a project virtualenv:

```bash
python -m venv .venv
# Windows (Git Bash):     ./.venv/Scripts/python.exe -m pip install ...
# Windows (PowerShell):   .\.venv\Scripts\Activate.ps1
# macOS/Linux:            source .venv/bin/activate && pip install ...
```

## 2. Dependencies

```bash
./.venv/Scripts/python.exe -m pip install -r app/requirements.txt
```

`app/requirements.txt` is the canonical list. **It contains hard pins that are
load-bearing — do NOT relax them:**

- **`pyarrow==21.0.0`** — pyarrow 24's `arrow.dll` access-violates (exit 139)
  when loaded after torch 2.5.1, killing every `sentence_transformers` import.
  Streamlit needs `pyarrow<25,>=7`, so removal isn't an option. Do not upgrade
  without re-running the bare-import probe (`eval/results/postreboot/probe_report.json`).
- **`rank-bm25==0.2.2`** — pinned so the gitignored `pilot_sparse.pkl` rebuilds
  byte-reproducibly.

What it installs and why:

| Need | Packages |
|---|---|
| Compose (streamed Sonnet) | `anthropic`, `truststore` |
| Dense arm + centroids | `sentence-transformers` (bge-base), `torch`, `numpy`, `pyarrow` (pinned) |
| Sparse arm (BM25) | `rank-bm25` (pinned) |
| STT/TTS (demo host) | `openai` |
| Local STT (offline path) | `faster-whisper` |
| Voice demo UI | `streamlit` |
| `.env` loading | `python-dotenv` |

`sentence-transformers` is an **active, required** dependency on `develop` (the
dense retrieval arm), not optional.

## 3. Embedding model (auto-downloaded)

The dense arm and the topic centroids use **`BAAI/bge-base-en-v1.5`** (768-dim),
configured in `config.py` (`EMBED_MODEL_ID`, `EMBED_DIM`). It is public and
auto-downloads from the HF hub on first use (no token needed) into the HF cache;
`get_model()` resolves `EMBED_MODEL_PATH` → HF cache snapshot → hub id. To
pre-fetch:

```bash
./.venv/Scripts/python.exe -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"
```

(`all-MiniLM-L6-v2` / 384-dim and OpenAI `text-embedding-3` are W3.4 bakeoff
alternatives only — not the shipping model. Do not install MiniLM expecting the
pipeline to use it.)

## 4. Environment variables

Copy `app/.env.example` → `app/.env` (also searched: repo-root `.env`, cwd
`.env`; `app/.env` wins). `config.py` knobs read these names directly.

| Var | Required for | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | compose (the one pipeline LLM call) | `sk-ant-…` |
| `OPENAI_API_KEY` | STT + TTS on the demo host | **required for the voice demo** (default `STT_BACKEND=openai`) |
| `STT_BACKEND` | `openai` (default) or `local` | `local` = offline faster-whisper (`LOCAL_STT_MODEL=base`) |
| `INFERENCE_MODEL` | composer model override | default `claude-sonnet-4-6` |
| `CJ_*` (e.g. `CJ_RETRIEVAL_TOP_P`, `CJ_EMBED_DEVICE`) | optional knob overrides | every `config.py` knob; precedence env > file |

## 5. Rebuild the gitignored index, then sanity-check

The BM25 index is gitignored and must be rebuilt on a clean clone (see the
runbook for the full list):

```bash
./.venv/Scripts/python.exe scripts/build_sparse_index.py     # -> data/index/pilot_sparse.pkl (~1 min)
```

$0 checks (no API):

```bash
# (a) every knob surfaces from one import — no network, no model load
./.venv/Scripts/python.exe config.py

# (b) filler-v5 routing/sequencer harness (stubbed compose; $0)
./.venv/Scripts/python.exe scripts/verify_filler_v5.py
```

Live check (needs `ANTHROPIC_API_KEY`) — one grounded answer end-to-end, no audio:

```bash
./.venv/Scripts/python.exe app/service.py --query "What is the rule of law?"
```

Without a key this stops cleanly at a `RuntimeError` naming the `.env` files it
searched — that is the key guard, not a build failure.

> **Legacy note.** `app/cj_chat.py` and `app/dashboard.py` are the pre-W1.8 kiosk
> and now exit unless `CJ_ALLOW_LEGACY=1`. The develop entrypoints are
> `app/service.py --query …` (headless) and `streamlit run streamlit_voice_demo.py`
> (voice demo).
