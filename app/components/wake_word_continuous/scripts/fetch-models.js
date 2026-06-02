// Download the SHARED openWakeWord pipeline + Silero VAD into ./models/
// so the bundle can fetch them at runtime via publicPath. Run
// automatically by `npm run prebuild`. Idempotent — files that
// already exist are skipped, so re-running is cheap.
//
// The wake-word classifier itself (wake_word.onnx) is NOT downloaded
// here. The kiosk's wake phrase is "Hey CJP" / "CJP" which is
// specific to this project and must be custom-trained. See
// docs/train_hey_cjp.md (or ../wake_word_training/) for the offline
// training pipeline. After training, drop the resulting ONNX file
// into models/wake_word.onnx and re-build the bundle.
//
// Until wake_word.onnx exists, the kiosk's wake-word component
// surfaces a clear "wake-word model missing" status pill — it does
// NOT fall back to a generic word like "Hey Jarvis", because firing
// on the wrong phrase mid-demo would be worse than disabling the
// feature.
//
// All upstream sources are Apache-2.0 (openWakeWord) or MIT
// (Silero VAD). No accounts. No keys. No per-device licensing.

const fs = require('fs');
const path = require('path');
const https = require('https');

const MODELS_DIR = path.resolve(__dirname, '..', 'models');
fs.mkdirSync(MODELS_DIR, { recursive: true });

const MODELS = [
  // openWakeWord pre-processing pipeline. Both feed every wake-word
  // classifier produced by the openWakeWord training pipeline.
  {
    out: 'melspectrogram.onnx',
    url: 'https://github.com/dscripka/openWakeWord/raw/v0.6.0/openwakeword/resources/models/melspectrogram.onnx',
    notes: 'PCM 1280 samples (80 ms @ 16 kHz) → 5 frames × 32 mel bins',
  },
  {
    out: 'embedding_model.onnx',
    url: 'https://github.com/dscripka/openWakeWord/raw/v0.6.0/openwakeword/resources/models/embedding_model.onnx',
    notes: '76 mel frames → 96-dim embedding (consumed by wake_word.onnx)',
  },
  // Silero VAD — for the 5-second-silence end-pointer. Replaces
  // Picovoice Cobra at zero cost, MIT-licensed.
  {
    out: 'silero_vad.onnx',
    url: 'https://github.com/snakers4/silero-vad/raw/v5.1/src/silero_vad/data/silero_vad.onnx',
    notes: 'VAD: 512-sample chunks @ 16 kHz → P(voice) per chunk',
  },
];

function download(url, out, redirects = 0) {
  return new Promise((resolve, reject) => {
    if (redirects > 5) return reject(new Error('Too many redirects: ' + url));
    https.get(url, (res) => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        return resolve(download(res.headers.location, out, redirects + 1));
      }
      if (res.statusCode !== 200) {
        return reject(new Error(`${url}: HTTP ${res.statusCode}`));
      }
      const file = fs.createWriteStream(out);
      res.pipe(file);
      file.on('finish', () => file.close(() => resolve(out)));
      file.on('error', reject);
    }).on('error', reject);
  });
}

(async () => {
  for (const m of MODELS) {
    const outPath = path.join(MODELS_DIR, m.out);
    if (fs.existsSync(outPath)) {
      console.log(`✓ ${m.out} already present, skipping`);
      continue;
    }
    process.stdout.write(`↓ fetching ${m.out} (${m.notes}) … `);
    try {
      await download(m.url, outPath);
      const sizeKb = (fs.statSync(outPath).size / 1024).toFixed(1);
      console.log(`done (${sizeKb} kB)`);
    } catch (err) {
      console.error(`FAILED: ${err.message}`);
      console.error(`Download manually from: ${m.url}`);
      console.error(`Save to:                 ${outPath}`);
      process.exit(1);
    }
  }
  // Reminder about the user-supplied classifier.
  const wakeOnnx = path.join(MODELS_DIR, 'wake_word.onnx');
  if (!fs.existsSync(wakeOnnx)) {
    console.log('');
    console.log('────────────────────────────────────────────────────────────');
    console.log('  REMAINING STEP: train the "Hey CJP" classifier.');
    console.log('  ');
    console.log('  models/wake_word.onnx is NOT auto-downloaded — the wake');
    console.log('  phrase is project-specific and must be trained.');
    console.log('  ');
    console.log('  See: app/components/wake_word_continuous/TRAINING.md');
    console.log('  Run on Colab (free T4 GPU), takes ~2-4 hours, produces');
    console.log('  a single .onnx file. Drop it into:');
    console.log(`  ${wakeOnnx}`);
    console.log('  ');
    console.log('  Until then the kiosk shows a clear "wake-word model not');
    console.log('  loaded" status and visitors can use the START/STOP pill.');
    console.log('────────────────────────────────────────────────────────────');
  } else {
    console.log(`✓ wake_word.onnx is in place`);
  }
})();
