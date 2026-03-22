# RunLeadBot.ps1
# Paste this entire script into PowerShell to install everything and run the lead bot.
# It will scrape Reddit for home/auto insurance leads and email each one to Kia automatically.

$ErrorActionPreference = "Stop"
$desktop = [Environment]::GetFolderPath("Desktop")
$botFolder = "$desktop\LeadBot"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   ERIN'S INSURANCE LEAD BOT" -ForegroundColor Cyan
Write-Host "   Scraping Reddit for leads -> Emailing Kia" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Create LeadBot folder on Desktop ─────────────────────────────────────
if (-not (Test-Path $botFolder)) {
    New-Item -ItemType Directory -Path $botFolder | Out-Null
    Write-Host "Created folder: $botFolder" -ForegroundColor Gray
}

# ── 2. Write lead_bot.py into the folder ────────────────────────────────────
$pythonScript = @'
#!/usr/bin/env python3
"""Referral / finder's-fee tracker for prospects sent to a partner."""

from __future__ import annotations
import argparse, csv, datetime as dt, json, os, re, smtplib, sqlite3, textwrap, time, urllib.parse, urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

DB_PATH = os.getenv("LEADBOT_DB", "leadbot.db")
PARTNER_EMAIL = os.getenv("PARTNER_EMAIL", "kiaconwell@gmail.com")
PARTNER_WEBSITE = "https://livemore.net/o/kia_conwell"
DEFAULT_REF_OWNER = os.getenv("LEADBOT_REF_OWNER", "ERIN")
DEFAULT_REPORT_TO = os.getenv("LEADBOT_REPORT_TO", "erinswyrick85@gmail.com")
DEFAULT_FEE_AMOUNT = float(os.getenv("LEADBOT_DEFAULT_FEE", "50"))

PARTNER_CONTEXT = textwrap.dedent("""
    Kia Conwell is a licensed insurance agent helping families protect their homes,
    cars, and loved ones. She provides personalized quotes for:
      - Auto / car insurance
      - Home / homeowners insurance
      - Bundled auto + home discounts
    Contact Kia for a free quote: kiaconwell@gmail.com
    Website: https://livemore.net/o/kia_conwell
""").strip()

INSURANCE_SUBREDDITS = ["insurance","personalfinance","homeowners","FirstTimeHomeBuyer","frugal","homebuying","AutoInsurance"]
INSURANCE_KEYWORDS = ["auto insurance quote","car insurance quote","home insurance quote","homeowners insurance quote","looking for car insurance","looking for home insurance","need auto insurance","need home insurance","switching car insurance","switching home insurance","cheaper car insurance","cheaper home insurance","bundle auto home"]
MIN_POST_SCORE = 1

@dataclass
class Referral:
    source: str
    name: str
    email: str
    question: str
    tags: str

Lead = Referral

