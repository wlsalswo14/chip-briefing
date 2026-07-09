$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $here "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDir "daily-$stamp.log"

try {
  "[$(Get-Date -Format s)] start chip briefing update" | Out-File -FilePath $logPath -Encoding utf8
  & "$here\run_collector.ps1" *>> $logPath
  "[$(Get-Date -Format s)] send telegram archive" | Out-File -FilePath $logPath -Encoding utf8 -Append
  python "$here\send_telegram_archive.py" *>> $logPath
  "[$(Get-Date -Format s)] done" | Out-File -FilePath $logPath -Encoding utf8 -Append
} catch {
  "[$(Get-Date -Format s)] failed: $($_.Exception.Message)" | Out-File -FilePath $logPath -Encoding utf8 -Append
  throw
}
