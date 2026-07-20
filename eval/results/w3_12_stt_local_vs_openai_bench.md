# STT backend bench — local (faster-whisper) vs OpenAI whisper-1

Harness: eval/results/stt_bench_clips  |  clips: q1_flp.wav, q2_baron.wav, q3_dont_know.wav  
Config: LOCAL sizes benched = local_small, local_base (int8/cpu) · OPENAI=whisper-1

Bench clips are Windows-SAPI stand-ins (scripts/gen_stt_bench_clips.ps1); robotic-timbred, so latency numbers here are conservative vs natural speech.

## Per-clip transcription (ms) and text diff

| clip | ref | local_small_ms | local_small_hyp | local_base_ms | local_base_hyp | openai_ms | openai_hyp |
|---|---|---|---|---|---|---|---|
| q1_flp.wav | What is the foundation for liberty and prosperity? | **83928** | What is the foundation for liberty and prosperity? | **9659** | What is the foundation for liberty and prosperity? | **14597** | What is the foundation for liberty and prosperity? |
| q2_baron.wav | What is baron travel? | **28917** | What is Baron Travel? | **7681** | What is Baron Travel? | **1633** | What is barren travel? |
| q3_dont_know.wav | I don't know. | **27153** | I don't know. | **7471** | I don't know. | **3047** | I don't know. |

## Summary

- **local_small**: first-call 83928ms, warm median 28917ms, total edits 0
- **local_base**: first-call 9659ms, warm median 7681ms, total edits 0
- **openai**: first-call 14597ms, warm median 3047ms, total edits 1

**Warm-median latency winner (Q2+ felt): `openai` @ 3047ms**
**Accuracy winner (fewest edits): `local_small` @ 0 edits**

## Config default disposition

Per the task rule ("if local wins, leave STT_BACKEND=local"):
latency winner = `openai`. If a local size beats
openai's warm median without a WER regression, flip config.STT_BACKEND
to `local` and set LOCAL_STT_MODEL to that size.

## MC#8 preemption (delivery week)

Regardless of the latency winner, `STT_BACKEND=local` unblocks the
offline-ready path: transcribe with zero network + zero API spend via
one env flip, so a Wi-Fi/API outage during delivery week cannot brick
the STT stage. Same transcript-confirm contract; filler untouched.
