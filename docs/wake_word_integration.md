# Wake-word integration — "See-Jap" / "Hey Cee-Jap"

Adds a hands-free wake-word front door to the `develop` pipeline. Resolves the
long-flagged wake phrase (`design/w2_7_reachy_seam.md` §f garbled it as **"Seejop"/"CJ"**)
to **"See-Jap"** — a **named config parameter**, never hardcoded.

## Where it sits (seam-aligned)
Wake capture is **upstream of the pipeline** (seam §f): `WAKE detect → record → STT →
query_text`. The pipeline receives only `query_text` and has no wake logic — so this is
robot-portable and does not touch retrieval/compose/TTS. It also **does not change the
push-to-talk Streamlit demo**; the hands-free loop is a separate, opt-in surface.

```
mic → [WAKE window] → wake_word.match ──fires──▶ record query → STT → query_text
                                                                          │
                                            retrieval → compose → TTS ◀────┘  (existing develop pipeline)
```

## Why STT keyword-spotting (not openWakeWord)
A custom phrase needs a **trained model** for openWakeWord/Porcupine — the reverted
PLAN-0008 shipped a hand-trained `hey_cj.onnx`, which is why it was heavy and deferred.
Keyword-spotting over the STT we already run (`voice_io.transcribe`, faster-whisper local)
needs **no trained model** and is trivially re-parameterizable: change `WAKE_PHRASE_VARIANTS`,
done. openWakeWord stays available as a pluggable `WakeDetector` backend for the robot
when a trained "See-Jap" model exists (`WAKE_OWW_MODEL_PATH`).

## Files
| File | Role |
|---|---|
| [app/wake_word.py](../app/wake_word.py) | `WakePhraseMatcher` (pure, tested) · `WakeDetector` (SttKeywordDetector default / OpenWakeWordDetector stub) · `MicAudioSource` (sounddevice, lazy) · `wait_for_wake` / `run_hands_free_loop` |
| [wake_demo.py](../wake_demo.py) | Hands-free entry — wires the wake loop to the develop pipeline (retrieval→compose→TTS) |
| [tests/test_wake_phrase.py](../tests/test_wake_phrase.py) | Matcher + detector-plumbing test (offline, $0) |
| `config.py` §12 | The named parameters (below) |

## The matcher (robustness)
"See-Jap" is out-of-vocabulary; Whisper spells it many ways. The matcher fires on the
whole family — `see jap`, `cee jap`, `see jab`, `cee jay`, `seejap`, `cjap`, `seejop`,
`cj`, `hey cj`, … — and stays silent on near-misses — `see the map`, `see japan`,
`the japanese economy`, `cheese`, `logic jump`. It is **boundary-safe** (token-level,
never a raw substring, so `cj` won't fire inside "logi**cj**ump"): multi-word forms match
an adjacent token run (per-token fuzzy); single-word forms match a whole token.

## Run it
```bash
pip install sounddevice          # mic capture (ffmpeg via imageio-ffmpeg for playback)
CJ_WAKE_WORD_ENABLED=1 python wake_demo.py
# say: "Hey Cee-Jap … what is the rule of law?"
```
Offline matcher demo (no mic/keys): `python app/wake_word.py --selftest`

## Config knobs (config.py §12)
| Knob | Default | Meaning |
|---|---|---|
| `WAKE_PHRASE` | `See-Jap` | the spoken phrase (display/log) |
| `WAKE_PHRASE_VARIANTS` | 24 forms | accepted mishears — the matcher's real driver |
| `WAKE_WORD_ENABLED` | `False` | master switch for the mic loop (opt-in) |
| `WAKE_BACKEND` | `stt_keyword` | `stt_keyword` \| `openwakeword` |
| `WAKE_STT_BACKEND` | `local` | STT for wake windows (faster-whisper; cheap/offline) |
| `WAKE_WINDOW_S` / `WAKE_QUERY_MAX_S` | `1.5` / `6.0` | wake-listen window / query record length |
| `WAKE_WORD_RATIO` / `WAKE_TOKEN_RATIO` | `0.80` / `0.86` | fuzzy thresholds |
| `WAKE_COOLDOWN_S` | `1.0` | debounce after a fire |
| `WAKE_OWW_MODEL_PATH` | `""` | trained model for the openWakeWord backend |

## Verified vs owed
- **Verified (offline, $0)**: `tests/test_wake_phrase.py` — the matcher fires on 24 accept
  cases, rejects 16 near-misses; the detector plumbing works with mocked STT.
- **Owed (needs a live mic — not runnable headless)**: real-voice wake precision/latency in
  the demo room (tune `WAKE_WINDOW_S` / `WAKE_TOKEN_RATIO` against live Whisper output), and
  the openWakeWord robot backend (needs a trained "See-Jap" model).

## Found, not fixed / deferred
- Query capture is a fixed `WAKE_QUERY_MAX_S` window; a VAD **record-until-silence** (the
  reverted `cj_chat.record_until_silence`) is the production upgrade, robot-side per the seam.
- The openWakeWord backend is a documented stub — enable only with a trained model.
