# W2.7 Seam Design — Pipeline ⇄ Reachy Responses-API Runtime

**Status:** DESIGN ONLY (review-ready). No pipeline code changed, no deps added, nothing committed.
**Scope:** the interface/contract by which the retrieval+compose pipeline plugs into the Reachy Mini
speech-to-speech runtime as the "LLM slot." Integration is a later task.

**Grounding (real symbols this references):**
- `app/service.py`: `compose_streamed(query, selected, directives, client=None, on_text=None) -> {answer, envelope, raw, ttft_ms, stop_reason, degraded, usage}`, `answer(query_text, allowlist_version, on_text)`, `build_payload(...)`, `_resolve_transport() -> "native_sdk"|"schannel_curl"`, `_split_envelope`, `config.COMPOSER_ENVELOPE_SENTINEL` (`"---ENVELOPE---"`).
- `app/voice_stream.py`: `SentenceChunker.feed/flush` (stops at the sentinel), TTS shape `synth(text)->(wav_path, synth_ms, audio_s)`, `speak_stream(token_iter, tts)`.
- `app/retrieval.py`: `run(query, allowlist) -> {gate, route, retrieval:{selected, cutoff}, timing, llm_calls_before_composition}`.
- Measured (arch-baseline-v2 + W2.7-TTS): TTFA 2.5s p50 / 3.7s p95 (from compose start); stream-overlap proven; X33 degraded case; transport native_sdk vs schannel_curl.

---

## a. SEAM BOUNDARY — who owns what

```
        ┌─────────────────────────── ROBOT (Reachy Mini, CM4, Linux) ───────────────────────────┐
 mic ─▶ │ WAKE detect ─▶ VAD(Silero) ─▶ STT(Parakeet/Whisper) ─▶ [query_text] ...                │
        │                                                              │                          │
        │   ... [prose sentences] ─▶ TTS(Qwen3/Kokoro) ─▶ audio-out ─▶ speaker   motors/gaze ◀────┤
        └──────────────────────────────────▲──────────────────────────┬──────────────────────────┘
                                  query_text │             prose stream │ (+ envelope side-channel)
        ┌───────────────────────────────────┴──────────────────────────▼──────────────────────────┐
        │ PIPELINE (our side, "LLM slot")                                                           │
        │  retrieval.run(query) ─▶ compose_streamed() [Sonnet, streamed] ─▶ prose deltas + ENVELOPE │
        └───────────────────────────────────────────────────────────────────────────────────────────┘
```

