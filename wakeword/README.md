# CJAP Wake Word Training — Portable Bundle

Everything needed to train the `hey_cee_jap` openWakeWord model on a new machine.
Target phrase: **"Hey Cee-Jap"** — one two-syllable word, /siː dʒæp/. **NOT spelled
as letters.** Ratified 2026-07-27 by Sir Jacob & Atty. Rae; `config.py` §12
(`WAKE_PHRASE`, `WAKE_PHRASE_VARIANTS`) is the canonical source for the phrase and
its accepted mishears.

> ### ⚠️ Correction — this README used to specify the wrong phrase
>
> Revisions before 2026-08-02 said "spoken as letters: hey see jay ay pee" and
> passed `--wake-word "hey see jay ay pee"` to training. That is the **spelled**
> form, and **decision WW-5 (2026-07-27) retired it**: spoken "C-J" / "see jay"
> must leave the detector SILENT. Training on the spelled string would have
> produced exactly the detector WW-5 forbids, and the app-side matcher
> (`app/wake_word.py`) has a regression test asserting that family stays silent.
>
> The **recordings were always right** — see "About the recordings" below. Only
> the docs and the phrase labels drifted.

## What's in this bundle

**What is actually on disk** (verified 2026-08-02 — the layout below is flat, not
the nested `patches/` + `tools/` tree earlier revisions of this README described):

```
wakeword/
├── README.md                  <- this file
├── train_py_fixes.md          <- the 3 train.py patches, as re-appliable diffs
├── patch-dataloader.py        <- container-side patch, applied at runtime
├── setup-data-fixed.sh        <- fixed data downloader (resumable, size-verified)
├── test_detection.py          <- live detection monitor (phase 0/4 harness)
├── record_samples.py          <- beep-cued recorder (protocol locked)
├── check_clips.py             <- clip QC: truncation/level/duration checks
└── CJAP/
    ├── record_samples.py      <- same recorder, run from here (writes ./data)
    ├── review_clips.py        <- play clips + label what was ACTUALLY said
    ├── build_validation_set.py<- SNR tiering -> data/validation_manifest.json
    ├── check_clips.py  validate.py  record_ambient.py
    └── data/                  <- CANONICAL clip set
        ├── positives/{dev0,elaine,pao}/   20 clips, 16 kHz mono PCM16
        ├── negatives/                      8 clips (all dev0 — see manifest warnings)
        └── validation_manifest.json
```

### ⚠️ Missing from this bundle — you must reconstruct these

`train.py`, `docker-compose.yml`, and `finish-data.sh` are **not here.** Earlier
revisions promised them as "ALREADY PATCHED" files to copy over a fresh clone;
they were never actually placed in the bundle, and there is no copy anywhere in
this repo. Nothing is lost — every change is documented as a re-appliable diff:

- `train.py` — clone upstream, then apply patches **1 and 2** from
  [`train_py_fixes.md`](train_py_fixes.md) by hand.
- `docker-compose.yml` — upstream's, plus patch **3** (`shm_size: 8gb` under the
  `trainer` service).
- `finish-data.sh` — has no surviving source. Only needed if AudioSet/FMA fail
  during step 4; write it then, against whatever the upstream repos look like at
  the time. Do not block on it.

Also read the "Also note (not a patch, a behavior)" section at the end of
`train_py_fixes.md` before the first run — `--samples-per-voice` below 10 crashes
the trainer, and the real clips are copied into BOTH train and test splits, so
reported test metrics are optimistic. Gallery-ambient testing is the real check.

## Machine requirements (learned the hard way)

- **RAM: 16 GB+ for the OS/WSL VM actually available to Linux.** The training
  data includes a 17 GB feature file. It is memory-mapped, but the machine we
  failed on had only 7.7 GB visible to Linux and training hung indefinitely
  with no error. More RAM headroom is the main thing to buy with a new machine.
- **NVIDIA GPU + driver new enough for CUDA 12.6+** (Kokoro TTS container
  requires it; driver 610.x works, 551.x does not).
- **Docker with NVIDIA Container Toolkit.** Verify with:
  `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi`
- **~25 GB free disk** for training data.
- **Prefer native Linux over WSL2.** All our unexplained hangs were on WSL2.
  Native Linux removes that whole suspect class.

## Setup on the new machine

### 1. Clone the repo

```bash
git clone https://github.com/CoreWorxLab/openwakeword-training.git
cd openwakeword-training
```

### 2. Overlay this bundle's fixed files

```bash
B=/path/to/wakeword          # this bundle

cp "$B"/setup-data-fixed.sh .
cp "$B"/patch-dataloader.py .        # flat here, not in patches/
chmod +x setup-data-fixed.sh

# train.py and docker-compose.yml are NOT in the bundle -- patch upstream's by
# hand now, per train_py_fixes.md (patches 1+2 for train.py, 3 for compose).

# Real samples: copy from the canonical clip set, flattened. Do NOT source these
# from CJAP/ at the repo root or wakeword/data/ -- both are pre-curation snapshots
# that still count 8 reclassified clips as positives.
mkdir -p my_real_samples
cp "$B"/CJAP/data/positives/*/*.wav my_real_samples/
ls my_real_samples/*.wav | wc -l     # expect 20
```

