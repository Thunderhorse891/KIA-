# RunLeadBot.ps1
# Right-click -> "Run with PowerShell"
# Scrapes Reddit + Craigslist for home/auto insurance shoppers.
# Saves leads silently until 50 are collected, then sends ONE email to Kia.
# To stop at any time: press Ctrl+C

$ErrorActionPreference = "Stop"
$botFolder = Join-Path ([Environment]::GetFolderPath("Desktop")) "LeadBot"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   ERIN'S INSURANCE LEAD BOT" -ForegroundColor Cyan
Write-Host "   Reddit + Craigslist  ->  Emails Kia" -ForegroundColor Cyan
Write-Host "   (Press Ctrl+C to stop at any time)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Create folder ────────────────────────────────────────────────────────
if (-not (Test-Path $botFolder)) {
    New-Item -ItemType Directory -Path $botFolder | Out-Null
    Write-Host "Created folder: $botFolder" -ForegroundColor Gray
}

# ── 2. Write lead_bot.py ────────────────────────────────────────────────────
$pythonScript = @'
#!/usr/bin/env python3
"""
Insurance Lead Bot
- Scrapes Reddit + Craigslist for people shopping for auto/home insurance
- Filters out GA, FL, NY (states where partner is not licensed)
- Filters out health/life/flood/etc -- only auto and home/renters
- Filters out complainers -- must show actual buying intent
- Accumulates leads silently; sends ONE batch digest email when 50+ are ready
- Read-only -- never posts anywhere
"""

from __future__ import annotations
import argparse, datetime as dt, os, re, smtplib, sqlite3, textwrap
import time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Optional

DB_PATH           = os.getenv("LEADBOT_DB",         "leadbot.db")
PARTNER_EMAIL     = os.getenv("PARTNER_EMAIL",       "kiaconwell@gmail.com")
PARTNER_WEBSITE   = "https://livemore.net/o/kia_conwell"
DEFAULT_REF_OWNER = os.getenv("LEADBOT_REF_OWNER",   "ERIN")
DEFAULT_REPORT_TO = os.getenv("LEADBOT_REPORT_TO",   "erinswyrick85@gmail.com")
DEFAULT_FEE_AMOUNT = float(os.getenv("LEADBOT_DEFAULT_FEE", "50"))
BATCH_THRESHOLD   = int(os.getenv("LEADBOT_BATCH_SIZE", "50"))

# States where Kia is NOT licensed -- skip these leads
EXCLUDED_STATE_TERMS = [
    "georgia"," ga "," ga,","(ga)","atlanta","savannah","augusta","macon",
    "florida"," fl "," fl,","(fl)","miami","orlando","tampa","jacksonville",
    "fort lauderdale","tallahassee","gainesville","pensacola",
    "new york"," ny "," ny,","(ny)","nyc","manhattan","brooklyn",
    "bronx","queens","staten island","buffalo","rochester","yonkers",
]

TARGET_INSURANCE = [
    "auto insurance","car insurance","vehicle insurance","truck insurance",
    "home insurance","homeowners insurance","homeowner insurance",
    "renters insurance","house insurance","property insurance",
    "condo insurance","bundle","bundl",
]

NON_TARGET_INSURANCE = [
    "health insurance","medical insurance","life insurance","term life",
    "whole life","dental insurance","vision insurance","pet insurance",
    "travel insurance","flood insurance","earthquake insurance",
    "commercial insurance","business insurance","workers comp",
    "disability insurance","malpractice","fire insurance",
]

BUYING_INTENT = [
    "looking for","shopping for","shopping around","need insurance",
    "want insurance","switching","switch from","getting quotes",
    "getting a quote","quote","compare","comparison","recommend",
    "best insurance","cheapest","affordable","help me find",
    "first time","new policy","new home","just bought","just purchased",
    "moving to","just moved","shop around","options for","suggestions",
    "advice on","which insurance","what insurance","who do you use",
    "who to use","any recommendations","need help","need advice",
    "how do i","how to get","where to get","best rate","best price",
    "save on","lower my","cheaper option",
]

COMPLAINT_ONLY = [
    "claim was denied","denied my claim","they won't pay","they wont pay",
    "bad experience with","avoid this company","worst insurance company",
    "insurance is a scam","my agent screwed","hate my insurance company",
]

