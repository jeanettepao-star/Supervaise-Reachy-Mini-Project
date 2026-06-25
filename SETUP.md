# SETUP.md — pilot dev environment

Minimal setup to run the **regression check** for the W1.1 baseline. The full
voice demo needs extra audio packages and API keys (noted at the end).

## 1. Python

- **Python 3.12** (validated on 3.12.13, Windows 10). 3.11+ should work
  (the code uses `X | Y` union types and `list[str]` generics).
- Use a project virtualenv (the system Python here is uv-managed and rejects
  global `pip install`):

```bash
python -m venv .venv
# Windows (Git Bash):     ./.venv/Scripts/python.exe -m pip install ...
# Windows (PowerShell):   .\.venv\Scripts\Activate.ps1
# macOS/Linux:            source .venv/bin/activate && pip install ...
```

## 2. Dependencies

```bash
# from repo root, into the venv:
./.venv/Scripts/python.exe -m pip install -r app/requirements.txt
```

`app/requirements.txt` is the canonical list (versions are `>=` floors, not
pinned — the baseline was validated against current releases; re-pin only if a
release breaks it). What it installs and why:

| Need | Packages |
|---|---|
| Claude router/composer/fidelity | `anthropic` |
| Cloud STT/TTS (dashboard voice) | `openai`, `pydub`, `imageio-ffmpeg` |
| `.env` loading | `python-dotenv` |
| Dashboard UI | `streamlit` |
| Recorder + (future) numpy index | `numpy`, `scipy` |

Commented/optional in the same file:
- `faster-whisper`, `sounddevice` — only for the **CLI push-to-talk** voice
  loop (`python app/cj_chat.py` with no `--text`). Imported lazily, so the
  regression check below does **not** need them.
- `sentence-transformers` — only for the **W1.4+ retrieval engine** (MiniLM
  embeddings). Not used by the baseline; left out to keep the install light.

> **Minimal regression-only install:** if you just want the regression check,
> `pip install anthropic python-dotenv` is enough — the offline steps need only
> `anthropic` (a top-level import) and the stdlib.

## 3. MiniLM embedding model (NEW-ARCH — not needed yet)

The locked target architecture (W1.4–W1.7) embeds passages and topic centroids
with **`all-MiniLM-L6-v2`** (384-dim), configured in `config.py`
(`EMBEDDING_MODEL_ID`, `EMBEDDING_DIM`). When that engine lands:

```bash
# pulls torch; downloads the model (~90 MB) to the HF cache on first use
./.venv/Scripts/python.exe -m pip install sentence-transformers
./.venv/Scripts/python.exe -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

The **baseline pipeline and the regression check do not use MiniLM** — skip
this step until the retrieval engine is wired.

## 4. Environment variables

Copy `.env.example` → `.env` (repo root, `app/`, or cwd — all are searched;
`app/.env` wins). Knobs in `config.py` also read these names directly.

| Var | Required for | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | live answers (router + composer + fidelity) | `sk-ant-…`. **Only** thing gating the live regression. |
| `OPENAI_API_KEY` | dashboard cloud STT/TTS (`voice_io.py`) | not needed for the regression |
| `ROUTER_MODEL`, `INFERENCE_MODEL` | optional model overrides | default to Haiku 4.5 / Sonnet 4.6 |
| `CJ_*` (e.g. `CJ_TAU`, `CJ_MAX_TOKENS`) | optional knob overrides | every `config.py` knob; precedence env > file |

## 5. Run the regression check

**Offline** (no API key — confirms imports, config wiring, grounded-context
assembly, and the config-driven topic-map build):

```bash
# (a) every knob surfaces from one import
./.venv/Scripts/python.exe config.py

# (b) pipeline imports, reads config, assembles a grounded context block
./.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'app'); import cj_chat, config; a=cj_chat.CorpusArtifacts(); print(len(a.topics),'topics;', cj_chat._approx_tokens(cj_chat.build_context({'primary_topic':'rule_of_law','secondary_topics':['twin_beacons_doctrine'],'confidence':'high'}, a)),'ctx tokens')"

# (c) existing build still runs (idempotent except its timestamp)
./.venv/Scripts/python.exe scripts/build_topic_map.py
```

**Live** (needs `ANTHROPIC_API_KEY`) — the single command that produces a
grounded answer end-to-end (text mode, no audio):

```bash
./.venv/Scripts/python.exe app/cj_chat.py --text "What is the rule of law?"
```

Without a key this stops cleanly at a `RuntimeError` telling you which `.env`
files were searched — that is the key guard, not a failure of the build.
