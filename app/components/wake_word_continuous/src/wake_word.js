// wake_word_continuous — bundled with vite into dist/wake_word.bundle.js
// ---------------------------------------------------------------------
// Continuous wake-word detection ("Hey CJP" / "CJP") + 5-second-silence
// end-pointed capture for the CJ Panganiban museum kiosk.
//
// Stack — fully open-source, zero per-device cost:
//   • openWakeWord  (Apache-2.0)  — three ONNX models in a 3-stage
//                                   pipeline:
//                                     melspectrogram.onnx
//                                       → embedding_model.onnx
//                                         → wake_word.onnx  (custom)
//   • Silero VAD    (MIT)         — silence end-pointer
//   • ONNX Runtime Web            — runs all ONNX inference in the
//                                   browser via WASM
//   • Custom AudioWorklet         — 48 kHz mic → 16 kHz mono Float32
//                                   in 80 ms chunks (1280 samples)
//
// No Picovoice. No access key. No license check. Bundle is hermetic
// once `npm run build` produces dist/wake_word.bundle.js and the
// models/ directory.
//
// State machine (every transition emits a status message to
// Streamlit so the Python side can paint a live "🎤 LISTENING…" /
// "🎙️ CAPTURING…" / "⏳ THINKING…" / "🔊 SPEAKING…" pill):
//
//   IDLE → INITIALIZING (load 4 ONNX + mic) → LISTENING_FOR_WAKE
//     ↓ wake fires ("Hey CJP" / "CJP")
//   CAPTURING_QUESTION
//     ↓ Silero VAD reports 5 s of continuous silence  OR  20 s cap
//   SENDING (encode 16 kHz mono WAV, base64, post to Streamlit)
//     ↓
//   SUSPENDED_FOR_PROCESSING (Porcupine equivalent: ignore wake fires)
//     ↓ Python flips is_busy=false AND announces tts_duration_ms
//   SUSPENDED_FOR_PLAYBACK
//     ↓ setTimeout(tts_duration_ms + 500 ms safety)
//   LISTENING_FOR_WAKE
//
// CORRECTNESS PROPERTY:
//   While the kiosk is processing or playing CJ's reply, wake-word
//   inference scores ARE STILL COMPUTED (we still run the models so
//   the rolling buffers stay warm) but the threshold-cross handler is
//   short-circuited. That stops the kiosk from hearing "Hey CJP"
//   inside CJ's own response and re-triggering itself.

import * as ort from 'onnxruntime-web';
// Vite ?url import — gives us a URL to the worklet file post-bundle.
import pcmWorkletUrl from './pcm-worklet.js?url';

// ONNX Runtime Web's WASM artefacts are copied into ./models/ort/ by
// `npm run copy-ort-wasm`. Point ORT at them so it doesn't try to
// fetch from a CDN — the kiosk runs fully offline once loaded.
ort.env.wasm.wasmPaths = './models/ort/';
ort.env.wasm.numThreads = 1;       // simpler, fits the single-tab kiosk
ort.env.logLevel = 'warning';

// ── Streamlit message protocol ──────────────────────────────────────
// We don't import streamlit-component-lib (React + 80 kB overhead) —
// the wire protocol is small and stable; re-implementing it inline
// keeps the bundle slim and the dependency surface flat.
const Streamlit = {
  setComponentReady() {
    window.parent.postMessage(
      { isStreamlitMessage: true, type: 'streamlit:componentReady', apiVersion: 1 },
      '*'
    );
  },
  setFrameHeight(height) {
    window.parent.postMessage(
      { isStreamlitMessage: true, type: 'streamlit:setFrameHeight', height: height | 0 },
      '*'
    );
  },
  setComponentValue(value) {
    window.parent.postMessage(
      { isStreamlitMessage: true, type: 'streamlit:setComponentValue', value, dataType: 'json' },
      '*'
    );
  },
};

