# RI-301 — Service Interface Contract (pipeline ↔ robot seam) — 2026-07-18

One-page contract for the seam between the **CJP text pipeline** (v4.2: retrieval + streamed Sonnet
compose) and the **Reachy Mini** robot. Built from RI-101/RI-102 (public docs) + design/w2_7_reachy_seam.md.
Recommended integration = **Path B** (own the loop via `media_backend="no_media"`); the pipeline stays
a pure text-in/text-out slot.

## The seam (inbound / outbound)
```
[robot mic] --audio--> [STT: robot SDK or our Whisper] --final transcript(text)-->
   >>> SERVICE SEAM (our pipeline) <<<
   answer(query_text) -> retrieval.run -> compose_streamed
       ── stream: prose text deltas (ENVELOPE sentinel STRIPPED, never emitted as speech)
       ── side-channel: ENVELOPE json (doc_ids_cited, register) AFTER the sentinel
   <<< SERVICE SEAM >>>
--prose deltas--> [sentence-chunk -> TTS: our Piper/Kokoro] --audio--> [robot speaker + motion]
                  [barge-in: cancel() stops compose + prose mid-turn]
```
- **In:** one call per **final transcript** (text). **Out:** streamed **prose deltas** (speakable) +
  a trailing **ENVELOPE** metadata event (never spoken — triple-locked: chunker stops at sentinel,
  split on sentinel, envelope on a separate field).
- **Control:** `cancel()` for barge-in; `transport` surfaced so a curl/non-streaming host can play a
  thinking-cue instead of streaming.

## MUST-CONFIRM delta — what the Pollen docs settle (RI-101/102)
| # | Item | Status after fetch | Basis |
|---|---|---|---|
| 1 | LLM slot protocol | **PARTIAL** — it's a realtime **WS `/v1/realtime`**, not `/v1/chat` or `/v1/responses`. Path B sidesteps it (we don't use the realtime backend). | conv-app env `HF_REALTIME_WS_URL` |
| 2 | In-process vs external endpoint | **CONFIRMED** — external/local endpoint supported (`HF_REALTIME_CONNECTION_MODE=local`, `HF_REALTIME_WS_URL=ws://<lan-ip>:8765/...`); backend can run off-robot on our Service host. | conv-app docs |
| 3 | Who sentence-chunks | **STILL OPEN** — undocumented. Path B: **we** chunk (our SentenceChunker). | — |
| 4 | Envelope side-channel | **STILL OPEN** — realtime event schema not public. Path B: envelope stays in our process (never crosses to the robot as audio); no side-channel needed. | — |
| 5 | Audio format (rate/PCM/chunk) | **STILL OPEN** — undocumented. **`media_backend="no_media"` lets us own the format** if we drive audio-out. Measure on arrival. | SDK `no_media` |
| 6 | Transport on robot host | **LEANS CONFIRMED** — Linux CM4, local WS/native networking; `schannel_curl` is a Windows-Avast artifact, absent on the robot → native streaming path. | RI-101 |
| 7 | Barge-in / cancel | **STILL OPEN** — undocumented. Seam already exposes `cancel()`; wire to the SDK's interrupt on arrival. | design stub |
| 8 | STT final vs partials | **STILL OPEN** — undocumented. Seam assumes **one call per final transcript**; confirm the SDK/VAD emits finals. | — |

**Settled/advanced by the fetch: #2 (confirmed), #1 & #6 (partial/leans).** Five (#3,#4,#5,#7,#8)
remain hardware/SDK confirms — none block Path B, because Path B keeps STT/TTS/chunking/envelope on
OUR side and uses the SDK only for raw audio I/O + motion.

## Open decisions (flag, not resolved here)
- **Wake word** ("Seejop"/"CJ") — parameterized `wake_phrase`, unconfirmed.
- **On-device vs host embedding** — bge-base on CM4 (ARM, no GPU) is the ≤3s-TTFA risk; MiniLM-or-host
  is the deploy-topology decision (pending Dok). The seam is agnostic (text slot either way).

## Sources
RI-101, RI-102 (this dir) · design/w2_7_reachy_seam.md · pollen-robotics/reachy_mini{,_conversation_app}.