### 3. Build

```bash
docker compose build trainer
```

### 4. Download training data (~17 GB)

```bash
docker compose run --rm -v "$(pwd)/setup-data-fixed.sh:/app/setup-data-fixed.sh" \
    trainer ./setup-data-fixed.sh
```

If AudioSet or FMA fail (the upstream repos have churned before):

```bash
docker compose run --rm -v "$(pwd)/finish-data.sh:/app/finish-data.sh" \
    trainer ./finish-data.sh
```

Verify before training — all four must pass:

```bash
stat -c%s data/openwakeword_features_ACAV100M_2000_hrs_16bit.npy  # 17280000128 exactly
ls data/audioset_16k/*.wav | wc -l                                # ~500
ls data/fma/*.wav | wc -l                                          # ~120
ls data/mit_rirs/*.wav | wc -l                                     # 270
```

### 5. Smoke test (15–30 min) — DO THIS BEFORE THE FULL RUN

```bash
docker compose run --rm \
  -v "$(pwd)/train.py:/app/train.py" \
  -v "$(pwd)/patch-dataloader.py:/tmp/patch.py" \
  trainer bash -c '
    python /tmp/patch.py
    python train.py --wake-word "hey cee jap" --data-dir /app/data \
      --samples-per-voice 10 --training-steps 500
  ' 2>&1 | tee smoke-test.log
```

PASS CRITERIA — all five, or stop and investigate:
1. `Kokoro voices available: ~29` (not 0, not an error)
2. `Copied 60 real voice samples (3x weight)` (60 = 20 clips x 3; if it says
   "No real samples found" the mount is broken — training silently proceeds
   synthetic-only, do NOT let it)
3. The `Training:` progress bar ADVANCES past 0/500 within ~10 minutes
4. A `.onnx` file exists in `my_custom_model/` at the end
5. **The synthesized clips actually say "Cee-Jap"** — see the next section.
   This one is new and it is the one that can silently waste an overnight run.

### 5a. Listen to the TTS output before the full run — NEW, DO NOT SKIP

`--wake-word` is not a label. It is the **text handed to Kokoro TTS**, which
generates the tens of thousands of synthetic positives the model actually learns
from; the 20 real clips are a 3x-weighted handful on top. If Kokoro's
grapheme-to-phoneme mangles `cee jap` — says "kay jap", spells it out, or stresses
it oddly — you train a detector for that, and nothing downstream will tell you.
The spelled phrase never had this risk, because letters are what TTS does well.

Play a few of the smoke run's generated positives:

```bash
ls my_custom_model/*positive*/ | head        # exact path varies by trainer version
# then play 3-4 across different voices and confirm they say /siː dʒæp/
```

If the pronunciation is wrong, try these spellings in order and re-smoke-test —
the model filename changes with the string, so keep track of which you used:
`"hey see jap"`, `"hey cee-jap"`, `"hey seejap"`. Whatever wins, record it here.

Note the app-side matcher does NOT depend on this choice — it keyword-spots STT
text against `WAKE_PHRASE_VARIANTS` in `config.py` §12. Only the openWakeWord
backend consumes the trained model.

KNOWN TRAP: train.py prints "TRAINING COMPLETE!" even when training crashed.
Ignore the banner. Only the .onnx file on disk counts.

### 6. Full training run (hours; overnight is fine)

```bash
docker compose run --rm \
  -v "$(pwd)/train.py:/app/train.py" \
  -v "$(pwd)/patch-dataloader.py:/tmp/patch.py" \
  trainer bash -c '
    python /tmp/patch.py
    python train.py --wake-word "hey cee jap" --data-dir /app/data
  ' 2>&1 | tee full-train.log
```

Defaults: 200 samples/voice, 50000 steps, layer size 64.

Output: `my_custom_model/hey_cee_jap.onnx` (the filename is derived from the
`--wake-word` string — if you changed the spelling in step 5a, adjust here too)

### 7. Validate on a machine with a microphone

```bash
pip install openwakeword --no-deps
pip install onnxruntime tqdm scipy scikit-learn requests sounddevice soundfile numpy
python tools/test_detection.py --device <mic-index> \
    --model my_custom_model/hey_cee_jap.onnx --threshold 0.4
```

Say "Hey Cee-Jap" as one word (/siː dʒæp/). Spikes above threshold on the phrase
and a quiet floor during normal talk = success. Start at threshold 0.4 for a fresh
model; tune upward against real ambient audio later.

**Then run the WW-5 rejection check, which is a pass/fail gate, not a nice-to-have:**
say "C-J" ("see jay"), "CJ Panganiban", and "Chief Justice" at the mic. The score
must stay at the floor. If the spelled form triggers it, the model learned the
retired phrase — do not ship it, and check what `--wake-word` string you trained on.

## Fixes already baked into this bundle (do not re-apply)

