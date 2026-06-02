# wake_word_continuous

Streamlit custom component that gives the kiosk **continuous,
hands-free voice operation**:

- listens forever for the wake words **"Hey CJP"** or **"CJP"**
  (openWakeWord pipeline running in the browser),
- captures the visitor's question on every wake fire,
- ends capture after **5 s of continuous silence** (Silero VAD) or
  **20 s safety cap** — whichever comes first,
- ships the 16 kHz mono WAV up to Python as base64,
- suspends wake-word **threshold-cross handling** during pipeline
  processing AND TTS playback, so CJ's own voice never re-triggers
  the kiosk. (Inference still runs to keep buffers warm.)

Drop-in replacement for `st.audio_input` in `app/app.py`. The
downstream pipeline (Whisper → input_gate → router → composer →
fidelity → TTS) is untouched.

**Stack: 100 % open-source, zero per-device licensing.**

| Component | License | Purpose |
|---|---|---|
| [openWakeWord](https://github.com/dscripka/openWakeWord) | Apache-2.0 | melspectrogram + embedding + wake classifier ONNX models |
| [Silero VAD](https://github.com/snakers4/silero-vad) | MIT | 5-second-silence end-pointer |
| [ONNX Runtime Web](https://onnxruntime.ai/docs/tutorials/web/) | MIT | runs all ONNX inference in the browser via WASM |
| Custom `AudioWorklet` | (this repo) | 48 kHz mic → 16 kHz mono Float32 |
| `vite` | MIT | single-file IIFE bundler |

---

## Files

| Path | Purpose |
|---|---|
| `index.html` | Iframe shell + LISTENING-pill CSS. Loaded by Streamlit. |
| `src/wake_word.js` | State machine, 3-stage openWakeWord ONNX pipeline, Silero VAD end-pointer. Bundled into `dist/wake_word.bundle.js`. |
| `src/pcm-worklet.js` | AudioWorkletProcessor: 48 kHz → 16 kHz mono Float32 in 1280-sample (80 ms) chunks. Emitted as a separate asset into `dist/pcm-worklet.js`. |
| `dist/wake_word.bundle.js` | **Built artefact** — committed for runtime hermeticity. |
| `dist/pcm-worklet.js` | **Built artefact** — must live next to the bundle (worklets load by URL). |
| `models/melspectrogram.onnx` | openWakeWord pre-processor (~120 kB). Auto-fetched by `npm run prebuild`. |
| `models/embedding_model.onnx` | openWakeWord embedder (~150 kB). Auto-fetched. |
| `models/wake_word.onnx` | **The trained "Hey CJP" classifier.** Must be produced offline by the operator (see TRAINING.md). Until present the kiosk falls back to push-to-talk. |
| `models/silero_vad.onnx` | Silero v5 VAD (~2 MB). Auto-fetched. |
| `models/ort/*.wasm` | ONNX Runtime Web WASM artefacts. Copied from `node_modules/onnxruntime-web/dist/` by `npm run copy-ort-wasm`. |
| `scripts/fetch-models.js` | Pinned-URL ONNX-model downloader. |
| `package.json` | `onnxruntime-web@1.20.1` + `vite@5.4.10`. No accounts, no keys. |
| `vite.config.js` | IIFE bundle config, worklet emitted as separate asset. |
| `TRAINING.md` | How to produce `models/wake_word.onnx` (the "Hey CJP" classifier) offline via openWakeWord's training pipeline. |

## How to build the bundle

```bash
cd app/components/wake_word_continuous
npm install         # ~25 MB: onnxruntime-web + vite
npm run build       # runs prebuild → fetch-models + copy ORT wasm,
                    # then vite build → dist/wake_word.bundle.js
git add dist/ models/melspectrogram.onnx models/embedding_model.onnx \
        models/silero_vad.onnx models/ort/
```

`npm run build` performs three steps automatically:

1. **`fetch-models`** (prebuild) — downloads
   `melspectrogram.onnx`, `embedding_model.onnx`, `silero_vad.onnx`
   from pinned upstream URLs into `models/`. Skips files already
   present. Does **not** download `wake_word.onnx` — that's the
   project-specific "Hey CJP" classifier; see TRAINING.md.
2. **`copy-ort-wasm`** (prebuild) — copies the ONNX Runtime Web WASM
   binaries from `node_modules/onnxruntime-web/dist/` into
   `models/ort/`. The bundle points at this path at runtime so the
   kiosk runs fully offline.
3. **`vite build`** — bundles `src/wake_word.js` + `onnxruntime-web`
   into `dist/wake_word.bundle.js`, emits `src/pcm-worklet.js`
   alongside as `dist/pcm-worklet.js`.

After this completes (and once `models/wake_word.onnx` is in place),
the component is fully self-contained at runtime.

## Wake-word vocabulary

The trained classifier `models/wake_word.onnx` fires on either of:

- **"Hey CJP"** — primary
- **"CJP"** — secondary (visitors who use only the initials)

The exact-phrase matching is encoded inside the ONNX classifier you
train, NOT in the JS state machine. To add or change phrases,
retrain the classifier (see TRAINING.md).

## Streamlit component contract

### Props (every render)

| Prop | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | `bool` | `True` | Set to False to render an inert placeholder; mic never requested. |
| `silence_ms` | `int` | `5000` | Continuous-silence threshold to end capture (Silero VAD). |
| `max_question_ms` | `int` | `20000` | Hard cap on capture duration. |
| `is_busy` | `bool` | `False` | Python flips True while pipeline runs; wake-word **threshold-cross** events are dropped. |
| `tts_duration_ms` | `int` | `0` | Python sets this just before `st.audio(autoplay=True)`. When > 0 and `is_busy` is False, component enters `SUSPENDED_FOR_PLAYBACK` and arms the resume timer. |

### Return value (via `Streamlit.setComponentValue`)

**Status updates** (sent on every state transition):
```json
{ "__status": "LISTENING_FOR_WAKE", "ts": 1717286400123 }
```

**Capture complete** (sent once after end-pointing):
```json
{
  "audio_b64": "UklGRiQ...",
  "audio_sha256": "9f86d081...",
  "wake_fired_at": 1717286400123,
  "capture_ended_reason": "silence",
  "vad_voice_ratio": 0.62,
  "__status": "SENDING",
  "ts": 1717286405287
}
```

**Special status:** `WAKE_WORD_MODEL_MISSING` is emitted if
`models/wake_word.onnx` failed to load — the operator hasn't trained
the classifier yet. The kiosk's `_preflight()` also surfaces this as
a Streamlit warning.

### State machine

```
IDLE  ─enabled→  INITIALIZING  ─4 ONNX + mic ready→  LISTENING_FOR_WAKE
                                                            │
                                                       wake fires
                                                            ▼
                                                    CAPTURING_QUESTION
                                                            │
                                       Silero 5 s silence  OR  20 s elapsed
                                                            ▼
                                                       SENDING
                                                            │
                                                 audio shipped to Python
                                                            ▼
                                              SUSPENDED_FOR_PROCESSING
                                                            │
                                       Python: is_busy=false + tts_dur>0
                                                            ▼
                                              SUSPENDED_FOR_PLAYBACK
                                                            │
                                                tts_duration + 500 ms
                                                            ▼
                                                  LISTENING_FOR_WAKE
```

### Self-trigger protection

Wake-word **inference runs continuously** so the rolling
mel/embedding buffers stay warm — but in `SUSPENDED_FOR_PROCESSING`
and `SUSPENDED_FOR_PLAYBACK`, the threshold-cross handler short-
circuits before calling `_beginCapture()`. CJ can say "Hey CJP"
inside his own response without the kiosk hearing itself.

### Why this isn't a Python background loop

See `docs/handover_claude_code_2026-05-31.md` §9 known issue 1 (the
silent state-bounce bug, commit `2cf9b88`). Continuous listening
server-side via Streamlit reruns loses audio bytes silently between
renders. The whole point of this component is to keep listening +
buffering in the browser, where the JS event loop runs continuously
and the audio buffer survives Python reruns.
