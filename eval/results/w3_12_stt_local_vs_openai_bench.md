# STT backend bench — local (faster-whisper) vs OpenAI whisper-1

Harness: eval/results/stt_bench_clips  |  clips: q1_flp.wav, q2_baron.wav, q3_dont_know.wav  
Config: LOCAL=small/int8/cpu · OPENAI=whisper-1

Bench clips are Windows-SAPI stand-ins (scripts/gen_stt_bench_clips.ps1); they are robotic-timbred and may inflate latency on both engines vs natural speech. Re-run on human clips before making a hardware-specific final call.

## Per-clip transcription (ms) and text diff

| clip | ref | local_ms | local_hyp | oai_ms | oai_hyp |
|---|---|---|---|---|---|
| q1_flp.wav | What is the foundation for liberty and prosperity? | **59651** | What is the foundation for liberty and prosperity? | **95050** | What is the foundation for liberty and prosperity? |
| q2_baron.wav | What is baron travel? | **28716** | What is Baron Travel? | **9754** | What is barren travel? |
| q3_dont_know.wav | I don't know. | **27286** | I don't know. | **11083** | I don't know. |

## Summary

- **local (faster-whisper small/int8/cpu)**: first-call 59651ms (cold CT2 load), warm median 28716ms, total edits 0
- **openai (whisper-1 cloud)**: first-call 95050ms, warm median 11083ms, total edits 1

**Warm-median latency winner (Q2+ felt): `openai`.**  Accuracy: local=0 vs openai=1 total word edits (SAPI harness — small sample).

## Config default disposition

Per the task rule ("if local wins, leave STT_BACKEND=local"): the bench outcome above sets config.STT_BACKEND's shipping default. This bench was run on the build laptop (Zen+ APU per CLAUDE.md); the local warm median may drop below OpenAI on a faster CPU (Reachy Mini Pi 5, modern demo host) — re-bench there before the final flip.

## MC#8 preemption (delivery week)

Regardless of the latency winner, STT_BACKEND=local now unblocks the offline-ready path: the demo can transcribe with zero network + zero API spend by flipping one env var, so a Wi-Fi/API outage during delivery week cannot brick the STT stage. Same transcript-confirm contract, filler sequencer untouched.
