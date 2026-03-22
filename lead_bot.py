#!/usr/bin/env python3
"""Referral / finder's-fee tracker for prospects sent to a partner.

Product framing:
- Scrape public web sources (Reddit, forums) for people looking for auto/home insurance.
- Track referred prospects sent to your friend/partner Kia Conwell.
- Record when a referred prospect becomes your partner's customer (signs a contract).
- Track expected and paid finder's fees.
- Email referral summaries (weekly by default) to you.
"""

from __future__ import annotations

import argparse
import csv
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
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

DB_PATH = os.getenv("LEADBOT_DB", "leadbot.db")
PARTNER_EMAIL = os.getenv("PARTNER_EMAIL", "kiaconwell@gmail.com")
PARTNER_WEBSITE = "https://livemore.net/o/kia_conwell"
DEFAULT_REF_OWNER = os.getenv("LEADBOT_REF_OWNER", "ERIN")
DEFAULT_REPORT_TO = os.getenv("LEADBOT_REPORT_TO", "Erin067841@outlook.com")
DEFAULT_FEE_AMOUNT = float(os.getenv("LEADBOT_DEFAULT_FEE", "50"))

PARTNER_CONTEXT = textwrap.dedent(
    """
    Kia Conwell is a licensed insurance agent helping families protect their homes,
    cars, and loved ones. She provides personalized quotes for:
      - Auto / car insurance
      - Home / homeowners insurance
      - Bundled auto + home discounts
    Contact Kia for a free quote: kiaconwell@gmail.com
    Website: https://livemore.net/o/kia_conwell
    """
).strip()

# ---------------------------------------------------------------------------
# Subreddits and keywords used by the web scraper
# ---------------------------------------------------------------------------
INSURANCE_SUBREDDITS = [
    "insurance",
    "personalfinance",
    "homeowners",
    "FirstTimeHomeBuyer",
    "frugal",
    "homebuying",
    "AutoInsurance",
]

INSURANCE_KEYWORDS = [
    "auto insurance quote",
    "car insurance quote",
    "home insurance quote",
    "homeowners insurance quote",
    "looking for car insurance",
    "looking for home insurance",
    "need auto insurance",
    "need home insurance",
    "switching car insurance",
    "switching home insurance",
    "cheaper car insurance",
    "cheaper home insurance",
    "bundle auto home",
]

# Minimum Reddit post score to consider (filters obvious spam/noise)
MIN_POST_SCORE = 1


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Referral:
    source: str
    name: str
    email: str
    question: str
    tags: str


# Backward-compatible alias
Lead = Referral


