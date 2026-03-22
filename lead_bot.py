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

import argparse
import datetime as dt
import json
import os
import re
import smtplib
import sqlite3
import textwrap
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH          = os.getenv("LEADBOT_DB",         "leadbot.db")
PARTNER_EMAIL    = os.getenv("PARTNER_EMAIL",       "kiaconwell@gmail.com")
PARTNER_WEBSITE  = "https://livemore.net/o/kia_conwell"
DEFAULT_REF_OWNER = os.getenv("LEADBOT_REF_OWNER",  "ERIN")
DEFAULT_REPORT_TO = os.getenv("LEADBOT_REPORT_TO",  "erinswyrick85@gmail.com")
DEFAULT_FEE_AMOUNT = float(os.getenv("LEADBOT_DEFAULT_FEE", "50"))
BATCH_THRESHOLD  = int(os.getenv("LEADBOT_BATCH_SIZE", "50"))

# ---------------------------------------------------------------------------
# Geographic filter -- Kia is not licensed in GA, FL, or NY
# ---------------------------------------------------------------------------

EXCLUDED_STATE_TERMS = [
    # Georgia
    "georgia", " ga ", " ga,", "(ga)", "atlanta", "savannah", "augusta", "macon",
    # Florida
    "florida", " fl ", " fl,", "(fl)", "miami", "orlando", "tampa", "jacksonville",
    "fort lauderdale", "tallahassee", "gainesville", "pensacola",
    # New York
    "new york", " ny ", " ny,", "(ny)", "nyc", "manhattan", "brooklyn",
    "bronx", "queens", "staten island", "buffalo", "rochester", "yonkers",
]

# ---------------------------------------------------------------------------
# Insurance-type filter -- auto and home/renters only
# ---------------------------------------------------------------------------

TARGET_INSURANCE = [
    "auto insurance", "car insurance", "vehicle insurance", "truck insurance",
    "home insurance", "homeowners insurance", "homeowner insurance",
    "renters insurance", "house insurance", "property insurance",
    "condo insurance", "bundle", "bundl",
]

NON_TARGET_INSURANCE = [
    "health insurance", "medical insurance", "life insurance", "term life",
    "whole life", "dental insurance", "vision insurance", "pet insurance",
    "travel insurance", "flood insurance", "earthquake insurance",
    "commercial insurance", "business insurance", "workers comp",
    "disability insurance", "malpractice", "fire insurance",
]

# ---------------------------------------------------------------------------
# Buying-intent filter -- shoppers only, not complainers
# ---------------------------------------------------------------------------

BUYING_INTENT = [
    "looking for", "shopping for", "shopping around", "need insurance",
    "want insurance", "switching", "switch from", "getting quotes",
    "getting a quote", "quote", "compare", "comparison", "recommend",
    "best insurance", "cheapest", "affordable", "help me find",
    "first time", "new policy", "new home", "just bought", "just purchased",
    "moving to", "just moved", "shop around", "options for", "suggestions",
    "advice on", "which insurance", "what insurance", "who do you use",
    "who to use", "any recommendations", "need help", "need advice",
    "how do i", "how to get", "where to get", "best rate", "best price",
    "save on", "lower my", "cheaper option",
]

COMPLAINT_ONLY = [
    "claim was denied", "denied my claim", "they won't pay", "they wont pay",
    "bad experience with", "avoid this company", "worst insurance company",
    "insurance is a scam", "my agent screwed", "hate my insurance company",
]

# ---------------------------------------------------------------------------
# Reddit config
# ---------------------------------------------------------------------------

INSURANCE_SUBREDDITS = [
    "insurance", "personalfinance", "homeowners", "FirstTimeHomeBuyer",
    "frugal", "homebuying", "AutoInsurance", "povertyfinance",
    "askcarsales", "RealEstate",
]

INSURANCE_KEYWORDS = [
    "auto insurance quote", "car insurance quote",
    "home insurance quote", "homeowners insurance quote",
    "looking for car insurance", "looking for home insurance",
    "need auto insurance", "need home insurance",
    "switching car insurance", "switching home insurance",
    "bundle auto home", "renters insurance", "shop around insurance",
    "compare car insurance", "compare home insurance",
]

