# CJ Panganiban Conversation App — Build Kit

This kit is the complete starting point for building a conversational app that
speaks as retired Philippine Chief Justice Artemio V. Panganiban, grounded in
his published corpus (65 columns + 1 book of 19 chapters + 4 appendices = 89
documents, ~150K words). The corpus has been pre-processed through Stage 1
(per-doc extraction) and Stage 3 (canonical synthesis).

This README is written for Claude Code (or any developer) to read first.

## What the demo is

A conversation app for the May 30 demo. **Not a robot** — just a desktop/laptop
conversational interface. User asks questions by voice; system responds in CJ's
voice using a local TTS engine.

**Pipeline shape (deliberately simple):**

```
STT (local faster-whisper)
  ↓
Topic Router (Claude Haiku 4.5)
  ↓
Retrieval (load relevant topic_map nodes + raw docs)
  ↓
Inference (Claude Sonnet 4.6 in CJ's voice)
  ↓
TTS (local Piper)
```

Two Claude API calls per user turn. Everything else runs locally.

## Inputs (in this bundle)

```
build_kit/
├── README.md                  ← you are here
├── voice_card.md              ← system prompt for the inference call (CJ's voice)
├── router_prompt.md           ← system prompt for the router call (Haiku)
└── cj_chat.py                 ← reference implementation (Python skeleton)

analysis/synthesis/             ← Stage 3 canonical artifacts (Layer B)
├── topic_map.json             ← 37 canonical topics with all per-topic context
├── topic_graph.json           ← topic relationships (37 nodes, 78 edges)
├── entity_index.json          ← 69 people + 16 cases + 15 laws, canonicalized
├── frameworks.json            ← 10 mnemonic frameworks (Four Ins, 3 Es, etc.)
├── signature_library.json     ← 684 normalized signature phrases
└── SUMMARY.md                 ← human-readable corpus overview

analysis/topics/                ← Stage 1 raw extractions (Layer A)
└── *.json                     ← 89 per-doc extractions, evidence base for inference
```

## How to run it (minimum viable demo)

### 1. Install dependencies

```bash
# Python deps
pip install anthropic faster-whisper sounddevice scipy numpy

# Piper TTS — download from https://github.com/rhasspy/piper/releases
# Pick the binary for your OS, put it on PATH or set PIPER_BIN env var

# Piper voice — recommended formal male voice:
# https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ryan/high
# Download both en_US-ryan-high.onnx and en_US-ryan-high.onnx.json into ./voices/

# faster-whisper model downloads automatically on first run
# 'medium' (769MB) recommended for Filipino-English code-switching
```

### 2. Set up the artifacts directory

Claude Code should organize artifacts like this:

```
your-app/
├── cj_chat.py                  ← from build_kit/
├── artifacts/
│   ├── voice_card.md           ← from build_kit/
│   ├── router_prompt.md        ← from build_kit/
│   ├── topic_map.json          ← from analysis/synthesis/
│   ├── topic_graph.json        ← from analysis/synthesis/
│   ├── entity_index.json       ← from analysis/synthesis/
│   ├── frameworks.json         ← from analysis/synthesis/
│   ├── signature_library.json  ← from analysis/synthesis/
│   └── topics/                 ← from analysis/topics/ (entire directory)
│       ├── book_01_ch01.json
│       ├── ... (89 total)
│       └── col_2026_0330.json
└── voices/
    ├── en_US-ryan-high.onnx
    └── en_US-ryan-high.onnx.json
```

