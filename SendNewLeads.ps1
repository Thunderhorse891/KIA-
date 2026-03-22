# SendNewLeads.ps1
# Scrapes Reddit + Craigslist and immediately emails any new leads to Kia.
# Does NOT wait for 50 -- sends whatever is new right now.
# Right-click -> "Run with PowerShell"

$ErrorActionPreference = "Stop"
$botFolder = Join-Path ([Environment]::GetFolderPath("Desktop")) "LeadBot"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   SEND NEW LEADS NOW" -ForegroundColor Cyan
Write-Host "   Scrapes + emails immediately (no wait)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $botFolder)) {
    Write-Host "ERROR: LeadBot folder not found at $botFolder" -ForegroundColor Red
    Write-Host "Run RunLeadBot.ps1 first to set things up." -ForegroundColor Yellow
    Write-Host ""; Read-Host "Press Enter to close"; exit 1
}

$pythonFile = "$botFolder\lead_bot.py"
if (-not (Test-Path $pythonFile)) {
    Write-Host "ERROR: lead_bot.py not found. Run RunLeadBot.ps1 first." -ForegroundColor Red
    Write-Host ""; Read-Host "Press Enter to close"; exit 1
}

# Gmail SMTP credentials
$env:SMTP_HOST  = "smtp.gmail.com"
$env:SMTP_PORT  = "587"
$env:SMTP_USER  = "erinswyrick85@gmail.com"
$env:SMTP_PASS  = "vfmqmvcclevvvmkl"
$env:SMTP_FROM  = "erinswyrick85@gmail.com"
$env:LEADBOT_DB = "$botFolder\leadbot.db"

Write-Host "Scraping for new leads -- this takes a few minutes..." -ForegroundColor Yellow
Write-Host "(Ctrl+C to stop at any time)" -ForegroundColor Gray
Write-Host ""

# --force-send sends whatever new leads exist immediately, no 50-lead wait
python $pythonFile --force-send
$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "Done!" -ForegroundColor Green
} else {
    Write-Host "Something went wrong (exit code $exitCode). Check errors above." -ForegroundColor Red
}

Write-Host ""
Write-Host "Press Enter to close..."
Read-Host
