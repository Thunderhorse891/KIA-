# SendTestEmail.ps1
# Loads SMTP credentials from .env and sends a test email to kiaconwell@gmail.com

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== KIA Lead Bot - Test Email Sender ===" -ForegroundColor Cyan
Write-Host ""

# ── 1. Find the .env file ────────────────────────────────────────────────────
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $scriptDir ".env"

if (-not (Test-Path $envFile)) {
    Write-Host "ERROR: .env file not found at: $envFile" -ForegroundColor Red
    Write-Host "Make sure .env exists in the same folder as this script." -ForegroundColor Yellow
    exit 1
}

# ── 2. Load .env into environment variables ──────────────────────────────────
Write-Host "Loading credentials from .env..." -ForegroundColor Gray
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
        $parts = $line -split "=", 2
        if ($parts.Count -eq 2) {
            $key   = $parts[0].Trim()
            $value = $parts[1].Trim()
            [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}
Write-Host "  SMTP_HOST : $env:SMTP_HOST" -ForegroundColor Gray
Write-Host "  SMTP_USER : $env:SMTP_USER" -ForegroundColor Gray
Write-Host "  SMTP_PASS : $('*' * $env:SMTP_PASS.Length)" -ForegroundColor Gray
Write-Host ""

# ── 3. Check Python is available ─────────────────────────────────────────────
$python = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python") {
            $python = $cmd
            Write-Host "Python found: $ver" -ForegroundColor Green
            break
        }
    } catch { }
}

if (-not $python) {
    Write-Host "ERROR: Python not found. Please install Python 3 and try again." -ForegroundColor Red
    exit 1
}

# ── 4. Build the test referral command ───────────────────────────────────────
$leadBotScript = Join-Path $scriptDir "lead_bot.py"

if (-not (Test-Path $leadBotScript)) {
    Write-Host "ERROR: lead_bot.py not found at: $leadBotScript" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Sending test email to kiaconwell@gmail.com..." -ForegroundColor Cyan

$args = @(
    $leadBotScript,
    "add-referral",
    "--source",   "TEST",
    "--name",     "Test Lead",
    "--email",    "test@example.com",
    "--question", "This is a test referral email from Erin's Lead Bot. If you received this, everything is working!",
    "--tags",     "test",
    "--notify-partner"
)

# ── 5. Run lead_bot.py ───────────────────────────────────────────────────────
try {
    & $python @args
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host ""
    Write-Host "ERROR running lead_bot.py: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "SUCCESS! Test email sent to kiaconwell@gmail.com" -ForegroundColor Green
    Write-Host "Tell Kia to check her Gmail inbox (and spam folder just in case)." -ForegroundColor Yellow
} else {
    Write-Host "FAILED. Exit code: $exitCode" -ForegroundColor Red
    Write-Host "Double-check your app password in the .env file." -ForegroundColor Yellow
}
Write-Host ""
