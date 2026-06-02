# Training the "Hey CJP" wake-word classifier

The browser runtime (`src/wake_word.js`) ships with three of the
four ONNX models it needs (melspectrogram + embedding + Silero VAD,
auto-fetched by `npm run prebuild`). The **wake-word classifier
itself** — `models/wake_word.onnx` — is the project-specific piece
that must be trained offline because "Hey CJP" / "CJP" isn't in
openWakeWord's pretrained zoo.

This document describes the openWakeWord training pipeline. It's
designed to run on a free Colab GPU (T4 / A100) — total ~2-4 hours
of wall-clock time, ~0 cost.

---

## Prerequisites

- Google account (for Colab) OR a local machine with ≥ 16 GB RAM
  and a CUDA GPU.
- ~50 GB of free disk (synthetic training data downloads).

## High-level flow

openWakeWord uses **synthetic training data**: it generates ~10 000
audio clips of someone saying "Hey CJP" / "CJP" via Piper TTS, then
mixes them with background noise + negative speech to train a small
binary classifier. No human voice recordings needed.

```
1. Phrase definition          ──→  ["Hey CJP", "CJP"]
2. Synthetic positives        ──→  10 000 clips via Piper TTS
                                   (many voices, accents, paces)
3. Background negatives       ──→  Open-source speech + noise corpora
                                   downloaded inside the notebook
4. Augmentation               ──→  reverb, noise, pitch shift
5. Train binary classifier    ──→  small CNN on top of the
                                   embedding_model.onnx outputs
6. Export to ONNX             ──→  wake_word.onnx  (~few-hundred kB)
```

The classifier sits ON TOP of `embedding_model.onnx` (which is
already in `models/`), so the trained file is small and the runtime
inference pipeline is the same as for any openWakeWord model.

---

## Step-by-step (Colab)

1. **Open the official training notebook:**
   https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb

2. **In cell `Define Wake Word`, set:**
   ```python
   target_phrase = ["Hey CJP", "CJP"]
   model_name    = "hey_cjp"
   ```

3. **Run all cells.** The notebook will:
   - install openWakeWord + Piper TTS,
   - generate ~10 000 synthetic positives (~30 min on T4),
   - download negative-example datasets (~1 hr, large download),
   - train the classifier (~30-60 min),
   - export `hey_cjp.onnx`.

4. **Download** `hey_cjp.onnx` from the Colab file browser.

5. **Drop it in** as `models/wake_word.onnx` (note: rename):
   ```bash
   cp hey_cjp.onnx app/components/wake_word_continuous/models/wake_word.onnx
   ```

6. **Rebuild the bundle** so the new model is picked up:
   ```bash
   cd app/components/wake_word_continuous
   npm run build
   git add models/wake_word.onnx
   ```

7. **Re-launch Streamlit.** The wake-word component should now boot
   into `LISTENING_FOR_WAKE` and fire on "Hey CJP" / "CJP".

---

## Tuning the threshold

`src/wake_word.js` hard-codes `WAKE_THRESHOLD = 0.5`. Real-world
museum kiosks may need lower (more sensitive — easier to trigger,
more false positives) or higher (more selective — fewer false
positives, requires clearer pronunciation).

Suggested initial pass: keep at 0.5, walk up to the kiosk and try
the trigger five times. If it fires < 4 times, drop to 0.4. If it
fires on random conversation in front of the kiosk, raise to 0.6.

You can also tune the **silence threshold** inside `_stepVad()`
(`VAD_THRESHOLD = 0.5`) — lowering makes the kiosk wait longer for
hesitant speakers, raising makes it cut off sooner.

---

## Local-training alternative

If Colab isn't available, the training pipeline runs locally:

```bash
pip install openwakeword
python -m openwakeword.train \
    --model_name hey_cjp \
    --target_phrase "Hey CJP" "CJP" \
    --n_samples 10000 \
    --output_dir ./trained_models/
```

Recommend a CUDA GPU; CPU training takes 12-24 hours instead of 2-4.

---

## Quality bar

A "good" wake-word model:

- **True-positive rate** ≥ 95 % when the operator says the phrase
  at normal volume from 1 m away.
- **False-positive rate** ≤ 1 trigger per hour of unrelated speech.

If you're materially below either, retrain with more positive
samples (`--n_samples 20000`) or tighter phrasing.

---

## Reachy Mini path

The same `wake_word.onnx` file works in the Python `openwakeword`
package — when the kiosk migrates to the Reachy Mini robot, the
classifier ports over unchanged. Only the browser-side audio
pipeline gets swapped for a Python `sounddevice` + `openwakeword`
pipeline that runs natively on the robot's onboard compute.

This is the entire architectural payoff for picking openWakeWord
over Picovoice: one trained model, two deployment surfaces, zero
licensing recurrence.
