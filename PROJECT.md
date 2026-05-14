# Project — CJ Panganiban Conversation App

A voice conversation app that speaks as retired Philippine Chief Justice
Artemio V. Panganiban, grounded in his published corpus. Built per
[`corpus/build_kit/README.md`](corpus/build_kit/README.md).

**Demo target:** May 30, 2026 · **Status:** ✅ Working end-to-end

---

## 1. What this is

A conversational interface — not a robot, not a chatbot — that answers
questions in CJ's voice using his own writing as the substrate. The user
speaks a question into a microphone; the app responds with synthesized
audio in CJ's style and a transcript on screen.

**Why this is interesting:** CJ has 25+ years of public writing —
1,000+ Supreme Court decisions, 14 books, hundreds of columns. That's
enough corpus to support a character that doesn't just mimic his voice
but actually reasons from his frameworks: the **twin beacons** (liberty
and prosperity), the **rule of law vs. rule of force** dichotomy, the
**chiastic doublets** (*"justice and jobs, freedom and food, ethics and
economics"*), and his signature openers / closers (*"With due respect,"*
*"Au contraire,"* *"Cheers!"* *"Maraming salamat po."*).

---

## 2. Scope

### In scope (May 30 demo)

- Voice conversation interface (browser-based, mic + speakers)
- Text fallback input for noisy / no-mic environments
- 89-doc corpus (65 columns + 1 book of 19 chapters + 4 appendices)
- 37 canonical topics organized in four tiers (anchor / pillar / vector / personal)
- Local STT/TTS so audio never leaves the demo machine
- Two Claude API calls per turn (router + inference)
- Per-turn ≤ $0.02, 50-turn demo ≤ $0.80

### Out of scope (deliberate, per the build kit)

- ~150 CJ speeches from cjpanganiban.com (Pass B addition)
- Robot embodiment (Reachy Mini wiring)
- Multi-user session management
- Memory beyond the last 10 turns
- Response caching
- Real-time interruption handling
- Authentication

---

## 3. Pipeline architecture

```
[mic in browser]
   │
   ▼
faster-whisper (local STT, "medium" model)
   │ transcript text
   ▼
Claude Haiku 4.5 (router)              ← 1st API call (~$0.001)
   │ {primary_topic, secondary_topics, confidence, reasoning}
   ▼
Retrieval (local artifacts)
   │ topic data + top-3 raw doc extractions for the primary topic
   ▼
Claude Sonnet 4.6 (inference, in CJ's voice)   ← 2nd API call (~$0.015)
   │ response text
   ▼
Piper (local TTS, en_US-ryan-high)
   │ wav with sentence-aware pauses
   ▼
[audio out in browser]
```

**Two Claude calls instead of one** is a deliberate choice. The router
returns just topic IDs from a ~7KB prompt; the inference call then gets a
focused 10-20KB context block (1-3 topic nodes + 2-3 raw doc extractions)
in CJ's voice. The single-call alternative (stuffing all 320KB of
`topic_map.json` into one inference) was rejected: ~$3 per turn, 5-10s
latency, attention dilution.

**Local STT/TTS** is also deliberate:
- Zero per-turn audio cost after one-time model download
- No network round-trip for audio (only the two small JSON Claude calls)
- Audio never leaves the demo machine (privacy)
- If wifi flakes mid-demo, audio still works; only the Claude calls fail

---

## 4. The corpus

89 source documents, ~150K words. Two layers:

### Layer A — Stage 1 per-doc extractions (`corpus/analysis/topics/`)
Each `.json` is a structured extraction from one source document:
title, date, voice register, primary topics, stances, signature phrases,
notable anecdotes, citations. 89 files = `book_01_ch01.json` through
`col_2026_0330.json`.

### Layer B — Stage 3 canonical synthesis (`corpus/analysis/synthesis/`)
Deterministic Python aggregated the per-doc extractions into:

- **`topic_map.json`** — 37 canonical topics (anchor / pillar / vector / personal tiers)
  with display name, definition, doc_ids, stances, signature phrases
- **`topic_graph.json`** — 37 nodes, 78 weighted edges (which topics co-occur)
- **`entity_index.json`** — 69 people + 16 cases + 15 laws, canonicalized
- **`frameworks.json`** — 10 mnemonic frameworks (Four Ins, 3 Es, etc.)
- **`signature_library.json`** — 684 normalized signature phrases
- **`SUMMARY.md`** — human-readable corpus overview

