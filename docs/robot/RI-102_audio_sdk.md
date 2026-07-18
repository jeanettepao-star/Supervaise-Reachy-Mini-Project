# RI-102 — Reachy Mini audio subsystem + SDK (reference notes) — 2026-07-18

**$0 doc fetch. Verify on hardware next week.** Our summary of public Pollen docs (not a copy).

## What the public docs establish
- The Python SDK connects to the **daemon on `localhost:8000`** (REST + WS) and covers "move, see,
  **speak, and hear**" plus AI integrations.
- **Custom audio pipelines are explicitly supported:** `media_backend="no_media"` **disables the
  built-in media manager** and gives **direct hardware access** — the docs cite building your own
  pipeline (e.g. Whisper STT via `sounddevice`). This is the hook our Path-B loop uses for mic-in
  and speaker-out.
- The conversation app streams audio over the realtime WS (`:8765/v1/realtime`) for its low-latency
  loop, with speech-reactive motion blended on top.

## What is NOT in the public docs (⚠ hardware/SDK confirms — do not assume)
- **Audio format:** sample rate, bit depth, channels, PCM vs WAV, chunk size for playback/record.
  *(Working assumption from the seam doc: 16-bit PCM WAV, engine-native rate, negotiated at
  `TTSBackend.open()`. UNVERIFIED.)*
- **Mic hardware:** array vs single, VAD, on-device wake — unspecified.
- **Speaker path:** direct buffer playback API name/signature, streaming vs whole-clip.
- **TTS interface on-robot:** whether a built-in TTS exists or we bring our own (Piper/Kokoro).

## Implication for our TTS + streaming work (Part A of this batch)
Our demo's **streamed-PCM TTS path** (`STREAM_TTS_ENABLED`, 24 kHz/16-bit/mono) is the right shape
IF the robot speaker path accepts raw PCM frames — but the robot's actual rate/format is unconfirmed.
On arrival: measure the SDK's audio-out format and re-point `TTSBackend` (Piper/Kokoro local) at it.
The gapless scheduler + first-chunk order guard (R-28) are browser-demo concerns; on-robot the SDK
owns playback ordering.

## Sources
- https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/integration.md
- https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/platforms/reachy_mini/usage.md
- https://github.com/pollen-robotics/reachy_mini (SDK overview, tutorial notebooks: connection/movement/camera/audio)