1. **train.py — Kokoro voices API**: Kokoro now returns `[{"id": ...}, ...]`
   instead of `["af_alloy", ...]`. Patched to accept both, and to drop the
   `*_v0*` legacy duplicate voices.
2. **train.py — config path**: `training_config.yaml` now written to
   `/app/my_custom_model/` (a mounted dir) so it survives container exit.
   Both subprocess call sites updated to match.
3. **docker-compose.yml — shm_size: 8gb**: PyTorch DataLoader workers crash
   with bus errors at Docker's default 64 MB /dev/shm.
4. **patch-dataloader.py** (applied at container start, every run):
   changes `num_workers=n_cpus, prefetch_factor=16` to `num_workers=0` in the
   upstream openwakeword trainer. Applied at runtime because that file lives
   inside the image.
5. **setup-data-fixed.sh**: original skipped a truncated 17 GB download
   because it only checked file existence; this verifies exact byte size and
   resumes. Also guards AudioSet/FMA on directory CONTENT, not existence.
6. **finish-data.sh**: AudioSet moved from tar files to parquet
   (data/bal_train/09.parquet); reads it via pyarrow directly because the
   container's pinned `datasets` library can't parse the new metadata.

## Known unresolved issue on the original machine

On WSL2 with 7.7 GB visible RAM, training hung indefinitely at
`Training: 0%| 0/500` with ~90% CPU, no error, even with all fixes applied
and even when running the upstream trainer directly. Root cause never
isolated (py-spy was blocked inside the container; the wrapper swallows
stderr). Suspects, in order: WSL2-specific generator stall, RAM pressure
from the memmapped 17 GB file's page cache churn. A machine with more RAM
and/or native Linux is the test of both.

If the smoke test hangs the same way on the new machine: stop. Use the
hosted trainer at https://openwakeword.com/train (paid credits, ~minutes)
or rent a GPU hour on RunPod/Vast.ai. Two days was enough.

## Context for whoever picks this up

Wake word for the CJ Panganiban museum kiosk (voice-only Streamlit app,
Anthropic Haiku router + Sonnet composer). Trigger phrase decided against
"Chief Justice"/"Panganiban" deliberately — those saturate gallery ambient
speech and would false-trigger constantly. **"Hey Cee-Jap"** is the published
form; signage should read: Say "Hey Cee-Jap" to begin.

## About the recordings (why the audio survived the doc drift)

Every `meta.json` in `CJAP/data/positives/` used to carry `"phrase": "C-J-A-P"`.
That field was a **label copied from this README's stale default**, not an
observation of what anyone said — `record_samples.py` writes whatever `--phrase`
it was given, and nothing ever checked it against the audio. The clips themselves
were measured on 2026-08-02 and are consistent with "Cee-Jap", not the spelled form:

| Measure | All 20 positives | What it means |
|---|---|---|
| Median speech span | **0.72 s** (clean takes 0.60–1.06 s) | 5 spelled syllables in 0.72 s = 6.9 syll/s, implausibly fast; 2 syllables = 2.8 syll/s, ordinary |
| Envelope bursts per clip | **median 2**, max 3, never 4–5 | "cee-jap" = 2, "hey-cee-jap" = 3; "hey-see-jay-ay-pee" would show 4–5 |
| `"Hey"` in the metadata | absent from every `meta.json` | speakers were cued on the bare word |

Two independent measures agreeing is strong, but neither is a transcript.
**The confirmation step is by ear, and the tool is already written:**

```bash
cd CJAP
python review_clips.py data/positives --device <output-device-index>
```

It plays each clip and records yes/no to `data/clip_labels.json`. Any "no" clips
are not positives for this phrase. Once it passes, note it here and the metadata
`phrase_verified` fields can go from `"pending_listen"` to `"yes"`.

## Known stale copies (delete, don't edit)

Three trees hold the same dev0 session. Only one is current:

- `wakeword/CJAP/data/` — **canonical.** Post-curation: 20 positives across 3
  speakers, 8 negatives, `validation_manifest.json`. This is what to train on.
- `CJAP/` (repo root) — pre-curation snapshot, all 20 dev0 clips still positives.
- `wakeword/data/data/` — unzip artifact of the same snapshot.

The latter two are stale in clip curation as well as phrase, so they were left
untouched rather than half-corrected. Delete them once you have confirmed nothing
else points at them.

After a working model exists, the remaining phases are:
- Phase 2: record ~1 hr of real gallery ambient at the exhibit site
  (evaluation ONLY — never train on it)
- Phase 4: run tools/test_detection.py --duration 3600 --log against that
  ambient; tune threshold; false-accepts-per-hour is the metric that goes
  in front of stakeholders
- Phase 5: wake-word daemon + event bus (do NOT run the audio loop inside
  Streamlit; it reruns top-to-bottom per interaction)
- Confusable phrases ("Chief Justice", "CJ") belong in the EVALUATION set
  only. Never as training negatives — near-miss negatives degrade the model
  (upstream docs and this repo's README both confirm).