# ---------------------------------------------------------------------------
# Database layer
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    question TEXT NOT NULL,
                    tags TEXT,
                    ref_code TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'referred',
                    sale_amount REAL,
                    sold_at TEXT,
                    invoice_amount REAL,
                    invoice_sent_at TEXT,
                    invoice_paid INTEGER NOT NULL DEFAULT 0,
                    invoice_paid_at TEXT,
                    paid_amount REAL,
                    post_url TEXT
                )
                """
            )
            for ddl in [
                "ALTER TABLE leads ADD COLUMN invoice_amount REAL",
                "ALTER TABLE leads ADD COLUMN invoice_sent_at TEXT",
                "ALTER TABLE leads ADD COLUMN invoice_paid INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE leads ADD COLUMN invoice_paid_at TEXT",
                "ALTER TABLE leads ADD COLUMN paid_amount REAL",
                "ALTER TABLE leads ADD COLUMN post_url TEXT",
            ]:
                col = ddl.split("ADD COLUMN ", 1)[1].split()[0]
                if not self._column_exists(conn, col):
                    conn.execute(ddl)

    def _build_ref_code(self, referral_id: int, owner: str = DEFAULT_REF_OWNER) -> str:
        clean_owner = re.sub(r"[^A-Z0-9]", "", owner.upper())
        return f"{clean_owner}-REF-{referral_id:06d}"

    def add_referral(self, referral: Referral, owner: str = DEFAULT_REF_OWNER,
                     post_url: str = "") -> int:
        created_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO leads(created_at, source, name, email, question, tags,
                                  ref_code, status, post_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'referred', ?)
                """,
                (
                    created_at,
                    referral.source,
                    referral.name,
                    referral.email,
                    referral.question,
                    referral.tags,
                    "PENDING",
                    post_url,
                ),
            )
            referral_id = cur.lastrowid
            ref_code = self._build_ref_code(referral_id, owner)
            conn.execute("UPDATE leads SET ref_code=? WHERE id=?", (ref_code, referral_id))
        return referral_id

    def referral_exists(self, name: str, question: str) -> bool:
        """Return True if a lead with this exact (name, question) is already stored."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM leads WHERE name=? AND question=?", (name, question)
            ).fetchone()
            return row is not None

    # Backward-compatible wrapper
    def add_lead(self, lead: Lead, owner: str = DEFAULT_REF_OWNER) -> int:
        return self.add_referral(lead, owner=owner)

    def get_referral(self, referral_id: int) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM leads WHERE id=?", (referral_id,)).fetchone()
            return dict(row) if row else None

    # Backward-compatible wrapper
    def get_lead(self, lead_id: int) -> Optional[dict]:
        return self.get_referral(lead_id)

    def get_referral_by_code(self, ref_code: str) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM leads WHERE ref_code=?", (ref_code,)).fetchone()
            return dict(row) if row else None

    # Backward-compatible wrapper
    def get_lead_by_ref(self, ref_code: str) -> Optional[dict]:
        return self.get_referral_by_code(ref_code)

    def mark_partner_closed(self, ref_code: str, sale_amount: float,
                             finder_fee_amount: float) -> bool:
        sold_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE leads
                SET status='partner_closed', sale_amount=?, sold_at=?,
                    invoice_amount=?, invoice_sent_at=?
                WHERE ref_code=?
                """,
                (sale_amount, sold_at, finder_fee_amount, sold_at, ref_code),
            )
            return cur.rowcount > 0

    # Backward-compatible wrapper
    def mark_sale(self, ref_code: str, sale_amount: float,
                  invoice_amount: float = DEFAULT_FEE_AMOUNT) -> bool:
        return self.mark_partner_closed(ref_code, sale_amount, invoice_amount)

    def mark_finder_fee_paid(self, ref_code: str, paid_amount: float) -> bool:
        paid_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE leads
                SET invoice_paid=1, invoice_paid_at=?, paid_amount=?, status='fee_paid'
                WHERE ref_code=?
                """,
                (paid_at, paid_amount, ref_code),
            )
            return cur.rowcount > 0

    # Backward-compatible wrapper
    def mark_paid(self, ref_code: str, paid_amount: float) -> bool:
        return self.mark_finder_fee_paid(ref_code, paid_amount)

    def referral_summary(self, days: int = 7) -> str:
        since = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            referrals = conn.execute(
                "SELECT * FROM leads WHERE created_at >= ? ORDER BY created_at DESC", (since,)
            ).fetchall()

            total = len(referrals)
            closed = sum(
                1 for r in referrals
                if r["status"] in ("partner_closed", "fee_paid", "sold", "paid")
            )
            paid = sum(1 for r in referrals if r["invoice_paid"] == 1)
            unpaid = closed - paid

            rows = [
                f"- {r['ref_code']} | {r['name']} | {r['email']} | "
                f"status={r['status']} | fee_paid={bool(r['invoice_paid'])}"
                for r in referrals
            ]

        return textwrap.dedent(
            f"""
            Referral Summary (last {days} day{'s' if days != 1 else ''})
            Generated: {dt.datetime.utcnow().isoformat()} UTC

            Total referred prospects: {total}
            Became partner customers (signed contracts): {closed}
            Finder's fees paid: {paid}
            Finder's fees unpaid: {unpaid}

            Referrals:
            {chr(10).join(rows) if rows else '- No referrals in period'}
            """
        ).strip()

    # Backward-compatible wrapper
    def summary(self, days: int = 7) -> str:
        return self.referral_summary(days=days)


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

def draft_partner_intro(referral: dict) -> str:
    post_line = ""
    if referral.get("post_url"):
        post_line = f"\nOriginal post: {referral['post_url']}"

    contact_line = referral["email"]
    if referral["email"].startswith("reddit:"):
        username = referral["email"].replace("reddit:", "")
        contact_line = f"Reddit {username}{post_line}"
    else:
        contact_line = referral["email"]

    return textwrap.dedent(
        f"""
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
        """
    ).strip()


# Backward-compatible wrapper
def draft_reply(lead: dict) -> str:
    return draft_partner_intro(lead)


def finder_fee_invoice_text(referral: dict, finder_fee_amount: float) -> str:
    return textwrap.dedent(
        f"""
        Subject: Finder's Fee Invoice - {referral['ref_code']}

        Hi Kia,

        Referral {referral['ref_code']} has been confirmed as a partner-closed customer
        (they signed an insurance contract with you).

        Referred Prospect : {referral['name']}
        Contact           : {referral['email']}
        Partner Sale      : ${referral['sale_amount']:.2f}
        Closed At (UTC)   : {referral['sold_at']}

        Finder's Fee Due  : ${finder_fee_amount:.2f}
        Terms             : Net 7

        Follow-up schedule if unpaid:
        - Day 1  : Invoice (this message)
        - Day 7  : Reminder
        - Day 14 : Reminder
        - Day 21 : Final reminder

        Payment: Zelle / Cash App / PayPal
        """
    ).strip()


# Backward-compatible wrapper
def invoice_text(lead: dict, invoice_amount: float = DEFAULT_FEE_AMOUNT) -> str:
    return finder_fee_invoice_text(lead, invoice_amount)


def send_email(to_email: str, subject: str, body: str) -> None:
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


# ---------------------------------------------------------------------------
# Web scraper  — Reddit public JSON API (no auth needed for public posts)
# ---------------------------------------------------------------------------

def _reddit_fetch(url: str) -> dict:
    """Fetch a Reddit JSON endpoint with a polite User-Agent."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "InsuranceLeadBot/1.0 (referral-tracker; contact kiaconwell@gmail.com)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _is_legit_post(post: dict) -> bool:
    """Return True if the post looks like a genuine person asking about insurance."""
    author = post.get("author", "")
    title = (post.get("title") or "").lower()
    body = (post.get("selftext") or "").lower()

    # Skip deleted / removed / bot-like entries
    if author in ("[deleted]", "AutoModerator", ""):
        return False
    if post.get("removed_by_category"):
        return False
    # Skip stickied mod posts
    if post.get("stickied"):
        return False
    # Must have meaningful content (title is enough)
    if len(title.strip()) < 10:
        return False
    # Skip posts that are just self-promotion or ads
    ad_signals = ["agent here", "dm me", "i'm an agent", "i am an agent", "shop with me"]
    if any(s in title or s in body for s in ad_signals):
        return False
    # Require at least some insurance relevance in the title or body
    insurance_words = ["insurance", "insure", "premium", "deductible", "coverage",
                       "quote", "policy", "bundle", "rate"]
    combined = title + " " + body
    if not any(w in combined for w in insurance_words):
        return False
    return True


