# =============================================================================
# KIA- Lead Bot — Test Script
# Sends a test lead email to kiaconwell@gmail.com
#
# HOW TO RUN:
#   1. Fill in SMTP_PASS below with your Outlook App Password
#   2. Open PowerShell and run:
#        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#        .\test_send.ps1
# =============================================================================

# ---------------------------------------------------------------------------
# STEP 1: Configure — fill in your Outlook App Password here
# ---------------------------------------------------------------------------
$env:SMTP_HOST = "smtp.office365.com"
$env:SMTP_PORT = "587"
$env:SMTP_USER = "Erin067841@outlook.com"
$env:SMTP_PASS = "PASTE_YOUR_OUTLOOK_APP_PASSWORD_HERE"   # <-- fill this in
$env:SMTP_FROM = "Erin067841@outlook.com"
$env:LEADBOT_REPORT_TO = "Erin067841@outlook.com"
$env:PARTNER_EMAIL     = "kiaconwell@gmail.com"
$env:LEADBOT_DB        = "test_leadbot.db"   # separate DB so tests don't pollute real data

# ---------------------------------------------------------------------------
# STEP 2: Find Python
# ---------------------------------------------------------------------------
$python = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python 3") {
            $python = $candidate
            break
        }
    } catch {}
}

if (-not $python) {
    Write-Error "Python 3 not found. Install it from https://www.python.org/downloads/"
    exit 1
}

Write-Host "Using Python: $python ($( & $python --version 2>&1 ))" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# STEP 3: Move to repo directory (adjust path if needed)
# ---------------------------------------------------------------------------
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoDir
Write-Host "Working directory: $repoDir" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# STEP 4: Guard — remind user to set their password
# ---------------------------------------------------------------------------
if ($env:SMTP_PASS -eq "PASTE_YOUR_OUTLOOK_APP_PASSWORD_HERE") {
    Write-Host ""
    Write-Host "ERROR: You haven't set your Outlook App Password yet." -ForegroundColor Red
    Write-Host "  1. Go to https://account.microsoft.com" -ForegroundColor Yellow
    Write-Host "  2. Security -> Advanced security options -> App passwords" -ForegroundColor Yellow
    Write-Host "  3. Create a new app password, copy it" -ForegroundColor Yellow
    Write-Host "  4. Paste it into this script where it says PASTE_YOUR_OUTLOOK_APP_PASSWORD_HERE" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ---------------------------------------------------------------------------
# STEP 5: Add a test lead manually and email it to kiaconwell@gmail.com
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== TEST 1: Add a manual test lead and email to kiaconwell@gmail.com ===" -ForegroundColor Green

& $python lead_bot.py `
    --db $env:LEADBOT_DB `
    add-referral `
    --source "test:powershell-script" `
    --name "Test Person" `
    --email "testperson@example.com" `
    --question "Looking for a quote on auto and home insurance bundle in Georgia" `
    --tags "auto-insurance,home-insurance" `
    --owner "ERIN" `
    --notify-partner

if ($LASTEXITCODE -ne 0) {
    Write-Host "add-referral failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# STEP 6: Run the Reddit scraper (preview mode — no email sent)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== TEST 2: Reddit scraper preview (no email sent yet) ===" -ForegroundColor Green
Write-Host "Fetching live Reddit posts about auto/home insurance..." -ForegroundColor Cyan

& $python lead_bot.py `
    --db $env:LEADBOT_DB `
    web-scrape `
    --days 7 `
    --limit 5 `
    --no-notify-partner

if ($LASTEXITCODE -ne 0) {
    Write-Host "web-scrape preview failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# STEP 7: Run the scraper for real — emails leads to kiaconwell@gmail.com
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== TEST 3: Reddit scraper — email leads to kiaconwell@gmail.com ===" -ForegroundColor Green
Write-Host "This will send real emails to kiaconwell@gmail.com for any new leads found." -ForegroundColor Yellow

$confirm = Read-Host "Send scraped leads to kiaconwell@gmail.com now? (yes/no)"
if ($confirm -eq "yes") {
    & $python lead_bot.py `
        --db $env:LEADBOT_DB `
        web-scrape `
        --days 7 `
        --limit 10

    if ($LASTEXITCODE -ne 0) {
        Write-Host "web-scrape with email failed (exit $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Skipped live send." -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# STEP 8: Print a summary of everything in the test database
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== TEST 4: Referral summary (what's in the test database) ===" -ForegroundColor Green

& $python lead_bot.py `
    --db $env:LEADBOT_DB `
    referral-summary `
    --days 30

# ---------------------------------------------------------------------------
# Cleanup test database
# ---------------------------------------------------------------------------
Write-Host ""
if (Test-Path $env:LEADBOT_DB) {
    Remove-Item $env:LEADBOT_DB -Force
    Write-Host "Cleaned up test database ($($env:LEADBOT_DB))." -ForegroundColor Gray
}

Write-Host ""
Write-Host "=== ALL TESTS COMPLETE ===" -ForegroundColor Green
Write-Host "Check kiaconwell@gmail.com for the test lead email." -ForegroundColor Cyan
