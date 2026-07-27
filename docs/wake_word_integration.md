# Wake-word integration — "Cee-Jap" / "Hey Cee-Jap"

Adds a hands-free wake-word front door to the `develop` pipeline. Resolves the
long-flagged wake phrase (`design/w2_7_reachy_seam.md` §f garbled it as **"Seejop"/"CJ"**)
to **"Cee-Jap"** — a **named config parameter**, never hardcoded.

## Where it sits (seam-aligned)
Wake capture is **upstream of the pipeline** (seam §f): `WAKE detect → record → STT →
query_text`. The pipeline receives only `query_text` and has no wake logic — so this is
robot-portable and does not touch retrieval/compose/TTS. It also **does not change the
push-to-talk Streamlit demo**; the hands-free loop is a separate, opt-in surface.

```
mic → [WAKE window] → wake_word.match ──fires──▶ [turn head toward speaker] → record query → STT → query_text
                                                                                                        │
                                                          retrieval → compose → TTS ◀───────────────────┘
```

## Head orientation — turn toward the speaker (ROBOT-side seam)
On a wake fire, the robot turns its head toward the voice. Motors/gaze are **robot-side**
per the seam, so this is a **parameterized seam** ([app/head_orient.py](../app/head_orient.py)),
opt-in via `HEAD_ORIENT_ENABLED` (default OFF), wired into `run_hands_free_loop`:

```
wake fire → DirectionEstimator.estimate() → level/distance gate → clamp to yaw limit → HeadController.turn_to(yaw)
```

- **Direction & distance are HARD-CODED signal inputs for now** (config §13): a fixed
  azimuth (`HEAD_ORIENT_FIXED_AZIMUTH_DEG`, 0=front / +=right / -=left) and a level
  (`HEAD_ORIENT_FIXED_LEVEL`). The **level/distance gate** (`HEAD_ORIENT_MIN_LEVEL`) means a
  far/quiet voice stays below threshold and the head holds — "heard from a certain distance".
- **Pluggable, robot-portable**: `DirectionEstimator` = `FixedDirectionEstimator` (default) |
  `MicArrayDOAEstimator` (**hardware-week stub** — real GCC-PHAT direction-of-arrival needs the
  robot's mic array). `HeadController` = `LoggingHeadController` (default, prints the target yaw,
  no hardware) | `ReachyMiniHeadController` (**stub** — real Reachy SDK head-turn).
- **The mapping/gate logic is unit-tested offline** (`tests/test_head_orient.py`); the estimated
  azimuth is clamped to `HEAD_ORIENT_YAW_LIMIT_DEG` so a command never over-rotates the neck.
- `orient_to_wake()` is fully guarded — a head-orient failure logs and returns `turned=False`;
  it can never break a voice turn.

**Owed (hardware week):** real mic-array DOA (GCC-PHAT/TDOA over ≥2 channels) to replace the
fixed azimuth, and the real Reachy SDK head-turn to replace the logging stub — neither verifiable
without the robot. Also: `run_hands_free_loop` passes no audio to the estimator yet (the fixed
path ignores it); the DOA path will need the wake window's multi-channel audio retained.

## Why STT keyword-spotting (not openWakeWord)
A custom phrase needs a **trained model** for openWakeWord/Porcupine — the reverted
PLAN-0008 shipped a hand-trained `hey_cj.onnx`, which is why it was heavy and deferred.
Keyword-spotting over the STT we already run (`voice_io.transcribe`, faster-whisper local)
needs **no trained model** and is trivially re-parameterizable: change `WAKE_PHRASE_VARIANTS`,
done. openWakeWord stays available as a pluggable `WakeDetector` backend for the robot
when a trained "Cee-Jap" model exists (`WAKE_OWW_MODEL_PATH`).

## Files
| File | Role |
|---|---|
| [app/wake_word.py](../app/wake_word.py) | `WakePhraseMatcher` (pure, tested) · `WakeDetector` (SttKeywordDetector default / OpenWakeWordDetector stub) · `MicAudioSource` (sounddevice, lazy) · `wait_for_wake` / `run_hands_free_loop` |
| [wake_demo.py](../wake_demo.py) | Hands-free entry — wires the wake loop to the develop pipeline (retrieval→compose→TTS) |
| [app/head_orient.py](../app/head_orient.py) | Head-orientation seam — `DirectionEstimator` (fixed default / mic-array DOA stub) · `HeadController` (logging default / Reachy SDK stub) · `orient_to_wake` (guarded) |
| [tests/test_wake_phrase.py](../tests/test_wake_phrase.py) · [tests/test_head_orient.py](../tests/test_head_orient.py) | Matcher/detector + head-orient logic tests (offline, $0) |
| `config.py` §12 (wake) · §13 (head orientation) | The named parameters |

## The matcher (robustness)
"Cee-Jap" is out-of-vocabulary; Whisper spells it many ways. The matcher fires on the
`-jap` family — `see jap`, `cee jap`, `see jab`, `seejap`, `cjap`, `seejop`, … — and stays
silent on near-misses — `see the map`, `see japan`, `the japanese economy`, `cheese`,
`logic jump` — **and on the legacy `CJ` / `see jay` family, retired per WW-5 (2026-07-27)**
and covered by a rejection regression test. It is **boundary-safe** (token-level, never a
raw substring, so a short token won't fire inside a longer word): multi-word forms match
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
| `WAKE_PHRASE` | `Cee-Jap` | the spoken phrase (display/log) |
| `WAKE_PHRASE_VARIANTS` | 15 forms | accepted `-jap` mishears — the matcher's real driver (legacy CJ/Jay pruned, WW-5) |
| `WAKE_WORD_ENABLED` | `False` | master switch for the mic loop (opt-in) |
| `WAKE_BACKEND` | `stt_keyword` | `stt_keyword` \| `openwakeword` |
| `WAKE_STT_BACKEND` | `local` | STT for wake windows (faster-whisper; cheap/offline) |
| `WAKE_WINDOW_S` / `WAKE_QUERY_MAX_S` | `1.5` / `6.0` | wake-listen window / query record length |
| `WAKE_WORD_RATIO` / `WAKE_TOKEN_RATIO` | `0.80` / `0.86` | fuzzy thresholds |
| `WAKE_COOLDOWN_S` | `1.0` | debounce after a fire |
| `WAKE_OWW_MODEL_PATH` | `""` | trained model for the openWakeWord backend |

## Verified vs owed
- **Verified (offline, $0)**: `tests/test_wake_phrase.py` — the matcher fires on the Cee-Jap
  accept set, rejects the near-misses **and the retired legacy CJ/Jay family** (regression
  test); the detector plumbing works with mocked STT.
- **Owed (needs a live mic — not runnable headless)**: real-voice wake precision/latency in
  the demo room (tune `WAKE_WINDOW_S` / `WAKE_TOKEN_RATIO` against live Whisper output), and
  the openWakeWord robot backend (needs a trained "Cee-Jap" model).

## Found, not fixed / deferred
- Query capture is a fixed `WAKE_QUERY_MAX_S` window; a VAD **record-until-silence** (the
  reverted `cj_chat.record_until_silence`) is the production upgrade, robot-side per the seam.
- The openWakeWord backend is a documented stub — enable only with a trained model.