### 3. Configure environment

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export PIPER_BIN="piper"           # or absolute path
export PIPER_VOICE="./voices/en_US-ryan-high.onnx"
export WHISPER_MODEL="medium"      # or "small" for English-only
```

### 4. Test text-only first (no audio, fastest debugging path)

```bash
python cj_chat.py --text "What do you think about the rule of law?"
```

This skips STT/TTS and runs the full router → inference pipeline. You'll see the
routing decision (which topics matched, with what confidence) and the generated
response. Verify the voice sounds right before adding audio I/O.

### 5. Run the voice loop

```bash
python cj_chat.py
```

Press Enter to start each turn. Speak the question. The app records, transcribes,
routes, generates, and speaks the response.

## Architecture choices and why

### Why two Claude calls (router + inference) instead of one?

- **Router** is fast and cheap. Haiku 4.5 returns topic IDs in ~300-500ms for ~$0.001/call. This lets you do focused retrieval before the expensive call.
- **Inference** gets a small, focused context block (1-3 topics + 2-3 raw docs ≈ 10-20K tokens). This is much cheaper and faster than stuffing all 320KB of topic_map.json into one giant context.

Single-call alternative (stuff everything) was rejected: ~$3/turn at 200K tokens, 5-10s latency, attention dilution. Not suitable for conversation.

### Why local STT/TTS instead of API STT/TTS?

- **Cost**: After model download, zero cost per turn. API STT/TTS would add ~$0.02/turn — small but cumulative.
- **Latency**: No network round-trip for audio. Network handles only the two small JSON Claude calls.
- **Privacy**: Audio never leaves the demo machine.
- **Demo reliability**: If wifi flakes mid-demo, audio still works. Only Claude calls fail.

### Why faster-whisper "medium" not "small"?

CJ code-switches into Tagalog constantly: "Maraming salamat po," "Au contraire,"
"Compañero," "Abangan!" If the user code-switches in questions (likely with a
Filipino audience), `small` will mangle Tagalog and your router will route on
garbage transcription. `medium` (769MB) handles it well at ~2x realtime on CPU.

Use `small` only if you control the demo audience to speak pure English.

### Why Piper "ryan-high" voice?

Best naturalness Piper offers for formal American male. Sounds intelligible but
synthesized; will anglicize Tagalog ornaments (Maraming salamat → "Maramayng
salamat"). This is acceptable for a demo — the audience will recognize the
texture as CJ's even if the pronunciation is imperfect.

**If demo quality matters more than cost**, swap Piper for OpenAI TTS `onyx`
(~$0.015/1K chars ≈ $0.50 for the whole demo). Voice quality jump is substantial.
See `cj_chat.py` `synthesize_speech()` — replace the subprocess call to piper
with an OpenAI API call.

## How to test the voice quality

A few sanity-check questions to verify the build is working before demo day:

| Question | Expected behavior |
|---|---|
| "What is the rule of law?" | Routes to rule_of_law (high). Response invokes twin beacons, the 1987 Constitution, structured chiastic doublets. |
| "Tell me about your mentor." | Routes to mentor_salonga (high). Tells the 1956 FEU strike + 1960 bar wading anecdotes. |
| "What's your favorite color?" | Routes with low confidence to personal_formation. Inference gracefully declines: "I have not written on that — let me speak instead to what does interest me..." |
| "Should we have the death penalty?" | Routes to death_penalty (high). Cites Echegaray, RA 7659, international treaties, DNA exonerations. |
| "Tell me about the Foundation." | Routes to flp_institutional_history (high). 2011 founding, scholarships, twin-beacons philosophy. |
| "What about West Philippine Sea?" | Routes to west_philippine_sea (high). 2016 Arbitral Award, Carpio as champion, "Compañero." |

If responses sound generic, check that the voice card is actually loaded as the
system prompt (not as a user message). If routing is wrong, check that the
router model is Haiku not Sonnet (Haiku is more literal, which is what you want
for routing).

## Adding speeches later (Pass B)

Per the original project plan, ~150 CJ speeches from
https://cjpanganiban.com/category/speeches/ will be added in a later pass. The
pipeline supports this without code changes:

1. Run Stage 1a extraction on speech files → produce `speech_XXXX.json` files in `artifacts/topics/`
2. Update `taxonomy.py` to assign new doc_ids to existing topics (add new topics only if speeches surface unfamiliar territory)
3. Re-run `synthesize.py` → regenerates topic_map.json, topic_graph.json, etc.
4. Re-run `make_summary.py` for human review

The conversation app code doesn't change. Just swap in the new artifact files
and restart.

The voice card already anticipates the **acceptance-address** register that
speeches will contribute (papal-award acceptance, eulogies, FLP awards). When
speeches arrive, that register will populate naturally.

## Cost estimate for the demo

A 50-turn demo session:
- Router (Haiku): 50 × $0.001 = $0.05
- Inference (Sonnet 4.6): 50 × ~$0.015 = $0.75
- **Total: ~$0.80 for a full demo**

A month of dev/test usage at ~200 turns/day: roughly $90/month. Negligible.

## Performance targets

| Metric | Target | Bottleneck |
|---|---|---|
| End-to-end turn latency | ≤ 4s | TTS streaming + inference |
| Per-turn cost | ≤ $0.02 | Inference call |
| Router accuracy | ≥ 85% on demo questions | Topic taxonomy clarity |
| Voice authenticity | Identifiable as CJ to Filipino audience | Voice card quality |

## What's _not_ in this build kit (consciously out of scope for the demo)

1. **Speech corpus** — Pass B addition (~150 speeches from cjpanganiban.com)
2. **Multi-turn conversation memory beyond last 10 turns** — the reference impl
   trims to last 10 turns; for production you'd want a memory store
3. **Robot embodiment** — the May 30 demo is conversation-only, no Reachy Mini wiring
4. **User authentication / multi-user session management** — single-user, single-session
5. **Web UI** — the reference impl is CLI; a web UI is straightforward but separate work
6. **Response caching** — could speed up common questions, but small gain at 50-turn scale
7. **Real-time interruption handling** — user can wait for CJ to finish a response

## Troubleshooting

**"Router output unparseable"** — Haiku occasionally adds preamble before the JSON. The reference impl strips code fences but if you see this often, lower router temperature to 0.

**"Whisper transcribes silence as 'Thank you' or other hallucinations"** — VAD is on by default in the reference impl (`vad_filter=True`). If it's still happening, increase `vad_parameters={"min_silence_duration_ms": 1000}`.

**"Piper voice sounds robotic"** — that's Piper. Either accept it or swap to OpenAI TTS `onyx` or ElevenLabs. The `synthesize_speech()` function is a single point of change.

**"CJ sounds generic / not like himself"** — confirm voice_card.md is being loaded as the `system` parameter on the inference call (not as a user message). Confirm the model is `claude-sonnet-4-6` (Sonnet 4.6) or better. Add 1-2 demo questions to the conversation history before the real demo so the voice "warms up."

**"Routing keeps picking rule_of_law"** — that's the safe fallback. If it's happening on questions that should route elsewhere, check that the router actually receives the topic list in its system prompt (the markdown extraction in `cj_chat.py` pulls the first ```...``` block — verify your `router_prompt.md` structure matches).

## Provenance and trust

The artifacts in this kit were produced by a documented Stage 1 + Stage 3
pipeline. The full Stage 1 extraction prompt is at `corpus/prompts/stage_1a_extraction.md`.
The Stage 3 synthesis scripts are in `corpus/synthesis_scripts/`. Both are
deterministic and re-runnable; if you want to verify a topic assignment or
rebuild the canonical layer from scratch, the scripts are self-contained Python.

The corpus itself is CJ Panganiban's publicly published writing: his Inquirer
column "With Due Respect" (2011-2026) and his 2001 book "A Centenary of Justice."

Built: May 2026. Demo target: May 30, 2026.

---

*Maraming salamat po.*