MIN_POST_SCORE = 1

# ---------------------------------------------------------------------------
# Craigslist config -- cities in states where Kia IS licensed
# ---------------------------------------------------------------------------

CRAIGSLIST_CITIES = [
    "chicago", "losangeles", "houston", "dallas", "phoenix",
    "philadelphia", "seattle", "denver", "boston", "detroit",
    "minneapolis", "portland", "lasvegas", "sandiego", "charlotte",
    "nashville", "austin", "columbus", "indianapolis", "memphis",
]

CRAIGSLIST_QUERIES = [
    "auto insurance quote", "home insurance quote", "car insurance quote",
]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Referral:
    source:   str
    name:     str
    email:    str
    question: str
    tags:     str
    body:     str = field(default="")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class ReferralBot:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _column_exists(self, conn: sqlite3.Connection, column: str) -> bool:
        rows = conn.execute("PRAGMA table_info(leads)").fetchall()
        return any(r[1] == column for r in rows)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at      TEXT NOT NULL,
                    source          TEXT NOT NULL,
                    name            TEXT NOT NULL,
                    email           TEXT NOT NULL,
                    question        TEXT NOT NULL,
                    body            TEXT,
                    tags            TEXT,
                    ref_code        TEXT NOT NULL UNIQUE,
                    status          TEXT NOT NULL DEFAULT 'referred',
                    sale_amount     REAL,
                    sold_at         TEXT,
                    invoice_amount  REAL,
                    invoice_sent_at TEXT,
                    invoice_paid    INTEGER NOT NULL DEFAULT 0,
                    invoice_paid_at TEXT,
                    paid_amount     REAL,
                    post_url        TEXT,
                    notified_at     TEXT
                )
            """)
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
                col = ddl.split("ADD COLUMN ", 1)[1].split()[0]
                if not self._column_exists(conn, col):
                    conn.execute(ddl)

    def _build_ref_code(self, referral_id: int, owner: str = DEFAULT_REF_OWNER) -> str:
        clean = re.sub(r"[^A-Z0-9]", "", owner.upper())
        return f"{clean}-REF-{referral_id:06d}"

    def add_referral(self, referral: Referral, owner: str = DEFAULT_REF_OWNER,
                     post_url: str = "") -> int:
        created_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO leads
                   (created_at, source, name, email, question, body, tags,
                    ref_code, status, post_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'referred', ?)""",
                (created_at, referral.source, referral.name, referral.email,
                 referral.question, referral.body, referral.tags, "PENDING", post_url),
            )
            rid = cur.lastrowid
            ref_code = self._build_ref_code(rid, owner)
            conn.execute("UPDATE leads SET ref_code=? WHERE id=?", (ref_code, rid))
        return rid

    def referral_exists(self, name: str, question: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM leads WHERE name=? AND question=?", (name, question)
            ).fetchone()
            return row is not None

    def get_referral(self, referral_id: int) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM leads WHERE id=?", (referral_id,)).fetchone()
            return dict(row) if row else None

    def get_referral_by_code(self, ref_code: str) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM leads WHERE ref_code=?", (ref_code,)
            ).fetchone()
            return dict(row) if row else None

    def count_unnotified(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE notified_at IS NULL"
            ).fetchone()
            return row[0] if row else 0

    def get_unnotified_referrals(self) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM leads WHERE notified_at IS NULL ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_notified(self, referral_ids: list[int]) -> None:
        now = dt.datetime.utcnow().isoformat()
        placeholders = ",".join("?" * len(referral_ids))
        with self._connect() as conn:
            conn.execute(
                f"UPDATE leads SET notified_at=? WHERE id IN ({placeholders})",
                [now] + referral_ids,
            )

    def mark_partner_closed(self, ref_code: str, sale_amount: float,
                             finder_fee_amount: float) -> bool:
        sold_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE leads
                   SET status='partner_closed', sale_amount=?, sold_at=?,
                       invoice_amount=?, invoice_sent_at=?
                   WHERE ref_code=?""",
                (sale_amount, sold_at, finder_fee_amount, sold_at, ref_code),
            )
            return cur.rowcount > 0

    def mark_finder_fee_paid(self, ref_code: str, paid_amount: float) -> bool:
        paid_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE leads
                   SET invoice_paid=1, invoice_paid_at=?, paid_amount=?, status='fee_paid'
                   WHERE ref_code=?""",
                (paid_at, paid_amount, ref_code),
            )
            return cur.rowcount > 0

    def referral_summary(self, days: int = 7) -> str:
        since = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            referrals = conn.execute(
                "SELECT * FROM leads WHERE created_at >= ? ORDER BY created_at DESC",
                (since,),
            ).fetchall()
        total  = len(referrals)
        closed = sum(1 for r in referrals if r["status"] in ("partner_closed", "fee_paid"))
        paid   = sum(1 for r in referrals if r["invoice_paid"] == 1)
        rows   = [
            f"  {r['ref_code']} | {r['name']} | status={r['status']} "
            f"| fee_paid={bool(r['invoice_paid'])}"
            for r in referrals
        ]
        return (
            f"Referral Summary (last {days} days) -- "
            f"{dt.datetime.utcnow().isoformat()} UTC\n"
            f"Total: {total}  |  Closed by Kia: {closed}  |  Fees paid: {paid}\n\n"
            + ("\n".join(rows) if rows else "No referrals in period")
        )


