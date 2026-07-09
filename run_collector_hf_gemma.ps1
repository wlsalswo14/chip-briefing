$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $env:HF_TOKEN) {
  $desktopCandidates = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path $env:USERPROFILE "OneDrive\Desktop")
  )
  foreach ($desktopPath in $desktopCandidates) {
    if (-not (Test-Path -LiteralPath $desktopPath)) {
      continue
    }
    $tokenFiles = Get-ChildItem -LiteralPath $desktopPath -File -Filter "*.txt" -ErrorAction SilentlyContinue
    foreach ($tokenFile in $tokenFiles) {
      $candidate = (Get-Content -LiteralPath $tokenFile.FullName -Raw -Encoding utf8 -ErrorAction SilentlyContinue).Trim()
      $match = [regex]::Match($candidate, "hf_[A-Za-z0-9]{20,}")
      if ($match.Success) {
        $env:HF_TOKEN = $match.Value
        break
      }
    }
    if ($env:HF_TOKEN) {
      break
    }
  }
}

if (-not $env:HF_TOKEN) {
  throw "HF_TOKEN is not set and Hugging Face token file was not found."
}

if (-not $env:CHIP_BRIEFING_LLM_BASE_URL) {
  $env:CHIP_BRIEFING_LLM_BASE_URL = "https://router.huggingface.co/v1"
}
if (-not $env:CHIP_BRIEFING_LLM_MODEL) {
  $env:CHIP_BRIEFING_LLM_MODEL = "google/gemma-4-26B-A4B-it"
}
if (-not $env:CHIP_BRIEFING_LLM_MAX_ITEMS) {
  $env:CHIP_BRIEFING_LLM_MAX_ITEMS = $env:CHIP_BRIEFING_MAX_ITEMS
}

python "$here\collect_news.py"
