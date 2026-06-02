// AudioWorklet: downsamples the browser's native mic stream (usually
// 48 kHz Float32 stereo) into 16 kHz mono Float32 chunks of exactly
// 1280 samples (80 ms), then posts each chunk to the main thread.
// 1280 is the input frame size openWakeWord's melspectrogram model
// expects.
//
// This file is loaded as an AudioWorkletProcessor module via
// `audioContext.audioWorklet.addModule(workletUrl)`. It runs in its
// own thread (the audio rendering thread) so the main JS thread stays
// free for ONNX inference.

class PcmDownsampler extends AudioWorkletProcessor {
  constructor() {
    super();
    // Native sample rate of the AudioContext (typically 48000).
    this.inRate = sampleRate;
    this.outRate = 16000;
    this.ratio = this.inRate / this.outRate;
    // Output chunk = 1280 samples = 80 ms at 16 kHz
    this.chunkSize = 1280;
    this.buffer = new Float32Array(this.chunkSize);
    this.bufferFill = 0;
    // Phase accumulator for the downsampler — fractional sample
    // position in the source stream that maps to the next output
    // sample. Linear interpolation between adjacent input samples.
    this.phase = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) return true;

    // Mix down to mono (average channels).
    const ch0 = input[0];
    const ch1 = input.length > 1 ? input[1] : null;
    const inLen = ch0.length;

    while (this.phase < inLen) {
      const i0 = Math.floor(this.phase);
      const frac = this.phase - i0;
      const i1 = Math.min(i0 + 1, inLen - 1);
      let s0 = ch0[i0], s1 = ch0[i1];
      if (ch1) {
        s0 = 0.5 * (s0 + ch1[i0]);
        s1 = 0.5 * (s1 + ch1[i1]);
      }
      this.buffer[this.bufferFill++] = s0 + frac * (s1 - s0);

      if (this.bufferFill === this.chunkSize) {
        // Post a copy so the worklet's buffer can be reused.
        this.port.postMessage(this.buffer.slice());
        this.bufferFill = 0;
      }
      this.phase += this.ratio;
    }
    // Carry the fractional phase across the input boundary.
    this.phase -= inLen;
    return true;
  }
}

registerProcessor('pcm-downsampler', PcmDownsampler);
