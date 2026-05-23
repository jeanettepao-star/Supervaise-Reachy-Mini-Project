# docs/decisions/ — MANIFEST

Architecture Decision Records in [MADR 4.0](https://adr.github.io/madr/)
format. One file per architecture-shaping decision. Append-only IDs.
When superseding, leave the old ADR in place and link to the new one
from both directions.

| ID | File | Description |
|---|---|---|
| 0001 | [0001-claude-not-openai-for-inference.md](0001-claude-not-openai-for-inference.md) | Choose Claude (Anthropic) as the inference provider rather than OpenAI. |
| 0002 | [0002-llm-tiering-haiku-router-sonnet-inference.md](0002-llm-tiering-haiku-router-sonnet-inference.md) | Tier the LLMs — Haiku 4.5 for routing, Sonnet 4.6 for inference, Opus excluded. |
| 0003 | [0003-reject-embeddings-for-v1.md](0003-reject-embeddings-for-v1.md) | Reject embeddings / vector DB for v1; route via a hand-curated 37-topic taxonomy instead. |
| 0004 | [0004-pattern-1-topic-routed-two-stage-api.md](0004-pattern-1-topic-routed-two-stage-api.md) | Adopt Pattern 1 — topic-routed two-stage API call (router → inference). |
| 0005 | [0005-defer-robot-embodiment-for-may-30.md](0005-defer-robot-embodiment-for-may-30.md) | Defer Reachy Mini embodiment for the May 30 demo; conversation app only. |
| 0006 | [0006-local-stt-faster-whisper.md](0006-local-stt-faster-whisper.md) | Use local `faster-whisper` for speech-to-text rather than a cloud STT API. |
| 0007 | [0007-local-tts-piper-ryan-high.md](0007-local-tts-piper-ryan-high.md) | Use local Piper TTS with the `en_US-ryan-high` voice rather than OpenAI TTS or ElevenLabs. |
| 0008 | [0008-streamlit-dashboard-operator-ui.md](0008-streamlit-dashboard-operator-ui.md) | Use a Streamlit dashboard as the operator UI rather than CLI-only or a custom FastAPI front end. |
| 0009 | [0009-messages-api-not-managed-agent.md](0009-messages-api-not-managed-agent.md) | Use the Messages API rather than a managed agent — the workflow is Q&A, not agentic. |
| 0010 | [0010-anthropic-prompt-caching-voice-card.md](0010-anthropic-prompt-caching-voice-card.md) | Enable Anthropic prompt caching on the voice-card system prompt; actual ~18% savings, not initially-projected 55%. |
