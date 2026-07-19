$dir = Join-Path $PSScriptRoot "..\eval\results\stt_bench_clips"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Add-Type -AssemblyName System.Speech
$clips = @{
  "q1_flp.wav"        = "What is the foundation for liberty and prosperity?";
  "q2_baron.wav"      = "What is baron travel?";
  "q3_dont_know.wav"  = "I don't know."
}
foreach ($k in $clips.Keys) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.Rate = 0
  $s.SetOutputToWaveFile((Join-Path $dir $k))
  $s.Speak($clips[$k])
  $s.Dispose()
}
Write-Host "Wrote 3 STT bench clips to $dir"
