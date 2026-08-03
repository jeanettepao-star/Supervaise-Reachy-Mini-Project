#!/bin/bash
# Corrected data setup.
#
# Fixes three bugs in the original:
#   1. ACAV100M was guarded by file EXISTENCE, so a truncated download was
#      skipped forever. Now verified by exact byte size, and resumable.
#   2. AudioSet created audioset_16k/ BEFORE downloading, so the -d guard
#      skipped it permanently after the first failure.
#   3. AudioSet's bal_train09.tar no longer exists; the repo was converted
#      to parquet. Now streams data/bal_train/09.parquet instead.

set -e

export DATA_DIR="${DATA_DIR:-./data}"
mkdir -p "$DATA_DIR"

ACAV="$DATA_DIR/openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
ACAV_URL='https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/openwakeword_features_ACAV100M_2000_hrs_16bit.npy'
ACAV_BYTES=17280000128

VAL="$DATA_DIR/validation_set_features.npy"
VAL_URL='https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/validation_set_features.npy'

echo "=== Downloading training data to $DATA_DIR ==="
echo ""

fetch_resumable() {
    local path="$1" url="$2" want="$3" label="$4"
    local have
    have=$(stat -c%s "$path" 2>/dev/null || echo 0)

    if [ "$have" -eq "$want" ]; then
        echo "$label complete ($have bytes), skipping."
        return 0
    fi

    echo "$label incomplete: $have / $want bytes. Resuming..."
    for attempt in $(seq 1 20); do
        if curl -L -C - --retry 5 --retry-delay 10 --retry-all-errors \
                --connect-timeout 30 -o "$path" "$url"; then
            :
        else
            echo "  attempt $attempt interrupted"
        fi
        have=$(stat -c%s "$path" 2>/dev/null || echo 0)
        if [ "$have" -eq "$want" ]; then
            echo "$label complete."
            return 0
        fi
        echo "  have $have / $want, retrying in 15s (attempt $attempt/20)"
        sleep 15
    done

    echo "ERROR: $label still incomplete after 20 attempts ($have / $want)."
    return 1
}

fetch_resumable "$ACAV" "$ACAV_URL" "$ACAV_BYTES" "ACAV100M features"

# Validation features: size unknown up front, so probe it.
VAL_BYTES=$(curl -sIL "$VAL_URL" | awk 'tolower($1)=="content-length:"{v=$2} END{gsub(/\r/,"",v); print v}')
if [ -n "$VAL_BYTES" ]; then
    fetch_resumable "$VAL" "$VAL_URL" "$VAL_BYTES" "Validation features"
elif [ ! -f "$VAL" ]; then
    echo "Downloading validation features..."
    curl -L --retry 5 -o "$VAL" "$VAL_URL"
fi

# MIT Room Impulse Responses
if [ -z "$(ls -A "$DATA_DIR/mit_rirs" 2>/dev/null)" ]; then
    echo "Downloading room impulse responses..."
    git lfs install
    git clone https://huggingface.co/datasets/davidscripka/MIT_environmental_impulse_responses \
        "$DATA_DIR/MIT_environmental_impulse_responses_tmp"
    mkdir -p "$DATA_DIR/mit_rirs"
    python3 << 'PYEOF'
import os, datasets, scipy.io.wavfile, numpy as np
from pathlib import Path
from tqdm import tqdm
d = os.environ["DATA_DIR"]
ds = datasets.Dataset.from_dict({
    "audio": [str(i) for i in Path(f"{d}/MIT_environmental_impulse_responses_tmp/16khz").glob("*.wav")]
}).cast_column("audio", datasets.Audio())
for row in tqdm(ds, desc="Processing RIRs"):
    name = os.path.basename(row["audio"]["path"])
    scipy.io.wavfile.write(f"{d}/mit_rirs/{name}", 16000,
                           (row["audio"]["array"] * 32767).astype(np.int16))
PYEOF
    rm -rf "$DATA_DIR/MIT_environmental_impulse_responses_tmp"
else
    echo "MIT RIRs already exist, skipping."
fi

# AudioSet background audio -- guard on CONTENT, not directory existence.
if [ -z "$(ls -A "$DATA_DIR/audioset_16k" 2>/dev/null)" ]; then
    echo "Downloading AudioSet background audio (streaming parquet)..."
    mkdir -p "$DATA_DIR/audioset_16k"
    python3 << 'PYEOF'
import os, datasets, scipy.io.wavfile, numpy as np
from tqdm import tqdm
d = os.environ["DATA_DIR"]
URL = ("https://huggingface.co/datasets/agkphysics/AudioSet/resolve/main/"
       "data/bal_train/09.parquet")
ds = datasets.load_dataset("parquet", data_files=URL, split="train", streaming=True)
ds = ds.cast_column("audio", datasets.Audio(sampling_rate=16000))
TARGET = 500
n = 0
for row in tqdm(ds, total=TARGET, desc="Processing AudioSet"):
    if n >= TARGET:
        break
    name = os.path.basename(row["audio"]["path"]).replace(".flac", ".wav")
    scipy.io.wavfile.write(f"{d}/audioset_16k/{name}", 16000,
                           (row["audio"]["array"] * 32767).astype(np.int16))
    n += 1
print(f"wrote {n} background clips")
PYEOF
else
    echo "AudioSet already exists, skipping."
fi

# FMA music samples
if [ -z "$(ls -A "$DATA_DIR/fma" 2>/dev/null)" ]; then
    echo "Downloading FMA music samples..."
    mkdir -p "$DATA_DIR/fma"
    python3 << 'PYEOF'
import os, datasets, scipy.io.wavfile, numpy as np
from tqdm import tqdm
d = os.environ["DATA_DIR"]
fma = datasets.load_dataset("rudraml/fma", name="small", split="train", streaming=True)
fma = iter(fma.cast_column("audio", datasets.Audio(sampling_rate=16000)))
for _ in tqdm(range(120), desc="Processing FMA"):
    try:
        row = next(fma)
    except StopIteration:
        break
    name = os.path.basename(row["audio"]["path"]).replace(".mp3", ".wav")
    scipy.io.wavfile.write(f"{d}/fma/{name}", 16000,
                           (row["audio"]["array"] * 32767).astype(np.int16))
PYEOF
else
    echo "FMA already exists, skipping."
fi

echo ""
echo "=== Data download complete! ==="
echo ""
du -sh "$DATA_DIR"/*