def scrape_reddit_leads(
    keywords: list[str] | None = None,
    subreddits: list[str] | None = None,
    limit: int = 25,
    days: int = 30,
) -> list[dict]:
    """
    Search Reddit for people actively asking about auto / home insurance.

    Returns a list of raw lead dicts with keys:
      source, name, email (reddit:u/username), question, tags, url, body
    """
    if keywords is None:
        keywords = INSURANCE_KEYWORDS
    if subreddits is None:
        subreddits = INSURANCE_SUBREDDITS

    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    raw_leads: list[dict] = []

    for subreddit in subreddits:
        for keyword in keywords:
            encoded = urllib.parse.quote(keyword)
            url = (
                f"https://www.reddit.com/r/{subreddit}/search.json"
                f"?q={encoded}&restrict_sr=1&sort=new&limit={limit}&t=month"
            )
            try:
                data = _reddit_fetch(url)
                posts = data.get("data", {}).get("children", [])
                for post_wrapper in posts:
                    p = post_wrapper.get("data", {})
                    created = dt.datetime.utcfromtimestamp(p.get("created_utc", 0))
                    if created < cutoff:
                        continue
                    if p.get("score", 0) < MIN_POST_SCORE:
                        continue
                    if not _is_legit_post(p):
                        continue

                    # Determine whether this is auto, home, or both
                    combined = ((p.get("title") or "") + " " + (p.get("selftext") or "")).lower()
                    tags_list = []
                    if any(w in combined for w in ["auto", "car", "vehicle", "truck", "motorcycle"]):
                        tags_list.append("auto-insurance")
                    if any(w in combined for w in ["home", "house", "homeowner", "property", "renters"]):
                        tags_list.append("home-insurance")
                    if not tags_list:
                        tags_list.append("insurance")

                    raw_leads.append({
                        "source": f"reddit:r/{subreddit}",
                        "name": p["author"],
                        "email": f"reddit:u/{p['author']}",
                        "question": (p.get("title") or "")[:500],
                        "tags": ",".join(tags_list),
                        "url": f"https://reddit.com{p.get('permalink', '')}",
                        "body": (p.get("selftext") or "")[:400],
                    })
                time.sleep(1.5)  # be polite — Reddit rate limit is ~60 req/min
            except Exception as exc:
                print(f"  Warning: could not scrape r/{subreddit} for '{keyword}': {exc}")

    # Deduplicate by (name, question)
    seen: set[tuple] = set()
    unique: list[dict] = []
    for lead in raw_leads:
        key = (lead["name"], lead["question"])
        if key not in seen:
            seen.add(key)
            unique.append(lead)

    return unique


