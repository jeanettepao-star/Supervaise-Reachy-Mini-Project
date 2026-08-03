"""Applied at container start, every run (the target file lives inside the
image, so this must re-run each time).

Changes the upstream openWakeWord trainer's DataLoader from
num_workers=n_cpus, prefetch_factor=16 to num_workers=0. The multi-worker
configuration bus-errored at Docker's default shm and is a hang suspect on
WSL2. Idempotent: safe if already applied.
"""
from pathlib import Path

p = Path("/app/openwakeword/openwakeword/train.py")
s = p.read_text()
old = "num_workers=n_cpus, prefetch_factor=16"
new = "num_workers=0"

if old in s:
    p.write_text(s.replace(old, new))
    print("patch-dataloader: applied")
elif new in s:
    print("patch-dataloader: already applied")
else:
    raise SystemExit("patch-dataloader: TARGET NOT FOUND — upstream changed, inspect before training")
