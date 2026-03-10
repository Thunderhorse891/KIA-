# Kia Lead Generator Bot (Compliant)

## What this does
This bot gives you a referral pipeline focused on Kia only:

1. Capture leads with source + attribution code.
2. Route prospects to Kia (email + website).
3. Mark who bought (sold) and track paid finder-fee invoices.
4. Send **daily lead summaries to Kia**.

## Important reality check
- Without social media API keys, the bot cannot safely auto-post on your behalf across platforms.
- It supports compliant lead tracking and email workflows.
- You can still gather leads from public sources and import them in bulk via CSV.

## Core commands

### Add one lead
```bash
python3 lead_bot.py add \
  --source "reddit:personalfinance" \
  --name "Prospect Name" \
  --email "prospect@example.com" \
  --question "Need life insurance options" \
  --tags "term-life" \
  --owner "YOURNAME" \
  --notify-kia
```

### Bulk import leads from CSV
CSV columns required: `source,name,email,question,tags`

```bash
python3 lead_bot.py bulk-import --csv-file leads.csv --owner YOURNAME
```

### Mark sale (who bought Kia package)
```bash
python3 lead_bot.py mark-sold --ref-code YOURNAME-LEAD-000001 --sale-amount 1200 --invoice-amount 50
```

### Mark your finder-fee paid
```bash
python3 lead_bot.py mark-paid --ref-code YOURNAME-LEAD-000001 --paid-amount 50
```

### Send daily summary to Kia
```bash
python3 lead_bot.py daily-summary --email
```

### Send weekly summary to Kia
```bash
python3 lead_bot.py weekly-summary --email
```

## Fully automated daily email to Kia
1) Set SMTP env vars:
```bash
export SMTP_HOST="smtp.yourprovider.com"
export SMTP_PORT="587"
export SMTP_USER="your-sender@example.com"
export SMTP_PASS="YOUR_APP_PASSWORD"
export SMTP_FROM="your-sender@example.com"
```

2) Add cron (every day at 8:00 AM):
```bash
0 8 * * * cd /workspace/KIA- && /usr/bin/python3 lead_bot.py --db leadbot.db daily-summary --email
```

## Contacts used by bot
- Kia Email: `KIACONWELL@PRIMERICA.COM`
- Kia Website: `https://livemore.net/o/kia_conwell`

## Compliance note
Use only platform-approved, opt-in outreach. This tool does not perform blind spam posting.