class ReferralBot:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _column_exists(self, conn, column):
        rows = conn.execute("PRAGMA table_info(leads)").fetchall()
        return any(r[1] == column for r in rows)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                source TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL,
                question TEXT NOT NULL, tags TEXT, ref_code TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'referred', sale_amount REAL, sold_at TEXT,
                invoice_amount REAL, invoice_sent_at TEXT,
                invoice_paid INTEGER NOT NULL DEFAULT 0, invoice_paid_at TEXT,
                paid_amount REAL, post_url TEXT)""")
            for ddl in ["ALTER TABLE leads ADD COLUMN invoice_amount REAL","ALTER TABLE leads ADD COLUMN invoice_sent_at TEXT","ALTER TABLE leads ADD COLUMN invoice_paid INTEGER NOT NULL DEFAULT 0","ALTER TABLE leads ADD COLUMN invoice_paid_at TEXT","ALTER TABLE leads ADD COLUMN paid_amount REAL","ALTER TABLE leads ADD COLUMN post_url TEXT"]:
                col = ddl.split("ADD COLUMN ", 1)[1].split()[0]
                if not self._column_exists(conn, col):
                    conn.execute(ddl)

    def _build_ref_code(self, referral_id, owner=DEFAULT_REF_OWNER):
        clean_owner = re.sub(r"[^A-Z0-9]", "", owner.upper())
        return f"{clean_owner}-REF-{referral_id:06d}"

    def add_referral(self, referral, owner=DEFAULT_REF_OWNER, post_url=""):
        created_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute("INSERT INTO leads(created_at,source,name,email,question,tags,ref_code,status,post_url) VALUES (?,?,?,?,?,?,?,'referred',?)",
                (created_at, referral.source, referral.name, referral.email, referral.question, referral.tags, "PENDING", post_url))
            referral_id = cur.lastrowid
            ref_code = self._build_ref_code(referral_id, owner)
            conn.execute("UPDATE leads SET ref_code=? WHERE id=?", (ref_code, referral_id))
        return referral_id

    def referral_exists(self, name, question):
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM leads WHERE name=? AND question=?", (name, question)).fetchone()
            return row is not None

    def get_referral(self, referral_id):
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM leads WHERE id=?", (referral_id,)).fetchone()
            return dict(row) if row else None

def draft_partner_intro(referral):
    post_line = f"\nOriginal post: {referral['post_url']}" if referral.get("post_url") else ""
    if referral["email"].startswith("reddit:"):
        username = referral["email"].replace("reddit:", "")
        contact_line = f"Reddit {username}{post_line}"
    else:
        contact_line = referral["email"]
    return textwrap.dedent(f"""
        Hi Kia,

        New insurance lead for you — this person is actively looking for
        auto or home insurance and could be a great fit for a free quote.

        Name / Username : {referral['name']}
        Contact         : {contact_line}
        Source          : {referral['source']}
        Referral Code   : {referral['ref_code']}
        Their Question  : {referral['question']}
        Tags            : {referral.get('tags', '')}

        {PARTNER_CONTEXT}

        Please follow up and let me know if they sign a contract so I can
        record the finder's fee. Reference code: {referral['ref_code']}
    """).strip()

def send_email(to_email, subject, body):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    from_email = os.getenv("SMTP_FROM", user or "leadbot@localhost")
    if not host or not user or not password:
        raise RuntimeError("SMTP_HOST, SMTP_USER, SMTP_PASS are required.")
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)

def _reddit_fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "InsuranceLeadBot/1.0 (contact kiaconwell@gmail.com)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _is_legit_post(post):
    author = post.get("author", "")
    title = (post.get("title") or "").lower()
    body = (post.get("selftext") or "").lower()
    if author in ("[deleted]", "AutoModerator", ""):
        return False
    if post.get("removed_by_category") or post.get("stickied"):
        return False
    if len(title.strip()) < 10:
        return False
    ad_signals = ["agent here", "dm me", "i'm an agent", "i am an agent", "shop with me"]
    if any(s in title or s in body for s in ad_signals):
        return False
    insurance_words = ["insurance","insure","premium","deductible","coverage","quote","policy","bundle","rate"]
    if not any(w in title + " " + body for w in insurance_words):
        return False
    return True

def scrape_reddit_leads(keywords=None, subreddits=None, limit=25, days=30):
    if keywords is None: keywords = INSURANCE_KEYWORDS
    if subreddits is None: subreddits = INSURANCE_SUBREDDITS
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    raw_leads = []
    for subreddit in subreddits:
        for keyword in keywords:
            encoded = urllib.parse.quote(keyword)
            url = f"https://www.reddit.com/r/{subreddit}/search.json?q={encoded}&restrict_sr=1&sort=new&limit={limit}&t=month"
            try:
                data = _reddit_fetch(url)
                for pw in data.get("data", {}).get("children", []):
                    p = pw.get("data", {})
                    if dt.datetime.utcfromtimestamp(p.get("created_utc", 0)) < cutoff: continue
                    if p.get("score", 0) < MIN_POST_SCORE: continue
                    if not _is_legit_post(p): continue
                    combined = ((p.get("title") or "") + " " + (p.get("selftext") or "")).lower()
                    tags_list = []
                    if any(w in combined for w in ["auto","car","vehicle","truck","motorcycle"]): tags_list.append("auto-insurance")
                    if any(w in combined for w in ["home","house","homeowner","property","renters"]): tags_list.append("home-insurance")
                    if not tags_list: tags_list.append("insurance")
                    raw_leads.append({"source": f"reddit:r/{subreddit}", "name": p["author"], "email": f"reddit:u/{p['author']}", "question": (p.get("title") or "")[:500], "tags": ",".join(tags_list), "url": f"https://reddit.com{p.get('permalink', '')}", "body": (p.get("selftext") or "")[:400]})
                time.sleep(1.5)
            except Exception as exc:
                print(f"  Warning: could not scrape r/{subreddit} for '{keyword}': {exc}")
    seen = set()
    unique = []
    for lead in raw_leads:
        key = (lead["name"], lead["question"])
        if key not in seen:
            seen.add(key)
            unique.append(lead)
    return unique

def main():
    db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leadbot.db")
    os.environ.setdefault("LEADBOT_DB", db_file)
    print("Scraping Reddit for home/auto insurance leads (last 30 days)...")
    raw_leads = scrape_reddit_leads()
    if not raw_leads:
        print("No new leads found this time. Try again later.")
        return
    bot = ReferralBot(db_file)
    new_count = 0
    skipped_count = 0
    new_referrals = []
    for lead_data in raw_leads:
        if bot.referral_exists(lead_data["name"], lead_data["question"]):
            skipped_count += 1
            continue
        referral_id = bot.add_referral(Referral(source=lead_data["source"], name=lead_data["name"], email=lead_data["email"], question=lead_data["question"], tags=lead_data["tags"]), post_url=lead_data.get("url", ""))
        with bot._connect() as conn:
            conn.execute("UPDATE leads SET post_url=? WHERE id=?", (lead_data.get("url", ""), referral_id))
        referral = bot.get_referral(referral_id)
        referral["post_url"] = lead_data.get("url", "")
        new_referrals.append(referral)
        new_count += 1
    print(f"Found {len(raw_leads)} leads -> {new_count} new, {skipped_count} already sent to Kia before.")
    if not new_referrals:
        print("No new leads to send.")
        return
    errors = 0
    for referral in new_referrals:
        try:
            send_email(PARTNER_EMAIL, f"New Insurance Lead: {referral['name']} ({referral['ref_code']}) [{referral.get('tags', '')}]", draft_partner_intro(referral))
            print(f"  Emailed lead {referral['ref_code']} ({referral['name']}) to {PARTNER_EMAIL}")
        except Exception as exc:
            print(f"  FAILED to email {referral['ref_code']}: {exc}")
            errors += 1
    print("")
    if errors == 0:
        print(f"SUCCESS! All {new_count} new leads emailed to {PARTNER_EMAIL}")
    else:
        print(f"{new_count - errors}/{new_count} leads emailed. {errors} failed.")

if __name__ == "__main__":
    main()
'@

$pythonFile = "$botFolder\lead_bot.py"
$pythonScript | Out-File -FilePath $pythonFile -Encoding UTF8
Write-Host "Lead bot script saved to: $pythonFile" -ForegroundColor Gray

# ── 3. Set Gmail SMTP credentials ────────────────────────────────────────────
$env:SMTP_HOST = "smtp.gmail.com"
$env:SMTP_PORT = "587"
$env:SMTP_USER = "erinswyrick85@gmail.com"
$env:SMTP_PASS = "vfmqmvcclevvvmkl"
$env:SMTP_FROM = "erinswyrick85@gmail.com"
$env:LEADBOT_DB = "$botFolder\leadbot.db"

Write-Host "Gmail credentials loaded." -ForegroundColor Gray
Write-Host ""
Write-Host "Starting Reddit scrape — this may take a few minutes..." -ForegroundColor Yellow
Write-Host ""

# ── 4. Run the bot ───────────────────────────────────────────────────────────
try {
    python $pythonFile
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    $exitCode = 1
}

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "Done! Check above to see how many leads were emailed to Kia." -ForegroundColor Green
} else {
    Write-Host "Something went wrong. Check the error above." -ForegroundColor Red
}

Write-Host ""
Write-Host "Press Enter to close..."
Read-Host
