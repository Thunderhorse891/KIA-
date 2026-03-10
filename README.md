# Referral Finder's-Fee Tracker (Partner Customer Tracking)

**Source-of-truth product framing:**
> This bot tracks referral customers I send to my friend, records when they become his customer, and tracks whether I received my finder’s fee.

## What this bot tracks
This is **not** your personal sales CRM.
This is a **referral / finder’s-fee tracker** for prospects you send to your friend (partner).

Workflow:
1. You refer a prospect to your friend.
2. Bot stores source + referral code.
3. Your friend confirms whether they became his customer.
4. Bot records partner-closed event.
5. Bot tracks expected finder’s fee and whether paid/unpaid.
6. Bot sends weekly referral summaries to you.

## Default business assumptions in this repo
- Channels: Facebook groups, Reddit, referrals, web form, warm DMs.
- Data entry: Erin only (for now).
- `mark-partner-closed` timing: when friend confirms they became his customer.
- `mark-finders-fee-paid` timing: when your finder’s fee is actually received.
- Payment methods: Zelle, Cash App, PayPal.
- Invoice terms: Net 7.
- Follow-up schedule:
  - Day 1 invoice
  - Day 7 reminder
  - Day 14 reminder
  - Day 21 final reminder
- Runtime now: laptop.
- Future runtime: VPS/server.

## Outlook SMTP configuration (recommended)
Use Outlook SMTP values:

```bash
export SMTP_HOST="smtp.office365.com"
export SMTP_PORT="587"
export SMTP_USER="Erin067841@outlook.com"
export SMTP_PASS="OUTLOOK_APP_PASSWORD"
export SMTP_FROM="Erin067841@outlook.com"
export LEADBOT_REPORT_TO="Erin067841@outlook.com"
```

**Important:** `SMTP_PASS` must be an Outlook **app password**, not your normal Outlook login password.

## CLI commands

### 1) Add a referred prospect
```bash
python3 lead_bot.py add-referral \
  --source "facebook:group:atlanta-finance" \
  --name "Prospect Name" \
  --email "prospect@example.com" \
  --question "Need life insurance options" \
  --tags "term-life" \
  --owner "ERIN" \
  --notify-partner
```

### 2) Bulk import referred prospects
CSV columns required: `source,name,email,question,tags`

```bash
python3 lead_bot.py bulk-import --csv-file referrals.csv --owner ERIN
```

### 3) Mark customer closed by partner
```bash
python3 lead_bot.py mark-partner-closed \
  --ref-code ERIN-REF-000001 \
  --sale-amount 1200 \
  --finders-fee-amount 50 \
  --send-invoice
```

### 4) Mark finder’s fee paid
```bash
python3 lead_bot.py mark-finders-fee-paid --ref-code ERIN-REF-000001 --paid-amount 50
```

### 5) Run weekly referral summary
```bash
python3 lead_bot.py weekly-summary --days 7
```

### 6) Email weekly referral summary to yourself
```bash
python3 lead_bot.py weekly-summary --days 7 --email --to Erin067841@outlook.com
```

## Fully automated weekly summary to yourself
Run every Monday at 8:00 AM:

```bash
0 8 * * 1 cd /workspace/KIA- && /usr/bin/python3 lead_bot.py --db leadbot.db weekly-summary --days 7 --email --to Erin067841@outlook.com
```

## Backward compatibility
Legacy commands still work (`add`, `mark-sold`, `mark-paid`) but are now labeled as legacy aliases.

## Partner contact destination
- Partner Email: `KIACONWELL@PRIMERICA.COM`
- Partner Website: `https://livemore.net/o/kia_conwell`

## Compliance note
Use only platform-approved outreach and opt-in referrals. This tool does not perform blind spam posting.
