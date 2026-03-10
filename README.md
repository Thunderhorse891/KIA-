# Kia Lead Generator Bot (Compliant)

## Is this ready for full production?
**Almost**. It is production-capable for workflow automation, but you should complete this checklist first:

1. Configure a reliable SMTP provider and secrets manager for email credentials.
2. Put `leadbot.db` on durable storage and schedule backups.
3. Add access controls (who can run `mark-paid`/`mark-sold`).
4. Review all outreach channels for platform terms + licensing compliance.
5. Run this under a process scheduler (cron/GitHub Actions/server job).

## What it does

- Stores leads in SQLite with unique attribution code (`YOURTAG-LEAD-000123`)
- Sends prospects to `KIACONWELL@PRIMERICA.COM` with attribution reference
- Marks converted leads as sold and creates a $50 invoice message
- Tracks whether the referral invoice has been paid (`mark-paid`)
- Generates and optionally emails a weekly lead summary (`weekly-summary --email`)

## How to run it

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

### 2) Mark that Kia made a sale (creates invoice text)
```bash
python3 lead_bot.py mark-sold --ref-code YOURNAME-LEAD-000001 --sale-amount 1200 --invoice-amount 50
```

### 3) Track ones that pay you
When Kia pays the referral fee:
```bash
python3 lead_bot.py mark-paid --ref-code YOURNAME-LEAD-000001 --paid-amount 50
```

### 4) Send him a weekly email of leads
```bash
python3 lead_bot.py weekly-summary --days 7 --email
```

## SMTP setup (required for live emails)

Set environment variables:
- `SMTP_HOST`
- `SMTP_PORT` (default `587`)
- `SMTP_USER`
- `SMTP_PASS`
- `SMTP_FROM` (optional)

## Automate weekly send (cron)
Run every Monday at 8:00 AM:
```bash
0 8 * * 1 cd /workspace/KIA- && /usr/bin/python3 lead_bot.py weekly-summary --db leadbot.db --days 7 --email
```

## Compliance note
This tool is designed for compliant lead management and human-reviewed outreach, not blind spam posting.
