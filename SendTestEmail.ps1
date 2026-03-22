# SendTestEmail.ps1
# Sends a test email to kiaconwell@gmail.com from Erin's Outlook account
# Save this anywhere on your computer and double-click to run

$From     = "erinswyrick85@gmail.com"
$AppPass  = "YOUR_GMAIL_APP_PASSWORD_HERE"
$To       = "kiaconwell@gmail.com"
$Subject  = "Test - Lead Bot Email Working!"
$Body     = @"
Hi Kia,

This is a test email from Erin's Lead Bot.

If you are reading this, the email system is set up and working correctly!

Going forward you will automatically receive new insurance leads at this email address.

- Erin
"@

Write-Host ""
Write-Host "Sending test email to $To ..." -ForegroundColor Cyan

try {
    $smtp = New-Object Net.Mail.SmtpClient("smtp.gmail.com", 587)
    $smtp.EnableSsl   = $true
    $smtp.Credentials = New-Object Net.NetworkCredential($From, $AppPass)

    $msg            = New-Object Net.Mail.MailMessage
    $msg.From       = $From
    $msg.To.Add($To)
    $msg.Subject    = $Subject
    $msg.Body       = $Body

    $smtp.Send($msg)

    Write-Host ""
    Write-Host "SUCCESS! Email sent to $To" -ForegroundColor Green
    Write-Host "Tell Kia to check her Gmail inbox (and spam just in case)." -ForegroundColor Yellow
}
catch {
    Write-Host ""
    Write-Host "FAILED: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "Press Enter to close..."
Read-Host