Both layers are loaded by the app at startup; both are part of the
context the inference call receives.

---

## 5. Two interfaces

### Dashboard (`dashboard.py`) — the primary UI

Streamlit chat app with everything in one page:

- 🎤 **mic input** — `st.audio_input` widget; browser records, sends to whisper
- **text fallback** — `st.chat_input` sticky at the bottom
- **conversation history** — last 10 turns scroll up; user bubbles 👤, CJ ⚖️
- **inline audio playback** — Piper-synthesized wav plays under each CJ response (autoplay)
- **Sources expander** — shows the routed topics (primary + secondary as pills),
  confidence (color-coded), router's reasoning, and the top-3 source documents
  the inference saw (title, date, doc_id)
- **sidebar** — toggle Piper TTS on/off, "🧹 Clear conversation" button,
  pipeline summary

Cached via `st.cache_resource` so faster-whisper, the 37-topic artifact set,
and the Anthropic client load once per Streamlit session.

### CLI (`cj_chat.py`) — headless / terminal

The original build-kit reference implementation:

- `python cj_chat.py --text "..."` — text-only smoke test (skips STT/TTS)
- `python cj_chat.py` — full push-to-talk voice loop (press Enter, speak,
  recorder auto-stops on ~1.2s trailing silence)

Useful for debugging, smoke tests, and demoing from a terminal without a browser.

---

## 6. How to run

### Quick smoke test (no audio, fastest path)

```powershell
cd "D:\Reachy Mini Project\App 2\app"
.venv\Scripts\python.exe cj_chat.py --text "What is the rule of law?"
```

Expected: routes to `rule_of_law` (high) with `liberty_and_prosperity` as
secondary; response invokes twin beacons, *Au contraire*, "Cheers!"

### Full demo (chat dashboard with mic)

```powershell
cd "D:\Reachy Mini Project\App 2\app"
.venv\Scripts\streamlit run dashboard.py
```

Opens `http://localhost:8501` in your browser. First time you click 🎤,
Chrome/Edge will ask for mic permission — accept it.

### From-scratch setup on a new machine

```powershell
cd "D:\Reachy Mini Project\App 2\app"

# 1. Python 3.11 venv
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. .env (paste ANTHROPIC_API_KEY)
copy .env.example .env
# edit .env

# 3. Piper TTS binary (Windows)
# Download piper_windows_amd64.zip from
# https://github.com/rhasspy/piper/releases
# and extract into .\piper\

# 4. Voice model — both files into .\voices\
# https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ryan/high
# en_US-ryan-high.onnx
# en_US-ryan-high.onnx.json

# 5. (Optional) Pre-fetch the whisper model
.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8')"
```

---

## 7. Verification — sanity-check questions

From the build kit. Run each and verify the routing + response shape:

| Question | Expected routing | Expected response shape |
|---|---|---|
| "What is the rule of law?" | `rule_of_law` (high) + `liberty_and_prosperity` | Twin beacons, chiastic doublets, 1987 Constitution |
| "Tell me about your mentor." | `mentor_salonga` (high) | 1956 FEU strike, 1960 bar wading, "Maraming salamat po, Dr. Salonga" |
| "What's your favorite color?" | `personal_formation` (low) | Graceful decline + redirect (out-of-corpus reasoning) |
| "Should we have the death penalty?" | `death_penalty` (high) | Echegaray, RA 7659, international treaties, DNA exonerations |
| "Tell me about the Foundation." | `flp_institutional_history` (high) | 2011 founding, scholarships, twin-beacons philosophy |
| "What about West Philippine Sea?" | `west_philippine_sea` (high) | 2016 Arbitral Award, Carpio, "Compañero" |

**All 6 verified passing as of last commit.**

---

## 8. Performance — what we measure

Per-turn latency on a typical CPU laptop (Windows, Python 3.11), warm:

| Stage | Time | Notes |
|---|---|---|
| Browser mic → server upload | <1s | Small wav, local network |
| faster-whisper transcribe | 3-5s | `medium` model, int8 quantized, CPU |
| Router (Haiku 4.5) | ~1.5s | ~7KB system prompt + short user question |
| Inference (Sonnet 4.6) | 7-10s | 10-20KB context, ~120-350 token response |
| Piper TTS | 5-10s | RTF ~1.8 on CPU for a 150-word response |
| **Total per turn (warm)** | **~20-25s** | |

