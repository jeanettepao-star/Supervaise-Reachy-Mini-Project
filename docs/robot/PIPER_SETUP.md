# PIPER_SETUP — on-device TTS (R-08 unblocked) — 2026-07-18

- **Model:** `en_US-ryan-medium` (male, 22050 Hz, medium quality) — a dignified male stand-in for CJ.
  Path: `app/voices/piper/en_US-ryan-medium.onnx` (+ `.onnx.json`). **Gitignored** (63 MB); not committed.
- **Download route that WORKS** (R-08 root cause: something injects a bad `Authorization` header →
  HF returns 401 "Invalid username or password" on public files; **clear the header**):
  ```
  curl -sL -H "Authorization:" -o app/voices/piper/en_US-ryan-medium.onnx \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx
  # + same for en_US-ryan-medium.onnx.json
  ```
  (`hf_hub_download` and plain `curl` both 401 without clearing the header. No HF token is set.)
- **Verified $0 local synth:** `pip install piper-tts`; `PiperVoice.load(onnx)` (load ~11 s once) →
  synth **~2006 ms for a 4.1 s sentence on this dev CPU** (`ROBOT-TTFA PREVIEW`). No network — vs
  tts-1's ~3000 ms + network. On the CM4 (ARM, no GPU) it will be slower; measure at RI-701.
- **Voice options for later selection:** Piper has no PH-English voice. Neutral/male en_US options:
  `ryan` (male, used here), `lessac` (neutral), `joe`, `kusal`. A fine-tuned CJ voice is the ideal —
  a delivery-week task. Swap by pointing `TTSBackend` at a different `.onnx` (per RI-301 Path B).