**Pipeline OWNS:** input gate, retrieval (dense+BM25/RRF, soft-prior, top-p nucleus), directives, Sonnet
composition (streamed), the **prose/ENVELOPE split** at the sentinel. Optionally sentence-chunking (see MUST-CONFIRM #3).

**Robot OWNS:** wake-word capture, VAD, STT, TTS synthesis + audio-out, barge-in/turn lifecycle, motors/gaze,
and the audio device. The robot supplies **`query_text`** (final STT transcript) and consumes a **prose stream**.

**The line:** the pipeline is a pure text-in / streamed-text-out **LLM slot**. It never touches audio or motors.
The robot never sees retrieval internals or the ENVELOPE-as-speech. The ENVELOPE is delivered to the robot as
**structured metadata on a side channel**, for logging/telemetry/gaze cues — never as text to speak.

---

## b. STREAMING CONTRACT — prose across the seam; ENVELOPE never spoken

The composer emits, in order: **prose tokens**, then the sentinel `config.COMPOSER_ENVELOPE_SENTINEL`
(`"---ENVELOPE---"`), then a one-line **ENVELOPE JSON**. The seam splits on the sentinel and routes the two
sides to two different channels.

**Event contract (transport-agnostic):** a turn is a stream of `SeamEvent`:
- `ProseDelta{ text }` — a fragment of spoken prose. **Only these feed TTS.**
- `Envelope{ doc_ids_cited, register_used, anecdotes_deployed, signature_phrases_used }` — terminal metadata. **Never spoken.**
- `Done{ stop_reason }` / `Error{ kind, spoken_fallback }`.

**ENVELOPE-NEVER-SPOKEN guarantee (three independent locks):**
1. **Source split:** `compose_streamed` already streams prose via the `on_text` callback and returns the parsed
   `envelope` separately (`_split_envelope`). Prose and envelope are *different return paths*, not one string.
2. **Chunker hard stop:** `voice_stream.SentenceChunker` truncates its buffer at the sentinel and sets `_done`
   — once the sentinel appears, **no further text is ever emitted to TTS**, even if envelope bytes arrive.
3. **Channel separation at the seam:** `ProseDelta` events go to the TTS-facing channel; the `Envelope` event
   goes to the metadata channel. The TTS consumer is *only* subscribed to `ProseDelta`. It is structurally
   impossible for envelope text to reach `synthesize()`.

**Two seam realizations (pick per MUST-CONFIRM #1/#2):**
- **In-process (preferred if the LLM slot runs on-robot in Python):** the robot's TTS stage subscribes to a
  generator of `ProseDelta`; `compose_streamed(on_text=...)` drives it directly. Lowest latency, no serialization.
- **OpenAI-compatible endpoint (if the s2s runtime points its LLM `base_url` at us):** prose streams as
  `chat.completion.chunk` / responses `output_text.delta` events; the ENVELOPE is delivered as a **final
  non-text event** — e.g. a trailing `tool_call`/custom `metadata` field on the `response.done`/`[DONE]` frame,
  or a separate `GET /turn/{id}/envelope`. The delta text channel carries prose only. **MUST-CONFIRM #4** covers
  whether the protocol permits a metadata side-field or requires the separate-GET fallback.

---

## c. TTS PLUG-IN INTERFACE — SAPI now, Piper/Kokoro drop-in

A backend-agnostic `TTSBackend` protocol so the engine swaps without touching the pipeline. Mirrors the current
`voice_stream` shape (`synth(text) -> (wav, synth_ms, audio_s)`) and generalizes for streaming engines.

- **Method surface:** `warmup()`, `synthesize(text_chunk) -> AudioChunk` (blocking, one chunk), and optional
  `synthesize_stream(text_chunk) -> Iterator[AudioChunk]` (for engines that emit sub-sentence audio).
- **Capabilities flag:** `incremental: bool` — SAPI/Piper synthesize per-sentence (`incremental=True` at sentence
  granularity, ~90ms « audio seconds → overlap holds); a hypothetical whole-utterance-only engine sets it False,
  which **loses the streaming win** (flagged, must fall to an incremental engine).
- **Lifecycle:** `open()/close()` (or context manager); `voice` selection; `sample_rate`/format negotiated with
  the robot audio-out (MUST-CONFIRM #5).
- **Drop-in rule:** SAPI (dev stand-in), Piper, Kokoro implement the same `TTSBackend`. The sentence stream and the
  seam are unchanged when swapping — only the concrete backend + its model path change. (Piper package installs on
  Windows but needs a ~60–100MB voice model; on the Linux robot Piper/Kokoro are the targets.)

---

## d. DEGRADATION / ERROR BEHAVIOR — what the robot says/does

| Condition | Detection (pipeline) | Robot behavior |
|---|---|---|
| **Compose timeout** | `COMPOSER_TIMEOUT_S` exceeded → `COMPOSER_MAX_RETRIES` w/ backoff → exhausted | Speak `config.COMPOSER_FALLBACK_MESSAGE` (in-voice: *"With due respect, I am unable to give that the considered answer it deserves just now…"*). `degraded=true`. |
| **Degraded / fallback compose (the X33 case)** | `compose_streamed` returns `degraded=true` (envelope `{}`, `stop_reason="error_fallback"`) | Speak the fallback line; do **not** attempt to synthesize an empty/garbled turn. Log for retry. |
| **Answer present but ENVELOPE empty/uncited** | `answer` non-empty, `envelope.doc_ids_cited == []` (or unparseable) | **Still speak the prose** — it is grounded output; the envelope is metadata, not a speech gate. Emit a `metadata_gap` telemetry flag; never block audio on envelope parse. |
| **Transport = schannel_curl (native TLS broken)** | `_resolve_transport() == "schannel_curl"` | **No incremental streaming** — curl returns the whole answer at once, so TTFA degrades to ≈ full compose time. Robot options: (i) play a short "thinking" cue/filler while it waits; (ii) speak once the blob arrives. Surface `transport` on the seam so the robot can choose. *(Windows-dev-box artifact; the Linux robot should have native TLS — MUST-CONFIRM #6.)* |
| **TTS engine failure** | backend `synthesize()` raises / returns empty | Fall to next engine in the ladder (Piper→SAPI on dev; robot's ladder TBD). If all fail: robot plays a pre-recorded audio fallback + visual/gaze cue; the turn is logged as TTS-failed (pipeline output was fine). |
| **Empty query / identity probe** | `retrieval.run().gate.scope` in `{empty, identity_probe}` | Robot may short-circuit to a canned identity line (design choice, robot-side); pipeline still composes if asked. |

Guiding rule: **audio never blocks on metadata**; **a failed turn degrades to a spoken in-voice line, never a stack trace or silence**.

---

## e. LATENCY BUDGET across the seam (localize a regression to a segment)

User-perceived first audio = STT→query (robot) + retrieve + compose-TTFT + sentence-1 accumulation + TTS-first-chunk + audio-out.
Measured p50 (arch-baseline-v2 + W2.7-TTS real-audio replay) with per-segment budgets:

| Segment | Owner | Measured p50 | Budget (alarm if >) | Source |
|---|---|---|---|---|
| STT → `query_text` | robot | — (robot-owned) | robot SLA | Reachy |
| retrieve (router+retrieval) | pipeline | ~246 ms | 400 ms | v2 (router 165 + retrieval 81) |
| compose TTFT (query→first token) | pipeline | ~1533 ms | 2000 ms | v2 TTFT p50 |
| sentence-1 accumulation (first token→s1 complete) | pipeline | ~800 ms | 1200 ms | W2.7-TTS traces |
| TTS synth first chunk | robot TTS | ~90 ms (SAPI) | 300 ms (Piper/Kokoro) | W2.7-TTS |
| audio-out device | robot | ~50 ms *(ASSUMED)* | 150 ms | ASSUMPTION |
| **first audio (from query)** | — | **~2.7 s** | **≤ 4 s** | derived (matches TTFA 2.5s p50 measured from compose start + retrieve) |

A single segment blowing its budget localizes the regression (e.g. TTFT ↑ → API/model; sentence-1 accumulation ↑
→ token rate / long first sentence; synth ↑ → TTS engine). p95 first-audio ≈ 3.7s + retrieve.

---

## f. WAKE / COMMAND HOOK

Wake + command capture is **entirely robot-side**, upstream of the seam: `WAKE detect → VAD → STT → query_text`.
The pipeline receives only the final `query_text`; it has no wake logic.

**🚩 FLAG — wake word UNCONFIRMED.** The minutes garble it as **"Seejop" / "CJ"**. It is a **named parameter**
(`wake_phrase`, robot-side config), **not hardcoded anywhere**. Do not resolve here. Command grammar (e.g.
"stop", "louder", "repeat") is likewise robot-side and TBD.

---

## MUST CONFIRM against the Reachy SDK (assumptions, unresolved)

1. **LLM slot protocol.** Which does `reachy_mini_conversation_app` actually call — `/v1/responses`,
   `/v1/chat/completions`, or the realtime WS (`ws://127.0.0.1:8765/v1/realtime`) events? *Assumption:* an
   OpenAI-compatible streaming endpoint whose `base_url` we can point at our slot.
2. **In-process vs endpoint.** Can the s2s runtime take an external LLM `base_url`, or must the LLM run
   in-process on the CM4? Decides the in-process vs HTTP seam realization (§b).
3. **Who sentence-chunks.** The robot's s2s TTS stage likely already chunks streamed text. If so, **our
   `SentenceChunker` is redundant on-robot** and the pipeline should emit raw prose deltas + a clean sentinel
   split, letting the robot chunk. *Assumption to confirm:* chunking is robot-side; pipeline owns only the
   prose/ENVELOPE split.
4. **Envelope side-channel.** Does the chosen protocol allow a metadata side-field on the terminal frame
   (tool_call / custom `metadata`), or must the ENVELOPE be a separate request? *Assumption:* a trailing
   non-text event exists; fallback = `GET /turn/{id}/envelope`.
5. **Audio format.** Sample rate / encoding / chunk size the robot TTS→audio-out expects. *Assumption:* 16-bit
   PCM WAV, engine-native rate; negotiated at `TTSBackend.open()`.
6. **Transport on the robot host.** Confirm the Linux CM4 has working native Python TLS → `native_sdk`
   streaming (the `schannel_curl` fallback is a **Windows-dev-box Avast artifact**; it should not exist on the
   robot). If confirmed, the robot always gets the streaming (low-TTFA) path.
7. **Turn lifecycle / barge-in.** Does the robot interrupt TTS when the user speaks again? If so the seam needs
   a **cancel** signal to stop compose+prose mid-turn. *Assumption:* barge-in exists; seam must expose `cancel()`.
8. **STT output contract.** Final-transcript-only, or partials? *Assumption:* the seam is invoked once per final
   transcript.

## OPEN DECISIONS (flag, do NOT resolve here)
- **Wake word** ("Seejop"/"CJ") — unconfirmed; parameterized as `wake_phrase`.
- **On-device vs host embedding** — where bge-large runs (CM4 vs off-board Service host) is undecided (pending
  Dok); the seam is agnostic (pipeline is a text-in/text-out slot regardless), but it affects deployment topology.

## Acceptance mapping
- Seam boundary (§a), streaming contract with ENVELOPE-never-spoken triple-lock (§b), swappable TTS interface
  (§c), degradation table incl. X33 + curl (§d), per-segment latency budget (§e), wake hook flagged (§f).
- Every Reachy-side assumption is in the MUST-CONFIRM list. TTS swap is defined so Piper/Kokoro drop in without
  touching the pipeline. Stub signatures: see `design/w2_7_seam_stubs.py`.
