# Insurance Referral Lead Bot (KIA-)

Tracks insurance leads sent to Kia Conwell, records when they sign contracts,
and tracks finder's fees owed to you.

---

## How it works

1. **Scrape** — Bot searches Reddit for people actively asking about auto / home
   insurance and saves them as leads.
2. **Email** — Each new lead is emailed to `kiaconwell@gmail.com` so Kia can
   follow up directly.
3. **Track** — When Kia signs a contract with a referred lead you record it.
4. **Invoice** — Bot generates a finder's fee invoice and emails it to Kia.
5. **Summarize** — Weekly report emailed to you so you can see what's pending.

---

## Quick start

### 1. Set SMTP credentials (required for all email features)

```bash
export SMTP_HOST="smtp.office365.com"
export SMTP_PORT="587"
export SMTP_USER="Erin067841@outlook.com"
export SMTP_PASS="YOUR_OUTLOOK_APP_PASSWORD"
export SMTP_FROM="Erin067841@outlook.com"
export LEADBOT_REPORT_TO="Erin067841@outlook.com"
```

> `SMTP_PASS` must be an Outlook **app password** (not your regular login password).
> Create one at account.microsoft.com → Security → App passwords.

### 2. Scrape Reddit and email leads to Kia (main workflow)

```bash
python3 lead_bot.py web-scrape
```

This searches Reddit subreddits (`r/insurance`, `r/personalfinance`,
`r/homeowners`, etc.) for people asking about auto/home insurance,
saves them to the database, and emails each one to `kiaconwell@gmail.com`.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--days N` | 30 | Look back N days |
| `--limit N` | 25 | Max posts per keyword/subreddit |
| `--no-notify-partner` | off | Print leads instead of emailing |
| `--keywords a,b` | built-in | Comma-separated search terms |
| `--subreddits a,b` | built-in | Comma-separated subreddits |

Preview without emailing:
```bash
python3 lead_bot.py web-scrape --no-notify-partner
```

### 3. Add a lead manually

```bash
python3 lead_bot.py add-referral \
  --source "facebook:group:home-insurance" \
  --name "Jane Smith" \
  --email "jane@example.com" \
  --question "Looking for homeowners insurance quote in Georgia" \
  --tags "home-insurance" \
  --notify-partner
```

### 4. Record that Kia signed a contract (closed the lead)

```bash
python3 lead_bot.py mark-partner-closed \
  --ref-code ERIN-REF-000001 \
  --sale-amount 1200 \
  --finders-fee-amount 50 \
  --send-invoice
```

### 5. Record that you received your finder's fee

```bash
python3 lead_bot.py mark-finders-fee-paid --ref-code ERIN-REF-000001 --paid-amount 50
```

### 6. Email yourself a weekly summary

```bash
python3 lead_bot.py weekly-summary --days 7 --email --to Erin067841@outlook.com
```

---

## Automate with cron

Run the scraper every morning at 7 AM and email leads to Kia automatically:

```bash
# Scrape and email leads to Kia every day at 7:00 AM
0 7 * * * cd /workspace/KIA- && /usr/bin/python3 lead_bot.py web-scrape

# Email yourself a weekly summary every Monday at 8:00 AM
0 8 * * 1 cd /workspace/KIA- && /usr/bin/python3 lead_bot.py weekly-summary --days 7 --email --to Erin067841@outlook.com
```

---

## Partner contact

- **Name:** Kia Conwell
- **Email:** kiaconwell@gmail.com
- **Website:** https://livemore.net/o/kia_conwell
- **Products:** Auto insurance, home/homeowners insurance, bundled discounts

---

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LEADBOT_DB` | `leadbot.db` | SQLite database path |
| `LEADBOT_REF_OWNER` | `ERIN` | Prefix for referral codes |
| `LEADBOT_REPORT_TO` | `Erin067841@outlook.com` | Where weekly summary is sent |
| `LEADBOT_DEFAULT_FEE` | `50` | Default finder's fee ($) |
| `PARTNER_EMAIL` | `kiaconwell@gmail.com` | Partner email for leads / invoices |
| `SMTP_HOST` | required | SMTP server (e.g. smtp.office365.com) |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | required | Your email address |
| `SMTP_PASS` | required | App password |
| `SMTP_FROM` | `SMTP_USER` | From address |

---

## Compliance note

The scraper reads **publicly posted** Reddit threads. It does not send
unsolicited emails to prospects — it alerts Kia so she can reach out through
the platform where the person already posted. Use only opt-in and
platform-approved follow-up methods.