// ── openWakeWord constants ─────────────────────────────────────────
// These mirror the canonical openWakeWord Python pipeline (model.py
// in dscripka/openWakeWord). Changing them requires retraining.
const SAMPLE_RATE = 16000;
const PCM_CHUNK = 1280;          // 80 ms input to melspectrogram.onnx
const MEL_PER_CHUNK = 5;         // melspectrogram.onnx emits 5 frames
const MEL_BINS = 32;
const MEL_WINDOW = 76;           // embedding_model.onnx input window
const EMBEDDING_DIM = 96;
const EMBEDDING_WINDOW = 16;     // wake-word classifier input window
const WAKE_THRESHOLD = 0.5;      // tune per-model in the field

// VAD constants — Silero v5 expects 512-sample chunks at 16 kHz.
const VAD_CHUNK = 512;
const VAD_THRESHOLD = 0.5;       // P(voice); below = silence

// ── Wake-word component runtime ─────────────────────────────────────
class WakeWordKiosk {
  constructor() {
    this.state = 'IDLE';
    this.props = {};
    this.audioCtx = null;
    this.mediaStream = null;
    this.workletNode = null;

    // ONNX sessions
    this.melSess = null;
    this.embSess = null;
    this.wakeSess = null;
    this.vadSess = null;
    this.vadState = null;       // Silero hidden state (carried across chunks)

    // Rolling buffers
    this.melBuf = [];            // last MEL_WINDOW frames of 32-bin mels
    this.embBuf = [];            // last EMBEDDING_WINDOW 96-dim vectors
    this.pcmCaptureFrames = [];  // Int16 PCM frames during CAPTURING
    this.vadPcmBuf = new Float32Array(0); // accumulator for 512-sample VAD chunks

    // Timing
    this.captureStart = 0;
    this.lastVoiceTs = 0;
    this.silenceMs = 0;
    this.totalVadFrames = 0;
    this.voiceVadFrames = 0;
    this.resumeTimer = null;

    // UI
    this.statusEl = null;
    this.pillEl = null;
    this._lastEmittedStatus = '';
  }

  // ── Visual surface inside the iframe ──
  mountUi(root) {
    root.innerHTML = `
      <div class="ww-pill ww-pill-loading">
        <span class="ww-spinner"></span>
        <span class="ww-status-text">Initialising…</span>
      </div>
    `;
    this.statusEl = root.querySelector('.ww-status-text');
    this.pillEl = root.querySelector('.ww-pill');
  }

  setVisualStatus(label, cls) {
    if (this.statusEl) this.statusEl.textContent = label;
    if (this.pillEl)   this.pillEl.className = 'ww-pill ww-pill-' + cls;
  }

  emitStatus() {
    if (this.state === this._lastEmittedStatus) return;
    this._lastEmittedStatus = this.state;
    Streamlit.setComponentValue({ __status: this.state, ts: Date.now() });
  }

  // ── Streamlit prop lifecycle ──
  applyProps(rawProps) {
    const next = rawProps || {};
    const enabledChanged = next.enabled !== this.props.enabled;
    this.props = next;

    if (this.state === 'IDLE' && next.enabled !== false) {
      this._boot();
      return;
    }
    if (this.state === 'SUSPENDED_FOR_PROCESSING' &&
        next.is_busy === false &&
        Number(next.tts_duration_ms) > 0) {
      this._enterPlaybackSuspension(Number(next.tts_duration_ms));
    }
  }