**Cold start:** first turn after launching adds ~12s for whisper model
load. Streamlit caches keep this one-time per session.

**Tuning levers:**
- `WHISPER_MODEL=small` in `.env` → ~3-4× faster transcription, English-only.
- Swap Piper for OpenAI TTS `onyx` → drops total turn to ~12-15s and
  improves voice quality substantially. Single point of change:
  `synthesize_speech()` in `cj_chat.py`.

---

## 9. Cost model

| Item | Per call | Per 50-turn demo |
|---|---|---|
| Router (Haiku 4.5) | ~$0.001 | ~$0.05 |
| Inference (Sonnet 4.6) | ~$0.015 | ~$0.75 |
| STT/TTS | $0 (local) | $0 |
| **Total** | **~$0.016** | **~$0.80** |

At ~200 turns/day of dev/test usage, monthly bill is roughly $90. Negligible.

---

## 10. Repo layout

```
Supervaise-FLP-Project-2/
├── README.md                ← project intro + quick start
├── PROJECT.md               ← this file
├── .gitignore
├── app/                     ← the runnable app
│   ├── README.md            ← detailed run instructions
│   ├── cj_chat.py           ← CLI entrypoint + pipeline functions
│   ├── dashboard.py         ← Streamlit chat UI
│   ├── requirements.txt
│   ├── .env                 ← API key + paths (GITIGNORED)
│   ├── .env.example         ← template
│   ├── artifacts/           ← corpus artifacts loaded at startup (1.4 MB)
│   │   ├── voice_card.md    ← inference system prompt
│   │   ├── router_prompt.md
│   │   ├── topic_map.json
│   │   ├── topic_graph.json
│   │   ├── entity_index.json
│   │   ├── frameworks.json
│   │   ├── signature_library.json
│   │   └── topics/          ← 89 Stage-1 per-doc extractions
│   ├── piper/               ← Piper TTS binary + dlls (GITIGNORED, ~38 MB)
│   ├── voices/              ← ryan-high voice model (GITIGNORED, ~116 MB)
│   ├── state/               ← runtime: TTS wavs (GITIGNORED)
│   └── .venv/               ← Python venv (GITIGNORED, ~464 MB)
├── corpus/                  ← source corpus + pre-processing pipeline
│   ├── build_kit/           ← the original spec, voice card, router prompt, reference impl
│   ├── analysis/
│   │   ├── synthesis/       ← Stage 3 canonical artifacts
│   │   └── topics/          ← Stage 1 per-doc extractions (source of truth)
│   ├── prompts/             ← Stage 1 / Stage 3 prompts (rebuildable)
│   ├── synthesis_scripts/   ← Stage 3 Python (deterministic)
│   └── manifest.json
└── source_materials/        ← original books + columns
    ├── books/
    ├── columns/
    └── manifest.json
```

What gets committed: ~5MB total (corpus + app code + extracted topics).
What stays local: `.env`, `.venv/`, `piper/`, `voices/*.onnx`, `state/`,
generated wavs.

---

## 11. Configuration

`app/.env` (gitignored):

| Var | Default | What |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Claude API key |
| `WHISPER_MODEL` | `medium` | `small` (English-only, faster) or `medium` (Filipino/English code-switch). 769 MB download. |
| `PIPER_BIN` | `./piper/piper.exe` | Path to the Piper executable |
| `PIPER_VOICE` | `./voices/en_US-ryan-high.onnx` | Voice model path |

Model IDs in code (`app/cj_chat.py`):

```python
ROUTER_MODEL    = "claude-haiku-4-5-20251001"
INFERENCE_MODEL = "claude-sonnet-4-6"
```

---

## 12. Tuning knobs

### TTS pause length
`app/cj_chat.py` top of `synthesize_speech`:

```python
TTS_SENTENCE_SILENCE = "0.5"   # seconds between sentences AND after em-dashes
TTS_LENGTH_SCALE     = "1.05"  # >1 = slower; 1.05 = measured judicial tempo
```

- Bump silence to `"0.7"` for more dramatic pauses
- Drop to `"0.3"` for a faster demo tempo
- Bump length scale to `"1.10"` for a slower overall pace

### What triggers a TTS pause