# ---------------------------------------------------------------------------
# CLI command handlers
# ---------------------------------------------------------------------------

def cmd_add_referral(args: argparse.Namespace) -> None:
    bot = ReferralBot(args.db)
    referral_id = bot.add_referral(
        Referral(args.source, args.name, args.email, args.question, args.tags),
        owner=args.owner,
    )
    referral = bot.get_referral(referral_id)
    print(f"Created referral #{referral_id} with code {referral['ref_code']}")
    print("\n--- Suggested referral intro ---")
    print(draft_partner_intro(referral))
    if args.notify_partner:
        send_email(
            PARTNER_EMAIL,
            f"New Insurance Lead: {referral['name']} ({referral['ref_code']})",
            draft_partner_intro(referral),
        )
        print(f"Lead emailed to {PARTNER_EMAIL}.")


# Backward-compatible alias command handler
def cmd_add(args: argparse.Namespace) -> None:
    if not getattr(args, "notify_partner", False) and getattr(args, "notify_kia", False):
        args.notify_partner = True
    cmd_add_referral(args)


def cmd_bulk_import(args: argparse.Namespace) -> None:
    bot = ReferralBot(args.db)
    created = 0
    with open(args.csv_file, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"source", "name", "email", "question", "tags"}
        if not required.issubset(set(reader.fieldnames or [])):
            missing = required - set(reader.fieldnames or [])
            raise SystemExit(f"CSV missing columns: {', '.join(sorted(missing))}")
        for row in reader:
            bot.add_referral(
                Referral(
                    row["source"], row["name"], row["email"],
                    row["question"], row.get("tags", ""),
                ),
                owner=args.owner,
            )
            created += 1
    print(f"Imported {created} referrals from {args.csv_file}")


def cmd_scrape_web(args: argparse.Namespace) -> None:
    """Scrape Reddit for auto/home insurance leads and send them to Kia."""
    print(f"Scraping Reddit for auto/home insurance leads (last {args.days} days)…")

    keywords = args.keywords.split(",") if args.keywords else None
    subreddits = args.subreddits.split(",") if args.subreddits else None

    raw_leads = scrape_reddit_leads(
        keywords=keywords,
        subreddits=subreddits,
        limit=args.limit,
        days=args.days,
    )

    if not raw_leads:
        print("No new leads found.")
        return

    bot = ReferralBot(args.db)
    new_count = 0
    skipped_count = 0
    new_referrals: list[dict] = []

    for lead_data in raw_leads:
        # Skip duplicates already in the database
        if bot.referral_exists(lead_data["name"], lead_data["question"]):
            skipped_count += 1
            continue

        referral_id = bot.add_referral(
            Referral(
                source=lead_data["source"],
                name=lead_data["name"],
                email=lead_data["email"],
                question=lead_data["question"],
                tags=lead_data["tags"],
            ),
            owner=args.owner,
            post_url=lead_data.get("url", ""),
        )
        # Persist post_url into db
        with bot._connect() as conn:
            conn.execute(
                "UPDATE leads SET post_url=? WHERE id=?",
                (lead_data.get("url", ""), referral_id),
            )

        referral = bot.get_referral(referral_id)
        referral["post_url"] = lead_data.get("url", "")
        new_referrals.append(referral)
        new_count += 1

    print(f"Found {len(raw_leads)} leads → {new_count} new, {skipped_count} already known.")

    if not new_referrals:
        return

    # ---- Email each lead individually to Kia --------------------------------
    if args.notify_partner:
        errors = 0
        for referral in new_referrals:
            try:
                send_email(
                    PARTNER_EMAIL,
                    f"New Insurance Lead: {referral['name']} ({referral['ref_code']}) "
                    f"[{referral.get('tags', '')}]",
                    draft_partner_intro(referral),
                )
                print(f"  ✓ Emailed lead {referral['ref_code']} ({referral['name']}) to {PARTNER_EMAIL}")
            except Exception as exc:
                print(f"  ✗ Failed to email {referral['ref_code']}: {exc}")
                errors += 1
        if errors == 0:
            print(f"All {new_count} leads emailed to {PARTNER_EMAIL}.")
        else:
            print(f"{new_count - errors}/{new_count} leads emailed. {errors} failed.")
    else:
        # Print to stdout so operator can review
        print("\n--- New leads (not emailed; use --notify-partner to send) ---")
        for referral in new_referrals:
            print(f"\n{draft_partner_intro(referral)}")
            print("-" * 60)