# ---------------------------------------------------------------------------
# Lead quality filters
# ---------------------------------------------------------------------------

def _contains_excluded_state(text: str) -> bool:
    t = " " + text.lower() + " "
    return any(term in t for term in EXCLUDED_STATE_TERMS)


def _is_target_insurance(title: str, body: str) -> bool:
    combined = (title + " " + body).lower()
    if not any(t in combined for t in TARGET_INSURANCE):
        return False
    title_lower = title.lower()
    non_hits = sum(1 for t in NON_TARGET_INSURANCE if t in title_lower)
    tgt_hits  = sum(1 for t in TARGET_INSURANCE    if t in title_lower)
    if non_hits > 0 and tgt_hits == 0:
        return False
    return True


def _has_buying_intent(title: str, body: str) -> bool:
    combined = (title + " " + body).lower()
    has_intent = any(t in combined for t in BUYING_INTENT)
    pure_complaint = any(t in combined for t in COMPLAINT_ONLY) and not has_intent
    return has_intent and not pure_complaint


def _qualifies(title: str, body: str) -> bool:
    text = title + " " + body
    if _contains_excluded_state(text):
        return False
    if not _is_target_insurance(title, body):
        return False
    if not _has_buying_intent(title, body):
        return False
    return True


def _tag(title: str, body: str) -> str:
    combined = (title + " " + body).lower()
    tags = []
    if any(w in combined for w in ["auto", "car", "vehicle", "truck", "motorcycle"]):
        tags.append("auto-insurance")
    if any(w in combined for w in ["home", "house", "homeowner", "property", "renters", "condo"]):
        tags.append("home-insurance")
    return ",".join(tags) if tags else "insurance"


# ---------------------------------------------------------------------------
# Reddit scraper (read-only)
# ---------------------------------------------------------------------------

def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "InsuranceLeadBot/2.0 (contact kiaconwell@gmail.com)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def scrape_reddit_leads(
    keywords:   list[str] | None = None,
    subreddits: list[str] | None = None,
    limit: int = 25,
    days:  int = 30,
) -> list[dict]:
    if keywords   is None: keywords   = INSURANCE_KEYWORDS
    if subreddits is None: subreddits = INSURANCE_SUBREDDITS

    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    raw: list[dict] = []

    for subreddit in subreddits:
        for keyword in keywords:
            url = (
                f"https://www.reddit.com/r/{subreddit}/search.json"
                f"?q={urllib.parse.quote(keyword)}&restrict_sr=1&sort=new"
                f"&limit={limit}&t=month"
            )
            try:
                data = _fetch_json(url)
                for pw in data.get("data", {}).get("children", []):
                    p = pw.get("data", {})
                    if dt.datetime.utcfromtimestamp(p.get("created_utc", 0)) < cutoff:
                        continue
                    if p.get("score", 0) < MIN_POST_SCORE:
                        continue
                    author = p.get("author", "")
                    if author in ("[deleted]", "AutoModerator", ""):
                        continue
                    if p.get("removed_by_category") or p.get("stickied"):
                        continue
                    ad = ["agent here", "dm me for", "i'm an agent", "i am an agent"]
                    title = p.get("title", "")
                    body  = p.get("selftext", "")
                    if any(s in (title + body).lower() for s in ad):
                        continue
                    if not _qualifies(title, body):
                        continue
                    raw.append({
                        "source":   f"reddit:r/{subreddit}",
                        "name":     author,
                        "email":    f"reddit:u/{author}",
                        "question": title[:500],
                        "body":     body.strip()[:600],
                        "tags":     _tag(title, body),
                        "url":      f"https://reddit.com{p.get('permalink', '')}",
                    })
                time.sleep(1.5)
            except Exception as exc:
                print(f"  [Reddit] r/{subreddit} '{keyword}': {exc}")

    seen:   set[tuple] = set()
    unique: list[dict] = []
    for lead in raw:
        key = (lead["name"], lead["question"])
        if key not in seen:
            seen.add(key)
            unique.append(lead)
    return unique


