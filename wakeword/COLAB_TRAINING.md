# Training "Hey Cee-Jap" on Google Colab

Local Docker training is blocked on the current machine (verified 2026-08-02):
GPU passthrough fails with `nvidia-container-cli: WSL environment detected but no
adapters were found`, and driver 536.67 is CUDA 12.2 against the CUDA 12.6+ the
Kokoro container needs. Colab supplies a working GPU and skips the whole problem
— including the missing `train.py` / `docker-compose.yml`, which the upstream
notebook does not use.

## There is nothing to upload

The upstream notebook generates **every** training positive synthetically via TTS
(verified against the notebook, 2026-08-02). It has no step for real recordings —
that was a feature of the CoreWorxLab `train.py` wrapper (`copy_real_samples()`,
3x weight), which this route does not use.

So the 34 clips are the **test set**, not training input — exactly what
`CJAP/data/validation_manifest.json` → `purpose` always said. They get used after
training, by `validate.py`. `cjap_training_samples.zip` is still a handy portable
copy, but the Colab run does not want it.

| speaker | clips | |
|---|---|---|
| dev0 | 12 | all ear-confirmed to say "Cee-Jap" |
| pao | 19 | (`phrase_check` in the manifest) |
| elaine | 3 | |

## The notebook

openWakeWord's own training notebook, run on Colab's free GPU:

<https://colab.research.google.com/github/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb>

If that path 404s, open <https://github.com/dscripka/openWakeWord> and use the
Colab badge on the training notebook — upstream moves files occasionally.

**Set the runtime to GPU first**: Runtime → Change runtime type → T4 GPU. The
notebook will run on CPU without complaint and take many hours.

## The only value that matters

```
hey cee jap
```

One two-syllable word, /siː dʒæp/. **Never the spelled letters.** Decision WW-5
(2026-07-27) retires the spelled form: spoken "C-J" / "see jay" must leave the
detector silent. Training on "hey see jay ay pee" produces exactly the detector
WW-5 forbids.

## Check the TTS pronunciation before the long run — DO NOT SKIP

The wake-word string is not a label; it is text handed to a TTS that generates
the tens of thousands of synthetic positives the model actually learns from.
Your 34 real clips are a small weighted addition on top. If the TTS mispronounces
`cee jap` — "kay jap", spells it out, odd stress — you train a detector for that,
and nothing downstream reports it.

The notebook generates samples before training. **Play 3–4 of them** across
different voices and confirm they say /siː dʒæp/. If wrong, try in order:
`hey see jap`, `hey cee-jap`, `hey seejap`. Note which one you used — the output
filename derives from the string.

## After it finishes

Download the `.onnx`, put it somewhere stable, then from `wakeword/CJAP`:

```powershell
python validate.py --model <path-to.onnx> --expect detect
```

That scores it against the stratified manifest — recall by difficulty tier and
by speaker, plus false accepts on the 8 negatives.

**Then the WW-5 rejection gate.** Say "C-J" ("see jay"), "CJ Panganiban", and
"Chief Justice" at the mic:

```powershell
python test_detection.py --model <path-to.onnx> --threshold 0.4 --device <mic>
```

The score must stay at the floor for all three. If the spelled form triggers it,
the model learned the retired phrase — do not ship it, and check what wake-word
string you trained on.

## Known limits of the validation set

All 8 negatives are one speaker, all contain speech, and none are room tone. The
false-accept rate this set reports is not the field rate; resolution floor is 12%.
Real numbers need the Phase 2 gallery-ambient recording (`record_ambient.py`),
which is the outstanding data gap.

## Wiring it into the app (later)

The app runs the `stt_keyword` backend and needs no model. To switch:
`CJ_WAKE_BACKEND=openwakeword` and `CJ_WAKE_OWW_MODEL_PATH=<path>` (config.py §12).
Keep `stt_keyword` as the laptop default — openWakeWord is the robot/always-on path.