INSURANCE_SUBREDDITS = [
    "insurance","personalfinance","homeowners","FirstTimeHomeBuyer",
    "frugal","homebuying","AutoInsurance","povertyfinance",
    "askcarsales","RealEstate",
]

INSURANCE_KEYWORDS = [
    "auto insurance quote","car insurance quote",
    "home insurance quote","homeowners insurance quote",
    "looking for car insurance","looking for home insurance",
    "need auto insurance","need home insurance",
    "switching car insurance","switching home insurance",
    "bundle auto home","renters insurance","shop around insurance",
    "compare car insurance","compare home insurance",
]

# Craigslist cities in states where Kia IS licensed
CRAIGSLIST_CITIES = [
    "chicago","losangeles","houston","dallas","phoenix",
    "philadelphia","seattle","denver","boston","detroit",
    "minneapolis","portland","lasvegas","sandiego","charlotte",
    "nashville","austin","columbus","indianapolis","memphis",
]

CRAIGSLIST_QUERIES = [
    "auto insurance quote","home insurance quote","car insurance quote",
]

@dataclass
class Referral:
    source: str; name: str; email: str; question: str; tags: str
    body: str = field(default="")

class ReferralBot:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _column_exists(self, conn, column):
        return any(r[1] == column for r in conn.execute("PRAGMA table_info(leads)").fetchall())

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                source TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL,
                question TEXT NOT NULL, body TEXT, tags TEXT,
                ref_code TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'referred',
                sale_amount REAL, sold_at TEXT, invoice_amount REAL,
                invoice_sent_at TEXT, invoice_paid INTEGER NOT NULL DEFAULT 0,
                invoice_paid_at TEXT, paid_amount REAL, post_url TEXT,
                notified_at TEXT)""")
            for ddl in [
                "ALTER TABLE leads ADD COLUMN body TEXT",
                "ALTER TABLE leads ADD COLUMN invoice_amount REAL",
                "ALTER TABLE leads ADD COLUMN invoice_sent_at TEXT",
                "ALTER TABLE leads ADD COLUMN invoice_paid INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE leads ADD COLUMN invoice_paid_at TEXT",
                "ALTER TABLE leads ADD COLUMN paid_amount REAL",
                "ALTER TABLE leads ADD COLUMN post_url TEXT",
                "ALTER TABLE leads ADD COLUMN notified_at TEXT",
            ]:
                col = ddl.split("ADD COLUMN ",1)[1].split()[0]
                if not self._column_exists(conn, col):
                    conn.execute(ddl)

    def _build_ref_code(self, rid, owner=None):
        owner = owner or DEFAULT_REF_OWNER
        return f"{re.sub(r'[^A-Z0-9]','',owner.upper())}-REF-{rid:06d}"

    def add_referral(self, referral, owner=None, post_url=""):
        owner = owner or DEFAULT_REF_OWNER
        now = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO leads(created_at,source,name,email,question,body,tags,"
                "ref_code,status,post_url) VALUES(?,?,?,?,?,?,?,?,'referred',?)",
                (now,referral.source,referral.name,referral.email,
                 referral.question,referral.body,referral.tags,"PENDING",post_url))
            rid = cur.lastrowid
            conn.execute("UPDATE leads SET ref_code=? WHERE id=?",
                         (self._build_ref_code(rid,owner), rid))
        return rid

    def referral_exists(self, name, question):
        with self._connect() as conn:
            return conn.execute(
                "SELECT id FROM leads WHERE name=? AND question=?",(name,question)
            ).fetchone() is not None

    def get_referral(self, rid):
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            r = conn.execute("SELECT * FROM leads WHERE id=?",(rid,)).fetchone()
            return dict(r) if r else None

    def get_referral_by_code(self, code):
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            r = conn.execute("SELECT * FROM leads WHERE ref_code=?",(code,)).fetchone()
            return dict(r) if r else None

    def count_unnotified(self):
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM leads WHERE notified_at IS NULL"
            ).fetchone()[0]

    def get_unnotified_referrals(self):
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM leads WHERE notified_at IS NULL ORDER BY created_at ASC"
            ).fetchall()]

    def mark_notified(self, ids):
        now = dt.datetime.utcnow().isoformat()
        placeholders = ",".join("?"*len(ids))
        with self._connect() as conn:
            conn.execute(
                f"UPDATE leads SET notified_at=? WHERE id IN ({placeholders})",
                [now]+ids)

    def mark_partner_closed(self, code, sale_amount, fee_amount):
        now = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE leads SET status='partner_closed',sale_amount=?,sold_at=?,"
                "invoice_amount=?,invoice_sent_at=? WHERE ref_code=?",
                (sale_amount,now,fee_amount,now,code))
            return cur.rowcount > 0

    def mark_finder_fee_paid(self, code, paid_amount):
        now = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE leads SET invoice_paid=1,invoice_paid_at=?,paid_amount=?,"
                "status='fee_paid' WHERE ref_code=?", (now,paid_amount,code))
            return cur.rowcount > 0

    def referral_summary(self, days=7):
        since = (dt.datetime.utcnow()-dt.timedelta(days=days)).isoformat()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            refs = conn.execute(
                "SELECT * FROM leads WHERE created_at>=? ORDER BY created_at DESC",(since,)
            ).fetchall()
        total  = len(refs)
        closed = sum(1 for r in refs if r["status"] in ("partner_closed","fee_paid"))
        paid   = sum(1 for r in refs if r["invoice_paid"]==1)
        rows   = [f"  {r['ref_code']} | {r['name']} | {r['status']} | paid={bool(r['invoice_paid'])}"
                  for r in refs]
        return (f"Summary ({days}d) -- {dt.datetime.utcnow().isoformat()} UTC\n"
                f"Total:{total}  Closed:{closed}  Fees paid:{paid}\n\n"
                +("\n".join(rows) if rows else "No referrals in period"))

# ── Filters ──────────────────────────────────────────────────────────────────

def _excluded_state(text):
    t = " "+text.lower()+" "
    return any(s in t for s in EXCLUDED_STATE_TERMS)

def _target_insurance(title, body):
    combined = (title+" "+body).lower()
    if not any(t in combined for t in TARGET_INSURANCE):
        return False
    tl = title.lower()
    if sum(1 for t in NON_TARGET_INSURANCE if t in tl) > 0 and \
       sum(1 for t in TARGET_INSURANCE if t in tl) == 0:
        return False
    return True

def _buying_intent(title, body):
    combined = (title+" "+body).lower()
    has_intent = any(t in combined for t in BUYING_INTENT)
    pure_complaint = any(t in combined for t in COMPLAINT_ONLY) and not has_intent
    return has_intent and not pure_complaint

def _qualifies(title, body):
    return (not _excluded_state(title+" "+body) and
            _target_insurance(title, body) and
            _buying_intent(title, body))

def _tag(title, body):
    c = (title+" "+body).lower()
    tags = []
    if any(w in c for w in ["auto","car","vehicle","truck","motorcycle"]):
        tags.append("auto-insurance")
    if any(w in c for w in ["home","house","homeowner","property","renters","condo"]):
        tags.append("home-insurance")
    return ",".join(tags) if tags else "insurance"

# ── Reddit scraper (RSS -- no API key needed) ─────────────────────────────────

_ATOM = "http://www.w3.org/2005/Atom"
def _atom(t): return f"{{{_ATOM}}}{t}"

def scrape_reddit_leads(days=30):
    cutoff = dt.datetime.utcnow()-dt.timedelta(days=days)
    raw = []
    for sub in INSURANCE_SUBREDDITS:
        url = f"https://www.reddit.com/r/{sub}/new.rss?limit=100"
        try:
            xml_text = _fetch_text(url)
            root = ET.fromstring(xml_text)
            for entry in root.findall(_atom("entry")):
                te = entry.find(_atom("title"))
                le = entry.find(_atom("link"))
                ce = entry.find(_atom("content"))
                ae = entry.find(f"{_atom('author')}/{_atom('name')}")
                ue = entry.find(_atom("updated"))
                title  = (te.text or "").strip() if te is not None else ""
                link   = le.get("href","") if le is not None else ""
                body   = re.sub(r"<[^>]+>"," ",(ce.text or "") if ce is not None else "").strip()[:600]
                author = ((ae.text or "").replace("/u/","").strip()) if ae is not None else "unknown"
                upd    = (ue.text or "") if ue is not None else ""
                try:
                    pdt = dt.datetime.fromisoformat(upd.replace("Z","+00:00"))
                    if pdt.replace(tzinfo=None) < cutoff: continue
                except Exception: pass
                if not title: continue
                if author in ("[deleted]","AutoModerator",""): continue
                if any(s in (title+body).lower() for s in
                       ["agent here","dm me for","i'm an agent","i am an agent"]): continue
                if not _qualifies(title, body): continue
                raw.append({
                    "source": f"reddit:r/{sub}", "name": author,
                    "email": f"reddit:u/{author}", "question": title[:500],
                    "body": body, "tags": _tag(title,body), "url": link,
                })
            time.sleep(3.0)
        except Exception as e:
            print(f"  [Reddit] r/{sub}: {e}")
    seen = set(); unique = []
    for l in raw:
        k = (l["name"],l["question"])
        if k not in seen: seen.add(k); unique.append(l)
    return unique

# ── Craigslist scraper ────────────────────────────────────────────────────────

def _fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent":"InsuranceLeadBot/2.0 (contact kiaconwell@gmail.com)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")

def scrape_craigslist_leads():
    raw = []
    for city in CRAIGSLIST_CITIES:
        for query in CRAIGSLIST_QUERIES:
            url = (f"https://{city}.craigslist.org/search/fns"
                   f"?query={urllib.parse.quote(query)}&sort=date&format=rss")
            try:
                root = ET.fromstring(_fetch_text(url))
                channel = root.find("channel")
                if channel is None: continue
                for item in channel.findall("item"):
                    te = item.find("title"); le = item.find("link"); de = item.find("description")
                    title = (te.text or "") if te is not None else ""
                    link  = (le.text or "") if le is not None else ""
                    desc  = re.sub(r"<[^>]+>"," ",(de.text or "") if de is not None else "").strip()[:600]
                    if not title.strip(): continue
                    if not _qualifies(title, desc): continue
                    raw.append({
                        "source": f"craigslist:{city}", "name": f"cl-{city}-anon",
                        "email": f"craigslist:{link}", "question": title[:500],
                        "body": desc, "tags": _tag(title,desc), "url": link,
                    })
                time.sleep(1.0)
            except Exception as e:
                print(f"  [Craigslist] {city} '{query}': {e}")
    seen = set(); unique = []
    for l in raw:
        k = (l["name"],l["question"])
        if k not in seen: seen.add(k); unique.append(l)
    return unique

# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(to_email, subject, body):
    host  = os.getenv("SMTP_HOST"); port = int(os.getenv("SMTP_PORT","587"))
    user  = os.getenv("SMTP_USER"); pw   = os.getenv("SMTP_PASS")
    frm   = os.getenv("SMTP_FROM", user or "leadbot@localhost")
    if not host or not user or not pw:
        raise RuntimeError("SMTP_HOST, SMTP_USER, SMTP_PASS required.")
    msg = EmailMessage()
    msg["From"] = frm; msg["To"] = to_email; msg["Subject"] = subject
    msg.set_content(body, charset="utf-8")
    with smtplib.SMTP(host, port) as s:
        s.starttls(); s.login(user, pw); s.send_message(msg)

def format_batch_digest(referrals):
    today = dt.datetime.utcnow().strftime("%B %d, %Y")
    lines = [
        "Hi Kia,","",
        f"Here are {len(referrals)} new insurance leads as of {today}.",
        "Each person is actively shopping for auto or home insurance.","",
        f"Your quote link: {PARTNER_WEBSITE}","",
        "When a lead signs a contract with you, reply with their referral",
        "code so Erin can track the finder's fee.","",
        "="*60,
    ]
    for i, ref in enumerate(referrals, 1):
        e = ref["email"]
        contact = (f"Reddit {e.replace('reddit:','')}" if e.startswith("reddit:") else
                   "See post link below" if e.startswith("craigslist:") else e)
        lines += ["", f"LEAD #{i}  --  {ref['ref_code']}",
                  f"  Source     : {ref['source']}",
                  f"  Username   : {ref['name']}",
                  f"  Contact    : {contact}",
                  f"  Tags       : {ref.get('tags','')}",
                  f"  Their Post : {ref['question']}"]
        if ref.get("body"):  lines.append(f"  Details    : {ref['body'][:300]}")
        if ref.get("post_url"): lines.append(f"  Link       : {ref['post_url']}")
        lines.append("  "+"-"*56)
    lines += ["","="*60,f"Total: {len(referrals)} leads","",
              "Questions? Contact Erin: erinswyrick85@gmail.com"]
    return "\n".join(lines)

# ── Main scrape logic ─────────────────────────────────────────────────────────

def main():
    db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leadbot.db")
    os.environ.setdefault("LEADBOT_DB", db_file)

    force_send = "--force-send" in __import__("sys").argv

    print(f"Scraping Reddit (last 30 days)...")
    reddit_leads = scrape_reddit_leads()
    print(f"  Reddit: {len(reddit_leads)} qualifying posts found.")

    print("Scraping Craigslist...")
    cl_leads = scrape_craigslist_leads()
    print(f"  Craigslist: {len(cl_leads)} qualifying posts found.")

    bot = ReferralBot(db_file)
    new_count = 0; skipped = 0

    for ld in reddit_leads + cl_leads:
        if bot.referral_exists(ld["name"], ld["question"]):
            skipped += 1; continue
        rid = bot.add_referral(
            Referral(source=ld["source"],name=ld["name"],email=ld["email"],
                     question=ld["question"],body=ld.get("body",""),tags=ld["tags"]),
            post_url=ld.get("url",""))
        with bot._connect() as conn:
            conn.execute("UPDATE leads SET post_url=?,body=? WHERE id=?",
                         (ld.get("url",""),ld.get("body",""),rid))
        new_count += 1

    print(f"\nSaved {new_count} new leads ({skipped} duplicates skipped).")

    unnotified_count = bot.count_unnotified()
    needed = max(0, BATCH_THRESHOLD - unnotified_count)
    print(f"Leads waiting to send to Kia: {unnotified_count} / {BATCH_THRESHOLD}")

    if unnotified_count < BATCH_THRESHOLD and not force_send:
        print(f"Need {needed} more lead(s) before sending batch email.")
        print("Run again to keep collecting. Use --force-send to send now anyway.")
        return

    unnotified = bot.get_unnotified_referrals()
    subject = f"{len(unnotified)} New Insurance Leads -- {dt.datetime.utcnow().strftime('%b %d, %Y')}"
    digest  = format_batch_digest(unnotified)

    try:
        send_email(PARTNER_EMAIL, subject, digest)
        bot.mark_notified([r["id"] for r in unnotified])
        print(f"\nSUCCESS: Batch of {len(unnotified)} leads emailed to {PARTNER_EMAIL}.")
    except Exception as e:
        print(f"\nERROR sending email: {e}")

if __name__ == "__main__":
    main()
'@

$pythonFile = "$botFolder\lead_bot.py"
[System.IO.File]::WriteAllText($pythonFile, $pythonScript, [System.Text.Encoding]::UTF8)
Write-Host "Script saved: $pythonFile" -ForegroundColor Gray

# ── 3. Gmail SMTP credentials ────────────────────────────────────────────────
$env:SMTP_HOST  = "smtp.gmail.com"
$env:SMTP_PORT  = "587"
$env:SMTP_USER  = "erinswyrick85@gmail.com"
$env:SMTP_PASS  = "vfmqmvcclevvvmkl"
$env:SMTP_FROM  = "erinswyrick85@gmail.com"
$env:LEADBOT_DB = "$botFolder\leadbot.db"

Write-Host "Gmail credentials set." -ForegroundColor Gray
Write-Host ""
Write-Host "Scraping Reddit + Craigslist -- this takes a few minutes..." -ForegroundColor Yellow
Write-Host "(Ctrl+C to stop at any time)" -ForegroundColor Gray
Write-Host ""

# ── 4. Run the bot ───────────────────────────────────────────────────────────
# Pass --force-send as argument if you want to email before hitting 50 leads:
#   python $pythonFile --force-send
python $pythonFile
$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "Done!" -ForegroundColor Green
    Write-Host "Leads are saved to: $botFolder\leadbot.db" -ForegroundColor Gray
    Write-Host "Run again anytime to collect more -- email fires at 50 leads." -ForegroundColor Gray
} else {
    Write-Host "Something went wrong (exit code $exitCode). Check errors above." -ForegroundColor Red
}

Write-Host ""
Write-Host "Press Enter to close..."
Read-Host