# ---------------------------------------------------------------------------
# Craigslist scraper (read-only, RSS)
# ---------------------------------------------------------------------------

def _fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "InsuranceLeadBot/2.0 (contact kiaconwell@gmail.com)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def scrape_craigslist_leads() -> list[dict]:
    raw: list[dict] = []

    for city in CRAIGSLIST_CITIES:
        for query in CRAIGSLIST_QUERIES:
            url = (
                f"https://{city}.craigslist.org/search/fns"
                f"?query={urllib.parse.quote(query)}&sort=date&format=rss"
            )
            try:
                xml_text = _fetch_text(url)
                root    = ET.fromstring(xml_text)
                channel = root.find("channel")
                if channel is None:
                    continue
                for item in channel.findall("item"):
                    title_el = item.find("title")
                    link_el  = item.find("link")
                    desc_el  = item.find("description")
                    title = (title_el.text or "") if title_el is not None else ""
                    link  = (link_el.text  or "") if link_el  is not None else ""
                    desc  = re.sub(
                        r"<[^>]+>", " ",
                        (desc_el.text or "") if desc_el is not None else ""
                    ).strip()[:600]

                    if not title.strip():
                        continue
                    if not _qualifies(title, desc):
                        continue

                    raw.append({
                        "source":   f"craigslist:{city}",
                        "name":     f"cl-{city}-anon",
                        "email":    f"craigslist:{link}",
                        "question": title[:500],
                        "body":     desc,
                        "tags":     _tag(title, desc),
                        "url":      link,
                    })
                time.sleep(1.0)
            except Exception as exc:
                print(f"  [Craigslist] {city} '{query}': {exc}")

    seen:   set[tuple] = set()
    unique: list[dict] = []
    for lead in raw:
        key = (lead["name"], lead["question"])
        if key not in seen:
            seen.add(key)
            unique.append(lead)
    return unique


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

def send_email(to_email: str, subject: str, body: str) -> None:
    host      = os.getenv("SMTP_HOST")
    port      = int(os.getenv("SMTP_PORT", "587"))
    user      = os.getenv("SMTP_USER")
    password  = os.getenv("SMTP_PASS")
    from_email = os.getenv("SMTP_FROM", user or "leadbot@localhost")

    if not host or not user or not password:
        raise RuntimeError("SMTP_HOST, SMTP_USER, SMTP_PASS are required.")

    msg = EmailMessage()
    msg["From"]    = from_email
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg.set_content(body, charset="utf-8")

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)