| Punctuation | Pause | Source |
|---|---|---|
| `.` `!` `?` (sentence end) | 0.6s | sentence-per-line input + `--sentence_silence` |
| `—` (em-dash, spaced) | ~150-300ms | **substituted to comma in TTS path**, Piper's native comma pause |
| `–` (en-dash) | ~150-300ms | same — substituted to comma |
| `―` (horizontal bar) | ~150-300ms | same |
| `" -- "` (double hyphen) | ~150-300ms | same |
| `" - "` (spaced hyphen) | ~150-300ms | same |
| `,` (comma) | ~150-300ms | Piper phoneme model (native) — varies with clause position |
| `;` (semicolon) | ~120ms | Piper phoneme model (native) |
| `Yale-trained` (un-spaced hyphen) | none | deliberately preserved as compound word |

**Note on the em-dash → comma substitution:** the *displayed* text in the
dashboard keeps the em-dashes for stylistic clarity. The substitution only
happens on the path that goes to Piper, so what you read and what you hear
are both grammatical in their own register.

### Recording stop-on-silence (CLI only)

`app/cj_chat.py` in `record_until_silence`:

```python
silence_rms_threshold = 350      # RMS below this = silence
min_speech_frames = 5            # ~150ms of speech before we'll consider stopping
trailing_silence_ms = 1200       # stop after this much silence post-speech
```

The dashboard uses the browser's mic widget instead and doesn't use these.

---

## 13. Changelog (recent commits)

- `6788eee` — TTS: also pause 0.5s after em-dashes (and other long-dash variants)
- `7e582d5` — TTS: respect punctuation pauses on commas, dashes, periods, sentence ends
- `b7072ef` — Rebuild dashboard as interactive chat (mic + text input + sources)
- `8311558` — Add Streamlit audience dashboard
- `32c39a0` — Initial commit: CJ Panganiban conversation app

---

## 14. Troubleshooting

| Symptom | Fix |
|---|---|
| **`OverloadedError: Error code: 529`** | Anthropic's servers are temporarily overloaded — not a code or auth problem. The SDK now auto-retries 4× with exponential backoff (~15s window) via `ANTHROPIC_MAX_RETRIES` in `cj_chat.py`. If retries still exhaust, the dashboard shows a friendly red banner and keeps your message in history; the CLI prints a clear message and continues. Just re-submit in a few seconds. |
| **`RateLimitError: Error code: 429`** | You've hit the per-minute rate limit on your Anthropic key. Same retry mechanism applies. Tier-1 keys have lower limits — if you hit it often, request a tier upgrade in the Anthropic console. |
| Router output unparseable | Haiku occasionally adds preamble. Reference impl strips code fences; drop router temp to 0 if persistent. |
| Whisper hallucinates "Thank you" on silence | VAD is on by default. Bump `vad_parameters={"min_silence_duration_ms": 1000}` in `transcribe_audio`. |
| Piper sounds robotic | That's Piper. Swap to OpenAI TTS `onyx` or ElevenLabs — single function (`synthesize_speech`) to change. |
| CJ sounds generic / not like himself | Confirm `voice_card.md` is loaded as `system=` parameter on the inference call. Confirm model is `claude-sonnet-4-6` or better. |
| Routing keeps picking `rule_of_law` | That's the safe fallback. If happening on questions that should route elsewhere, check the router actually receives the topic list (the markdown extraction pulls the first triple-backtick block). |
| Pauses too long / too short | Edit `TTS_SENTENCE_SILENCE` in `app/cj_chat.py`. |
| Dashboard mic re-submits last recording on rerun | Already handled via `mic_counter` key bump. If it recurs, increment the counter manually in the sidebar by clicking "Clear conversation". |
| `ANTHROPIC_API_KEY` not found | `.env` is loaded with `override=True` so an empty shell var won't shadow it. Confirm `.env` exists in `app/` and has the key on the first line. |

---

## 15. Provenance

The corpus artifacts were produced by a documented Stage 1 (per-doc
extraction) + Stage 3 (canonical synthesis) pipeline. The full Stage 1
prompt is at `corpus/prompts/stage_1a_extraction.md`; the Stage 3 scripts
are in `corpus/synthesis_scripts/`. Both are deterministic and
re-runnable.

The corpus itself is CJ Panganiban's publicly published writing: his
*Philippine Daily Inquirer* column "With Due Respect" (2011-2026) and his
2001 book "A Centenary of Justice."

---

*Maraming salamat po.*
