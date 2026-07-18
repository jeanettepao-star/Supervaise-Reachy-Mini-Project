# gen_filler_clips.ps1 — regenerate the two-stage TTFA filler pool with Windows SAPI ($0 stand-in).
# The .wav clips are gitignored (repo policy: *.wav); this script makes them reproducible.
# TODO: re-synthesize the pool with OpenAI tts-1 (~$0.03) or the robot's Piper voice for the real
# CJP voice — these SAPI clips are placeholders. Output dir = config.FILLER_CLIP_DIR default.
#
# Usage (from repo root):  powershell -ExecutionPolicy Bypass -File scripts\gen_filler_clips.ps1
$dir = Join-Path $PSScriptRoot "..\assets\filler_clips"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Add-Type -AssemblyName System.Speech
$clips = @{
  "filler_ack_1.wav"  = "Ah, let me think on that for a moment.";
  "filler_ack_2.wav"  = "Yes... allow me to gather my thoughts.";
  "filler_ack_3.wav"  = "Hmm, let me consider that.";
  "filler_ack_4.wav"  = "A moment, please, let me recall.";
  "filler_bridge.wav" = "Yes... let me put it this way."
}
foreach ($k in $clips.Keys) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.Rate = -1
  $s.SetOutputToWaveFile((Join-Path $dir $k))
  $s.Speak($clips[$k])
  $s.Dispose()
}
Write-Host "Wrote 5 filler clips to $dir"