def format_batch_digest(referrals: list[dict]) -> str:
    today = dt.datetime.utcnow().strftime("%B %d, %Y")
    lines = [
        f"Hi Kia,",
        f"",
        f"Here are {len(referrals)} new insurance leads as of {today}.",
        f"Each person is actively shopping for auto or home insurance.",
        f"",
        f"Your quote link: {PARTNER_WEBSITE}",
        f"",
        f"When a lead signs a contract with you, reply with their referral",
        f"code so Erin can track the finder's fee.",
        f"",
        "=" * 60,
    ]

    for i, ref in enumerate(referrals, 1):
        email_val = ref["email"]
        if email_val.startswith("reddit:"):
            contact = f"Reddit {email_val.replace('reddit:', '')}"
        elif email_val.startswith("craigslist:"):
            contact = "See post link below"
        else:
            contact = email_val

        post_url  = ref.get("post_url") or ""
        body_text = (ref.get("body") or "").strip()

        lines += [
            f"",
            f"LEAD #{i}  --  {ref['ref_code']}",
            f"  Source     : {ref['source']}",
            f"  Username   : {ref['name']}",
            f"  Contact    : {contact}",
            f"  Tags       : {ref.get('tags', '')}",
            f"  Their Post : {ref['question']}",
        ]
        if body_text:
            lines.append(f"  Details    : {body_text[:300]}")
        if post_url:
            lines.append(f"  Link       : {post_url}")
        lines.append("  " + "-" * 56)

    lines += [
        "",
        "=" * 60,
        f"Total leads in this batch: {len(referrals)}",
        f"",
        f"Questions? Contact Erin: erinswyrick85@gmail.com",
    ]
    return "\n".join(lines)


def finder_fee_invoice_text(referral: dict, finder_fee_amount: float) -> str:
    return textwrap.dedent(f"""
        Finder's Fee Invoice -- {referral['ref_code']}

        Hi Kia,

        Referral {referral['ref_code']} has been confirmed as a closed customer
        (they signed an insurance contract with you).

        Referred Prospect : {referral['name']}
        Contact           : {referral['email']}
        Partner Sale      : ${referral['sale_amount']:.2f}
        Closed At (UTC)   : {referral['sold_at']}

        Finder's Fee Due  : ${finder_fee_amount:.2f}
        Terms             : Net 7

        Follow-up schedule if unpaid:
          Day 1  : Invoice (this message)
          Day 7  : Reminder
          Day 14 : Reminder
          Day 21 : Final reminder

        Payment: Zelle / Cash App / PayPal
    """).strip()


# ---------------------------------------------------------------------------
# CLI command handlers
# ---------------------------------------------------------------------------

def cmd_scrape_web(args: argparse.Namespace) -> None:
    print(f"Scraping Reddit for insurance leads (last {args.days} days)...")
    reddit_leads = scrape_reddit_leads(limit=args.limit, days=args.days)
    print(f"  Reddit: {len(reddit_leads)} qualifying posts found.")

    print("Scraping Craigslist for insurance leads...")
    cl_leads = scrape_craigslist_leads()
    print(f"  Craigslist: {len(cl_leads)} qualifying posts found.")

    all_raw = reddit_leads + cl_leads
    bot = ReferralBot(args.db)

    new_count     = 0
    skipped_count = 0

    for lead_data in all_raw:
        if bot.referral_exists(lead_data["name"], lead_data["question"]):
            skipped_count += 1
            continue

        rid = bot.add_referral(
            Referral(
                source=lead_data["source"],
                name=lead_data["name"],
                email=lead_data["email"],
                question=lead_data["question"],
                body=lead_data.get("body", ""),
                tags=lead_data["tags"],
            ),
            owner=args.owner,
            post_url=lead_data.get("url", ""),
        )
        with bot._connect() as conn:
            conn.execute(
                "UPDATE leads SET post_url=?, body=? WHERE id=?",
                (lead_data.get("url", ""), lead_data.get("body", ""), rid),
            )
        new_count += 1

    print(
        f"\nSaved {new_count} new leads "
        f"({skipped_count} duplicates skipped)."
    )

    unnotified_count = bot.count_unnotified()
    needed = max(0, BATCH_THRESHOLD - unnotified_count)
    print(f"Leads waiting to send to Kia: {unnotified_count} / {BATCH_THRESHOLD}")

    if unnotified_count < BATCH_THRESHOLD and not args.force_send:
        print(
            f"Need {needed} more lead(s) before sending batch email."
            f" Run again to keep collecting."
        )
        return

    unnotified = bot.get_unnotified_referrals()
    if not args.notify_partner:
        print("\n-- Leads queued (--no-notify-partner set, not emailing) --")
        for ref in unnotified:
            print(f"\n  [{ref['ref_code']}] {ref['name']} | {ref['source']}")
            print(f"    Post : {ref['question']}")
            if ref.get("body"):
                print(f"    Body : {ref['body'][:200]}")
            print(f"    Link : {ref.get('post_url', 'N/A')}")
        return

    digest  = format_batch_digest(unnotified)
    subject = (
        f"{len(unnotified)} New Insurance Leads -- "
        f"{dt.datetime.utcnow().strftime('%b %d, %Y')}"
    )
    try:
        send_email(PARTNER_EMAIL, subject, digest)
        bot.mark_notified([r["id"] for r in unnotified])
        print(
            f"\nSUCCESS: Batch of {len(unnotified)} leads emailed to {PARTNER_EMAIL}."
        )
    except Exception as exc:
        print(f"\nERROR sending email: {exc}")