def cmd_mark_partner_closed(args: argparse.Namespace) -> None:
    bot = ReferralBot(args.db)
    if not bot.mark_partner_closed(args.ref_code, args.sale_amount, args.finders_fee_amount):
        raise SystemExit(f"No referral found for {args.ref_code}")
    referral = bot.get_referral_by_code(args.ref_code)
    invoice = finder_fee_invoice_text(referral, finder_fee_amount=args.finders_fee_amount)
    print(invoice)
    if args.send_invoice:
        send_email(PARTNER_EMAIL, f"Finder's Fee Invoice: {args.ref_code}", invoice)
        print(f"Invoice emailed to {PARTNER_EMAIL}.")


# Backward-compatible alias
def cmd_mark_sold(args: argparse.Namespace) -> None:
    if not hasattr(args, "finders_fee_amount"):
        args.finders_fee_amount = getattr(args, "invoice_amount", DEFAULT_FEE_AMOUNT)
    cmd_mark_partner_closed(args)


def cmd_mark_finders_fee_paid(args: argparse.Namespace) -> None:
    bot = ReferralBot(args.db)
    if not bot.mark_finder_fee_paid(args.ref_code, args.paid_amount):
        raise SystemExit(f"No referral found for {args.ref_code}")
    print(f"Marked {args.ref_code} as FINDER'S FEE PAID (${args.paid_amount:.2f}).")


# Backward-compatible alias
def cmd_mark_paid(args: argparse.Namespace) -> None:
    cmd_mark_finders_fee_paid(args)


def cmd_referral_summary(args: argparse.Namespace) -> None:
    bot = ReferralBot(args.db)
    report = bot.referral_summary(days=args.days)
    print(report)
    if args.email:
        send_email(args.to, f"Referral Summary ({args.days}-day window)", report)
        print(f"Referral summary email sent to {args.to}.")


