# Colab training — `hey_cee_jap`

Trains the openWakeWord model for **"Hey, Cee Jap"** and exports
`hey_cee_jap.onnx` for `config.WAKE_OWW_MODEL_PATH`.

| File | What it is |
|---|---|
| `train_hey_cee_jap.ipynb` | The notebook. Upload to [colab.research.google.com](https://colab.research.google.com) and run top to bottom. |
| `cjap_clips.zip` | The 34 held-out positives + 8 WW-5 negatives + `validation_manifest.json`. Upload when the notebook asks (Step 3). |

## Run it

1. Open the notebook in Colab → **Runtime → Change runtime type → GPU**.
2. Run cells in order. Step 3 prompts for `cjap_clips.zip`.
3. **Leave `QUICK_SMOKE = True` for the first pass** (~15 min). It proves the whole
   chain end to end and produces a deliberately weak model. Only then set it to
   `False` and do the real run (a few hours).
4. Step 9 prints a threshold table; Step 10 downloads the model bundle.

## Why openWakeWord

It is what the app already expects — [`app/wake_word.py`](../../../app/wake_word.py)
has an `OpenWakeWordDetector` backend wired to `config.WAKE_OWW_MODEL_PATH`, and
`validate.py` / `test_detection.py` both load `.onnx`.

It is also the right architecture for this job: a ~100 KB classifier head on
Google's frozen `speech_embedding` extractor. It trains in hours instead of days,
runs always-on at low CPU, and `auto_train` optimises directly against
**false-accepts-per-hour** — the number stakeholders actually care about.
Fine-tuning Whisper or Wav2Vec2 would be hundreds of MB with ~1 s latency, which
is fine for transcription and unusable as an always-on trigger.

## What the real recordings are for

**Validation only — they are never trained on.** Training positives are tens of
thousands of synthetic Piper-TTS utterances with room-impulse and background-noise
augmentation. 34 clips from 3 speakers would be swamped in that, but they are the
only *real* evidence the model works, so they are held out and scored per SNR tier
and per speaker at the end.

The 8 negatives are the spelled-letter "see jay ay pee" takes. **WW-5 (2026-07-27)
requires that family to stay silent** — Step 9 fails loudly if any of them fire.

## Phrase decision

Confirmed by `data/clip_labels.json`: all 34 positives say **"Cee-Jap" as one word**
(`/siː dʒæp/`), all 8 negatives spell the letters out. This matches
`config.WAKE_PHRASE = "Cee-Jap"`, with `hey` stripped as a carrier word at
[`app/wake_word.py:51`](../../../app/wake_word.py#L51).

The notebook trains on `hey cee jap` **and** bare `cee jap`, so it fires either
way. Dropping the bare spellings from `TARGET_PHRASES` gives a stricter, lower
false-accept model that requires the carrier — the tradeoff is called out in the
Step 4 cell.

> ⚠️ The bundle-level [`wakeword/README.md`](../../README.md) still describes the
> **pre-WW-5** target ("Hey C-J-A-P" spoken as letters, `--wake-word "hey see jay
> ay pee"`). That document is stale and now contradicts the app; training from it
> would build exactly the detector WW-5 retired.

## Known gotchas, in the order you will hit them

1. **Dependency install can knock out CUDA torch.** The cell after the install
   re-checks it. If it fails: **Runtime → Restart session**, re-run from Step 0.
2. **The 17 GB negative-features download is the long pole.** It is memory-mapped
   during training, so RAM is not the constraint — disk is. Step 6 verifies the
   exact byte size, because a truncated download does not error, it just trains a
   quietly worse model.
3. **The training cell ends with an `onnx_tf` / `tensorflow` error. This is
   expected and harmless.** It is `convert_onnx_to_tflite()` running *after* the
   ONNX file is already written. This project needs the `.onnx`; the tflite
   conversion is not worth installing a conflicting TF stack for. The assert cell
   right after confirms the model exists.
4. **Upstream URLs churn.** This repo already lived through AudioSet moving from
   tar to parquet. Every remote reference sits in one cell in Step 5 so there is a
   single place to fix, and Step 6 verifies what actually landed.
5. **`num_workers` hang.** openWakeWord builds its DataLoader with
   `num_workers=n_cpus, prefetch_factor=16`, which on a small `/dev/shm` hangs at
   `Training: 0%` with no error — the failure that cost this project two days on
   WSL2. Step 7 patches it to `num_workers=0`.

## After training

```bash
cd "wakeword/CJAP"
./.venv/Scripts/python.exe validate.py --model models/hey_cee_jap.onnx --threshold 0.5
./.venv/Scripts/python.exe test_detection.py --model models/hey_cee_jap.onnx --device <mic> --threshold 0.5
```

Two things a trained model does **not** finish:

- **`OpenWakeWordDetector.detect()` is still a stub** that raises
  `NotImplementedError`. Setting `CJ_WAKE_BACKEND=openwakeword` will crash until
  it is implemented. A model is necessary but not sufficient.
- **False-accepts-per-hour is still unmeasured.** 8 negative clips cannot resolve
  below 12%; a usable target is far lower. That number only comes from Phase 2 —
  an hour of real gallery ambient replayed through
  `test_detection.py --duration 3600 --log`. Note those flags exist only in the
  *outer* `wakeword/test_detection.py`, not the regressed copy in `CJAP/`.
