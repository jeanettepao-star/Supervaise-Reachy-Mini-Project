# Patches already applied to the bundled train.py

The bundled `train.py` is the CoreWorxLab wrapper with three fixes applied.
If you ever need to re-apply them against a FRESH clone (e.g. upstream
updated), here is each one.

## 1. Kokoro voices API shape (crash: 'dict' object has no attribute 'startswith')

Kokoro's /v1/audio/voices now returns `{"voices": [{"id": "af_alloy", ...}, ...]}`
instead of a list of strings.

Replace:
```python
        english = [v for v in voices if v.startswith(('af_', 'am_', 'bf_', 'bm_'))]
```
With:
```python
        # Kokoro now returns [{"id": ..., "name": ...}, ...] rather than
        # plain strings. Accept either shape.
        voices = [v.get("id", v.get("name")) if isinstance(v, dict) else v
                  for v in voices]
        voices = [v for v in voices if v]
        # Drop legacy v0_* duplicates -- same speakers, near-identical audio.
        english = [v for v in voices
                   if v.startswith(('af_', 'am_', 'bf_', 'bm_'))
                   and not v.startswith(('af_v0', 'am_v0', 'bf_v0', 'bm_v0'))]
```

## 2. Config path must be on a mounted volume

`training_config.yaml` was written to /app (container-local, lost on exit),
which broke any attempt to run the underlying trainer separately.

Replace:
```python
    config_path = WORK_DIR / "training_config.yaml"
```
With:
```python
    config_path = Path("/app/my_custom_model") / "training_config.yaml"
```

AND update BOTH subprocess call sites (there are two):
```python
        "--training_config", "training_config.yaml",
```
becomes:
```python
        "--training_config", "/app/my_custom_model/training_config.yaml",
```

## 3. docker-compose.yml: shared memory

PyTorch DataLoader workers bus-error at Docker's default 64 MB /dev/shm.
Under the trainer service add:
```yaml
    shm_size: 8gb
```

## Also note (not a patch, a behavior)

- `--samples-per-voice` below 10 produces ZERO test samples
  (integer division: samples_per_voice // 10) and the trainer crashes with
  StopIteration. Use 10 minimum for smoke tests.
- train.py prints "TRAINING COMPLETE!" unconditionally, even after a crash.
  The only success signal is the .onnx file existing.
- copy_real_samples() copies the SAME real clips into both positive_train and
  positive_test, so reported test metrics are optimistic. Real validation is
  gallery-ambient testing (phase 4), not training metrics.
