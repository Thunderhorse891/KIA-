# Kia Lead Generator Bot (Compliant)

## What this does
This bot gives you a complete referral pipeline:

1. Capture lead details with source + attribution code.
2. Route prospects to Kia (email + website).
3. Mark conversions and generate a $50 referral invoice event.
4. Mark which referral invoices are actually paid.
5. Auto-send weekly summary reports by email.

## How to run it

### Install / prerequisites
- Python 3.9+
- SMTP account (for email sending)

### 1) Add a lead
```bash
python3 lead_bot.py add \
  --source "facebook:group:atlanta-finance" \
  --name "Prospect Name" \
  --email "prospect@example.com" \
  --question "How can I protect my family with affordable life insurance?" \
  --tags "term-life,investing" \
  --owner "YOURNAME"
```

### 2) Mark Kia sale and invoice trigger
```bash
python3 lead_bot.py mark-sold --ref-code YOURNAME-LEAD-000001 --sale-amount 1200 --invoice-amount 50
```

### 3) Mark paid referrals (track who paid you)
```bash
python3 lead_bot.py mark-paid --ref-code YOURNAME-LEAD-000001 --paid-amount 50
```

### 4) Generate weekly report (console)
```bash
python3 lead_bot.py weekly-summary --days 7
```

### 5) Email weekly report to yourself
```bash
python3 lead_bot.py weekly-summary --days 7 --email --to Erin067841@outlook.com
```

## Fully automated weekly report to yourself

### A) Set environment variables (recommended)
```bash
export SMTP_HOST="smtp.yourprovider.com"
export SMTP_PORT="587"
export SMTP_USER="Erin067841@outlook.com"
export SMTP_PASS="YOUR_APP_PASSWORD"
export SMTP_FROM="Erin067841@outlook.com"
export LEADBOT_REPORT_TO="Erin067841@outlook.com"
```

Now you can run:
```bash
python3 lead_bot.py weekly-summary --days 7 --email
```

### B) Add cron job (runs every Monday at 8:00 AM)
```bash
0 8 * * 1 cd /workspace/KIA- && /usr/bin/python3 lead_bot.py --db leadbot.db weekly-summary --days 7 --email
```

## Contacts used by bot
- Kia Email: `KIACONWELL@PRIMERICA.COM`
- Kia Website: `https://livemore.net/o/kia_conwell`

## Compliance note
Use only compliant outreach and platform-approved engagement. This tool is for lead management and reporting, not blind spam automation.
