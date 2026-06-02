import { defineConfig } from 'vite';
import { resolve } from 'path';

// Single-file IIFE bundle that index.html pulls in via a plain
// <script src="..."> tag. The output goes into ./dist/. The
// AudioWorklet file (src/pcm-worklet.js) is emitted as a SEPARATE
// asset (it can't be inlined — AudioWorkletProcessor must load from
// a URL the browser can resolve) but is committed alongside the
// bundle for hermeticity.
//
// ONNX Runtime Web's WASM artefacts are NOT bundled by vite —
// they're copied into ./models/ort/ by `npm run copy-ort-wasm`, and
// ort.env.wasm.wasmPaths is set in src/wake_word.js to point there.
export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    sourcemap: false,
    minify: 'esbuild',
    target: 'es2020',
    rollupOptions: {
      input: resolve(__dirname, 'src/wake_word.js'),
      output: {
        format: 'iife',
        entryFileNames: 'wake_word.bundle.js',
        // Keep the worklet's filename stable so index.html can
        // reference it deterministically.
        assetFileNames: (asset) => {
          if (asset.name && asset.name.includes('pcm-worklet')) {
            return 'pcm-worklet.js';
          }
          return '[name][extname]';
        },
        chunkFileNames: '[name].js',
        inlineDynamicImports: true,
      },
    },
  },
});
