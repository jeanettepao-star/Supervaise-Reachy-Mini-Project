# app/ — MANIFEST

The runnable conversation app. Two entrypoints share one pipeline:
`cj_chat.py` (CLI) for smoke tests and headless voice loop, and
`dashboard.py` (Streamlit) as the primary operator UI. Both consume the
artifacts in `app/artifacts/` and the local Piper/Whisper assets in
`app/voices/` and `app/piper/`.

| ID | File | Description |
|---|---|---|
| 0001 | [README.md](README.md) | App-scoped run instructions — touch when install steps, env vars, or the quick-start commands change. |
| 0002 | [cj_chat.py](cj_chat.py) | CLI entrypoint plus all pipeline functions (STT, router, retrieval, inference, TTS, cache stats). Touch when changing pipeline behavior; the dashboard imports from here. |
| 0003 | [dashboard.py](dashboard.py) | Streamlit chat UI — mic input, text fallback, audio playback, sources expander, cache savings panel. Touch when changing operator UX. |
| 0004 | [requirements.txt](requirements.txt) | Pinned core Python deps (anthropic, python-dotenv, faster-whisper, sounddevice, scipy, numpy, streamlit). Touch when adding a runtime dep. |

## Subdirectories

| ID | Path | Description |
|---|---|---|
| S0001 | [artifacts/](artifacts/) | Corpus artifacts loaded at startup — see [artifacts/MANIFEST.md](artifacts/MANIFEST.md). |
| S0002 | piper/ | Piper TTS Windows binary plus dlls. Gitignored (~38 MB). Install from the Piper release bundle per [README.md](README.md). |
| S0003 | voices/ | Piper ONNX voice model (`en_US-ryan-high`) plus its `.onnx.json` config. Gitignored (~116 MB). Source: HuggingFace `rhasspy/piper-voices`. |