def cmd_mark_partner_closed(args: argparse.Namespace) -> None:
    bot = ReferralBot(args.db)
    if not bot.mark_partner_closed(args.ref_code, args.sale_amount, args.finders_fee_amount):
        raise SystemExit(f"No referral found for {args.ref_code}")
    referral = bot.get_referral_by_code(args.ref_code)
    invoice  = finder_fee_invoice_text(referral, args.finders_fee_amount)
    print(invoice)
    if args.send_invoice:
        send_email(PARTNER_EMAIL, f"Finder's Fee Invoice: {args.ref_code}", invoice)
        print(f"Invoice emailed to {PARTNER_EMAIL}.")


def cmd_mark_finder_fee_paid(args: argparse.Namespace) -> None:
    bot = ReferralBot(args.db)
    if not bot.mark_finder_fee_paid(args.ref_code, args.paid_amount):
        raise SystemExit(f"No referral found for {args.ref_code}")
    print(f"Marked {args.ref_code} as FINDER'S FEE PAID (${args.paid_amount:.2f}).")


def cmd_referral_summary(args: argparse.Namespace) -> None:
    bot    = ReferralBot(args.db)
    report = bot.referral_summary(days=args.days)
    print(report)
    if args.email:
        send_email(args.to, f"Referral Summary ({args.days}-day window)", report)
        print(f"Summary emailed to {args.to}.")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Insurance lead scraper and finder's-fee tracker."
    )
    parser.add_argument("--db", default=DB_PATH)
    sub = parser.add_subparsers(required=True)

    # web-scrape
    scrape = sub.add_parser("web-scrape", help="Scrape Reddit + Craigslist for leads")
    scrape.add_argument("--days",       type=int, default=30)
    scrape.add_argument("--limit",      type=int, default=25)
    scrape.add_argument("--owner",      default=DEFAULT_REF_OWNER)
    scrape.add_argument("--force-send", action="store_true",
                        help="Send batch email even if fewer than 50 leads are queued")
    scrape.add_argument("--notify-partner",    action="store_true", default=True)
    scrape.add_argument("--no-notify-partner", dest="notify_partner", action="store_false")
    scrape.set_defaults(func=cmd_scrape_web)

    # mark-partner-closed
    closed = sub.add_parser("mark-partner-closed")
    closed.add_argument("--ref-code",           required=True)
    closed.add_argument("--sale-amount",         type=float, required=True)
    closed.add_argument("--finders-fee-amount",  type=float, default=DEFAULT_FEE_AMOUNT)
    closed.add_argument("--send-invoice",        action="store_true")
    closed.set_defaults(func=cmd_mark_partner_closed)

    # mark-finders-fee-paid
    paid = sub.add_parser("mark-finders-fee-paid")
    paid.add_argument("--ref-code",   required=True)
    paid.add_argument("--paid-amount", type=float, default=DEFAULT_FEE_AMOUNT)
    paid.set_defaults(func=cmd_mark_finder_fee_paid)

    # summaries
    for name, default_days in [
        ("referral-summary", 7),
        ("weekly-summary",   7),
        ("daily-summary",    1),
    ]:
        s = sub.add_parser(name)
        s.add_argument("--days",  type=int, default=default_days)
        s.add_argument("--email", action="store_true")
        s.add_argument("--to",    default=DEFAULT_REPORT_TO)
        s.set_defaults(func=cmd_referral_summary)

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
