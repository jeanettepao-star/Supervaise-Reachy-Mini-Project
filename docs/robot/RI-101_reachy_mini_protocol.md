# RI-101 — Reachy Mini protocol / API (reference notes) — 2026-07-18

**$0 doc fetch. Robot arrives NEXT week.** Our own summary of the public Pollen docs (not a copy);
verify against the physical unit + installed SDK version on arrival. Sources at the bottom.

## Two distinct API surfaces
1. **Daemon control API** (movement, state, vision) — REST + WebSocket on **`localhost:8000`**:
   - REST docs: `http://localhost:8000/docs`
   - State: `GET /api/state/full` · WS state stream: `ws://localhost:8000/api/state/ws/full`
   - Python SDK connects to this daemon; e.g. `mini.goto_target(...)`.
2. **Conversation backend** (STT + LLM + TTS) — a **real-time speech-to-speech WebSocket**, NOT a
   plain text LLM endpoint. The `reachy_mini_conversation_app` talks to a **Hugging Face realtime
   backend**:
   - `ws://<host>:8765/v1/realtime` (the `/v1/realtime` name implies OpenAI-Realtime-compatible events)
   - Env: **`HF_REALTIME_CONNECTION_MODE=deployed|local`**, **`HF_REALTIME_WS_URL=ws://<lan-ip>:8765/v1/realtime`**
   - "…using the built-in Hugging Face server **or your own local endpoint**." → the backend can run
     **off-robot** (our Service host / laptop on the LAN, or via SSH tunnel).

## Architectural consequence for OUR pipeline (the key finding)
Our pipeline is a **text-in → streamed-prose-out** LLM slot (retrieval + Sonnet compose). The robot's
conversation app expects a **realtime s2s WS backend**, not a text LLM. Two integration paths:

- **Path A — replace the realtime backend:** implement the `/v1/realtime` WS event protocol and point
  `HF_REALTIME_WS_URL` at our Service. Heaviest (we'd own STT+TTS framing in the realtime protocol);
  our text-only pipeline doesn't natively speak s2s-realtime.
- **Path B — own the loop via `media_backend="no_media"` (recommended):** the SDK lets you **disable
  the built-in media manager** (`media_backend="no_media"`) for **direct hardware access** (their
  example: Whisper + `sounddevice`). We then run our OWN loop — mic → our STT → our text pipeline →
  our TTS → SDK audio-out + motion — bypassing the HF realtime backend entirely. This matches our
  text-in/prose-out seam (design/w2_7_reachy_seam.md) and the DEPLOY-1 topology.

Recommendation: **Path B.** It keeps our v4.2 pipeline unchanged (a text slot) and uses the SDK only
for audio I/O + motion.

## Still to confirm on hardware (see RI-301 for the full MUST-CONFIRM map)
Audio format/sample-rate, barge-in, STT partial-vs-final, who sentence-chunks — the public docs do
**not** specify these; they are hardware/SDK-version confirms.

## Sources
- https://github.com/pollen-robotics/reachy_mini (SDK)
- https://github.com/pollen-robotics/reachy_mini_conversation_app (conversation app)
- https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/integration.md
- https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/platforms/reachy_mini/usage.md