# Backward-compatible alias
def cmd_summary(args: argparse.Namespace) -> None:
    cmd_referral_summary(args)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Referral / finder's-fee tracker — scrapes web leads and tracks contracts."
    )
    parser.add_argument("--db", default=DB_PATH, help="SQLite database path")
    sub = parser.add_subparsers(required=True)

    # ---- web-scrape --------------------------------------------------------
    scrape = sub.add_parser(
        "web-scrape",
        help="Scrape Reddit for auto/home insurance leads and send to Kia",
    )
    scrape.add_argument("--days", type=int, default=30,
                        help="Look back this many days (default 30)")
    scrape.add_argument("--limit", type=int, default=25,
                        help="Max Reddit posts per keyword/subreddit (default 25)")
    scrape.add_argument("--keywords", default="",
                        help="Comma-separated keywords (default: built-in list)")
    scrape.add_argument("--subreddits", default="",
                        help="Comma-separated subreddits (default: built-in list)")
    scrape.add_argument("--owner", default=DEFAULT_REF_OWNER,
                        help="Referral code owner prefix")
    scrape.add_argument(
        "--notify-partner", action="store_true", default=True,
        help="Email each lead to Kia at kiaconwell@gmail.com (default: on)",
    )
    scrape.add_argument(
        "--no-notify-partner", dest="notify_partner", action="store_false",
        help="Print leads to stdout instead of emailing",
    )
    scrape.set_defaults(func=cmd_scrape_web)

    # ---- add-referral ------------------------------------------------------
    add = sub.add_parser("add-referral", help="Manually add a referred prospect")
    add.add_argument("--source", required=True,
                     help="Referral source (FB groups, Reddit, warm DM, etc.)")
    add.add_argument("--name", required=True)
    add.add_argument("--email", required=True)
    add.add_argument("--question", required=True)
    add.add_argument("--tags", default="")
    add.add_argument("--owner", default=DEFAULT_REF_OWNER)
    add.add_argument("--notify-partner", action="store_true",
                     help="Email referral details to Kia")
    add.set_defaults(func=cmd_add_referral)

    add_old = sub.add_parser("add", help="(legacy) Add referral")
    add_old.add_argument("--source", required=True)
    add_old.add_argument("--name", required=True)
    add_old.add_argument("--email", required=True)
    add_old.add_argument("--question", required=True)
    add_old.add_argument("--tags", default="")
    add_old.add_argument("--owner", default=DEFAULT_REF_OWNER)
    add_old.add_argument("--notify-kia", action="store_true")
    add_old.set_defaults(func=cmd_add, notify_partner=False)

    # ---- bulk-import -------------------------------------------------------
    bulk = sub.add_parser("bulk-import", help="Import referrals from CSV")
    bulk.add_argument("--csv-file", required=True)
    bulk.add_argument("--owner", default=DEFAULT_REF_OWNER)
    bulk.set_defaults(func=cmd_bulk_import)

    # ---- mark-partner-closed -----------------------------------------------
    closed = sub.add_parser(
        "mark-partner-closed",
        help="Mark customer closed by partner (they signed an insurance contract)",
    )
    closed.add_argument("--ref-code", required=True)
    closed.add_argument("--sale-amount", type=float, required=True,
                        help="Partner-reported sale / contract amount")
    closed.add_argument("--finders-fee-amount", type=float, default=DEFAULT_FEE_AMOUNT)
    closed.add_argument("--send-invoice", action="store_true")
    closed.set_defaults(func=cmd_mark_partner_closed)

    sold_old = sub.add_parser("mark-sold", help="(legacy) Mark partner closed")
    sold_old.add_argument("--ref-code", required=True)
    sold_old.add_argument("--sale-amount", type=float, required=True)
    sold_old.add_argument("--invoice-amount", type=float, default=DEFAULT_FEE_AMOUNT)
    sold_old.add_argument("--send-invoice", action="store_true")
    sold_old.set_defaults(func=cmd_mark_sold)

    # ---- mark-finders-fee-paid ---------------------------------------------
    paid = sub.add_parser("mark-finders-fee-paid", help="Mark finder's fee paid")
    paid.add_argument("--ref-code", required=True)
    paid.add_argument("--paid-amount", type=float, default=DEFAULT_FEE_AMOUNT)
    paid.set_defaults(func=cmd_mark_finders_fee_paid)

    paid_old = sub.add_parser("mark-paid", help="(legacy) Mark finder's fee paid")
    paid_old.add_argument("--ref-code", required=True)
    paid_old.add_argument("--paid-amount", type=float, default=DEFAULT_FEE_AMOUNT)
    paid_old.set_defaults(func=cmd_mark_paid)

    # ---- summaries ---------------------------------------------------------
    summary = sub.add_parser("referral-summary", help="Generate referral summary")
    summary.add_argument("--days", type=int, default=7)
    summary.add_argument("--email", action="store_true",
                         help="Email summary to report recipient")
    summary.add_argument("--to", default=DEFAULT_REPORT_TO)
    summary.set_defaults(func=cmd_referral_summary)

    weekly = sub.add_parser("weekly-summary", help="Generate weekly referral summary")
    weekly.add_argument("--days", type=int, default=7)
    weekly.add_argument("--email", action="store_true",
                        help="Email summary to report recipient")
    weekly.add_argument("--to", default=DEFAULT_REPORT_TO)
    weekly.set_defaults(func=cmd_referral_summary)

    daily = sub.add_parser("daily-summary", help="Generate daily referral summary")
    daily.add_argument("--days", type=int, default=1)
    daily.add_argument("--email", action="store_true",
                       help="Email summary to report recipient")
    daily.add_argument("--to", default=DEFAULT_REPORT_TO)
    daily.set_defaults(func=cmd_referral_summary)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