  // ── Boot: load ONNX models + open mic + start worklet ──
  async _boot() {
    try {
      this.state = 'INITIALIZING';
      this.setVisualStatus('Loading models…', 'loading');
      this.emitStatus();

      const opts = { executionProviders: ['wasm'], graphOptimizationLevel: 'all' };

      // Three pipeline models. wake_word.onnx is OPTIONAL — its
      // absence means the user hasn't trained the "Hey CJP" classifier
      // yet, and we surface a clear status instead of failing silently.
      this.melSess  = await ort.InferenceSession.create('./models/melspectrogram.onnx', opts);
      this.embSess  = await ort.InferenceSession.create('./models/embedding_model.onnx', opts);
      try {
        this.wakeSess = await ort.InferenceSession.create('./models/wake_word.onnx', opts);
      } catch (e) {
        console.warn('[wake_word] wake_word.onnx missing — see TRAINING.md');
        this.state = 'IDLE';
        this.setVisualStatus('Wake-word model not loaded (see TRAINING.md)', 'error');
        Streamlit.setComponentValue({
          __status: 'WAKE_WORD_MODEL_MISSING',
          error: 'Drop a trained "Hey CJP" wake_word.onnx into the models/ directory.',
        });
        return;
      }
      this.vadSess  = await ort.InferenceSession.create('./models/silero_vad.onnx', opts);
      this._resetVadState();

      // Mic.
      this.setVisualStatus('Activating microphone…', 'loading');
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1, sampleRate: SAMPLE_RATE,
          echoCancellation: true, noiseSuppression: true, autoGainControl: true,
        },
      });

      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)(
        { sampleRate: SAMPLE_RATE }
      );
      await this.audioCtx.audioWorklet.addModule(pcmWorkletUrl);
      const source = this.audioCtx.createMediaStreamSource(this.mediaStream);
      this.workletNode = new AudioWorkletNode(this.audioCtx, 'pcm-downsampler');
      this.workletNode.port.onmessage = (e) => this._onPcmChunk(e.data);
      source.connect(this.workletNode);
      // Don't connect to destination — we don't want mic feedback.

      this.state = 'LISTENING_FOR_WAKE';
      this.setVisualStatus('Listening for "Hey CJP"…', 'listening');
      this.emitStatus();
    } catch (err) {
      console.error('[wake_word] boot failed', err);
      this.state = 'IDLE';
      this.setVisualStatus('Setup failed — see console', 'error');
      Streamlit.setComponentValue({
        __status: 'ERROR',
        error: String(err?.message || err),
      });
    }
  }

  _resetVadState() {
    // Silero v5 keeps a (2, 1, 128) hidden state vector across chunks.
    this.vadState = new ort.Tensor('float32', new Float32Array(2 * 1 * 128), [2, 1, 128]);
  }

  // ── Per-chunk PCM handler (called by the AudioWorklet every 80 ms) ──
  async _onPcmChunk(float32Chunk) {
    // 1) Wake-word pipeline: always run so rolling buffers stay warm.
    await this._stepWakePipeline(float32Chunk);

    // 2) VAD pipeline: only matters when CAPTURING — but we still buffer
    //    PCM so we don't miss the leading edge of the question.
    if (this.state === 'CAPTURING_QUESTION') {
      this._captureChunk(float32Chunk);
      await this._stepVad(float32Chunk);
    }
  }

  // openWakeWord 3-stage pipeline:
  //   PCM 1280 samples → melspectrogram (5×32) → embedding (96) → wake score (1)
  async _stepWakePipeline(float32Chunk) {
    if (!this.melSess || !this.embSess || !this.wakeSess) return;

    // Stage 1 — melspectrogram. Input shape: [1, 1280].
    const melIn = new ort.Tensor('float32', float32Chunk, [1, PCM_CHUNK]);
    const melOut = await this.melSess.run({ [this.melSess.inputNames[0]]: melIn });
    const mel = melOut[this.melSess.outputNames[0]];
    // mel shape: [1, 1, MEL_PER_CHUNK, MEL_BINS] or [1, MEL_PER_CHUNK, MEL_BINS].
    // Normalise + push frames into the rolling mel buffer.
    const melData = mel.data;
    const totalMels = mel.dims.reduce((a, b) => a * b, 1);
    // Apply openWakeWord's mel scaling: (mel / 10) + 2.
    for (let i = 0; i < totalMels; i++) melData[i] = melData[i] / 10 + 2;
    for (let f = 0; f < MEL_PER_CHUNK; f++) {
      const frame = new Float32Array(MEL_BINS);
      for (let b = 0; b < MEL_BINS; b++) {
        frame[b] = melData[f * MEL_BINS + b];
      }
      this.melBuf.push(frame);
    }
    while (this.melBuf.length > MEL_WINDOW + MEL_PER_CHUNK) this.melBuf.shift();
    if (this.melBuf.length < MEL_WINDOW) return;

    // Stage 2 — embedding. Input shape: [1, MEL_WINDOW, MEL_BINS, 1].
    const embIn = new Float32Array(MEL_WINDOW * MEL_BINS);
    const offset = this.melBuf.length - MEL_WINDOW;
    for (let f = 0; f < MEL_WINDOW; f++) {
      for (let b = 0; b < MEL_BINS; b++) {
        embIn[f * MEL_BINS + b] = this.melBuf[offset + f][b];
      }
    }
    const embInTensor = new ort.Tensor('float32', embIn, [1, MEL_WINDOW, MEL_BINS, 1]);
    const embOut = await this.embSess.run({ [this.embSess.inputNames[0]]: embInTensor });
    const emb = embOut[this.embSess.outputNames[0]];
    const embVec = new Float32Array(EMBEDDING_DIM);
    embVec.set(emb.data.subarray(0, EMBEDDING_DIM));
    this.embBuf.push(embVec);
    while (this.embBuf.length > EMBEDDING_WINDOW + 1) this.embBuf.shift();
    if (this.embBuf.length < EMBEDDING_WINDOW) return;

    // Stage 3 — wake-word classifier. Input shape: [1, EMBEDDING_WINDOW, EMBEDDING_DIM].
    const wakeIn = new Float32Array(EMBEDDING_WINDOW * EMBEDDING_DIM);
    const eOffset = this.embBuf.length - EMBEDDING_WINDOW;
    for (let i = 0; i < EMBEDDING_WINDOW; i++) {
      wakeIn.set(this.embBuf[eOffset + i], i * EMBEDDING_DIM);
    }
    const wakeInTensor = new ort.Tensor('float32', wakeIn, [1, EMBEDDING_WINDOW, EMBEDDING_DIM]);
    const wakeOut = await this.wakeSess.run({ [this.wakeSess.inputNames[0]]: wakeInTensor });
    const score = wakeOut[this.wakeSess.outputNames[0]].data[0];

    if (score >= WAKE_THRESHOLD && this.state === 'LISTENING_FOR_WAKE') {
      this._beginCapture();
    }
    // Score is still computed in SUSPENDED_* states (to keep the
    // buffers warm) but ignored — the self-trigger guard.
  }

  _beginCapture() {
    this.state = 'CAPTURING_QUESTION';
    this.pcmCaptureFrames = [];
    this.captureStart = performance.now();
    this.lastVoiceTs = this.captureStart;
    this.silenceMs = 0;
    this.totalVadFrames = 0;
    this.voiceVadFrames = 0;
    this._resetVadState();
    this.setVisualStatus('Listening to your question…', 'capturing');
    this.emitStatus();
  }

  _captureChunk(float32Chunk) {
    // Convert Float32 → Int16 for WAV encoding later.
    const int16 = new Int16Array(float32Chunk.length);
    for (let i = 0; i < float32Chunk.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Chunk[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    this.pcmCaptureFrames.push(int16);
  }

  async _stepVad(float32Chunk) {
    if (!this.vadSess) return;
    // Silero v5 wants exactly 512-sample chunks. Our worklet emits
    // 1280; carry the remainder forward via vadPcmBuf.
    const combined = new Float32Array(this.vadPcmBuf.length + float32Chunk.length);
    combined.set(this.vadPcmBuf, 0);
    combined.set(float32Chunk, this.vadPcmBuf.length);
    let pos = 0;
    const now = performance.now();
    const silenceCap = this.props.silence_ms ?? 5000;
    const maxCap = this.props.max_question_ms ?? 20000;

    while (combined.length - pos >= VAD_CHUNK) {
      const slice = combined.subarray(pos, pos + VAD_CHUNK);
      pos += VAD_CHUNK;
      const vadIn = new ort.Tensor('float32', slice, [1, VAD_CHUNK]);
      const sr = new ort.Tensor('int64', new BigInt64Array([BigInt(SAMPLE_RATE)]), [1]);
      const out = await this.vadSess.run({
        input: vadIn, state: this.vadState, sr,
      });
      this.vadState = out.stateN;
      const voiceProb = out.output.data[0];
      this.totalVadFrames++;
      if (voiceProb >= VAD_THRESHOLD) {
        this.voiceVadFrames++;
        this.lastVoiceTs = now;
        this.silenceMs = 0;
      } else {
        this.silenceMs = now - this.lastVoiceTs;
      }
    }
    this.vadPcmBuf = new Float32Array(combined.length - pos);
    this.vadPcmBuf.set(combined.subarray(pos));

    const elapsedMs = now - this.captureStart;
    if (this.silenceMs >= silenceCap) {
      this._endCapture('silence');
    } else if (elapsedMs >= maxCap) {
      this._endCapture('max_duration');
    }
  }

  _endCapture(reason) {
    this.state = 'SENDING';
    this.setVisualStatus('Thinking…', 'processing');
    this.emitStatus();

    // Concat all Int16 PCM frames, wrap with minimal WAV header.
    const frames = this.pcmCaptureFrames;
    let total = 0;
    for (const c of frames) total += c.length;
    const pcm = new Int16Array(total);
    let off = 0;
    for (const c of frames) { pcm.set(c, off); off += c.length; }
    this.pcmCaptureFrames = [];
    const wavBytes = encodeWav16khzMono(pcm);

    const audio_b64 = bytesToBase64(wavBytes);
    sha256Hex(wavBytes).then((audio_sha256) => {
      const vad_voice_ratio = this.totalVadFrames > 0
        ? this.voiceVadFrames / this.totalVadFrames : 0;
      Streamlit.setComponentValue({
        audio_b64,
        audio_sha256,
        wake_fired_at: Math.floor(performance.timeOrigin + this.captureStart),
        capture_ended_reason: reason,
        vad_voice_ratio,
        __status: 'SENDING',
        ts: Date.now(),
      });
      this.state = 'SUSPENDED_FOR_PROCESSING';
      this.emitStatus();
    });
  }

  _enterPlaybackSuspension(durationMs) {
    if (this.resumeTimer) clearTimeout(this.resumeTimer);
    this.state = 'SUSPENDED_FOR_PLAYBACK';
    this.setVisualStatus('CJ is speaking…', 'speaking');
    this.emitStatus();
    const safetyMs = 500;
    this.resumeTimer = setTimeout(() => {
      this.resumeTimer = null;
      this.state = 'LISTENING_FOR_WAKE';
      this.setVisualStatus('Listening for "Hey CJP"…', 'listening');
      this.emitStatus();
    }, durationMs + safetyMs);
  }
}

// ── WAV encoder — 16 kHz · mono · 16-bit PCM ────────────────────────
function encodeWav16khzMono(pcmInt16) {
  const NUM_CHANNELS = 1, BITS_PER_SAMPLE = 16;
  const byteRate = SAMPLE_RATE * NUM_CHANNELS * BITS_PER_SAMPLE / 8;
  const blockAlign = NUM_CHANNELS * BITS_PER_SAMPLE / 8;
  const dataLen = pcmInt16.byteLength;
  const buf = new ArrayBuffer(44 + dataLen);
  const dv = new DataView(buf);
  let p = 0;
  const w8 = (s) => { for (let i = 0; i < s.length; i++) dv.setUint8(p++, s.charCodeAt(i)); };
  const w32 = (v) => { dv.setUint32(p, v, true); p += 4; };
  const w16 = (v) => { dv.setUint16(p, v, true); p += 2; };
  w8('RIFF');           w32(36 + dataLen);   w8('WAVE');
  w8('fmt ');           w32(16);             w16(1);                w16(NUM_CHANNELS);
  w32(SAMPLE_RATE);     w32(byteRate);       w16(blockAlign);       w16(BITS_PER_SAMPLE);
  w8('data');           w32(dataLen);
  new Int16Array(buf, 44).set(pcmInt16);
  return new Uint8Array(buf);
}

function bytesToBase64(bytes) {
  let bin = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(bin);
}

async function sha256Hex(bytes) {
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

// ── Bootstrap ──
const kiosk = new WakeWordKiosk();

window.addEventListener('DOMContentLoaded', () => {
  kiosk.mountUi(document.getElementById('root'));
  Streamlit.setFrameHeight(64);
  Streamlit.setComponentReady();
});

window.addEventListener('message', (event) => {
  const msg = event.data;
  if (!msg || !msg.type) return;
  if (msg.type === 'streamlit:render') {
    kiosk.applyProps(msg.args || {});
    Streamlit.setFrameHeight(64);
  }
});

// IIFE side-effect bundle — nothing to export.
export {};
