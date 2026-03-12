#!/usr/bin/env python3
"""Referral / finder's-fee tracker for prospects sent to a partner.

Product framing:
- Track referred prospects sent to your friend/partner.
- Record when a referred prospect becomes your partner's customer.
- Track expected and paid finder's fees.
- Email referral summaries (weekly by default) to you.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import smtplib
import sqlite3
import textwrap
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

DB_PATH = os.getenv("LEADBOT_DB", "leadbot.db")
PARTNER_EMAIL = "KIACONWELL@PRIMERICA.COM"
PARTNER_WEBSITE = "https://livemore.net/o/kia_conwell"
DEFAULT_REF_OWNER = os.getenv("LEADBOT_REF_OWNER", "ERIN")
DEFAULT_REPORT_TO = os.getenv("LEADBOT_REPORT_TO", "Erin067841@outlook.com")
DEFAULT_FEE_AMOUNT = float(os.getenv("LEADBOT_DEFAULT_FEE", "50"))

PARTNER_CONTEXT = textwrap.dedent(
    """
    Primerica serves middle-income households in the U.S. and Canada with term life,
    investments, mortgage-related referrals, and financial education.
    """
).strip()


@dataclass
class Referral:
    source: str
    name: str
    email: str
    question: str
    tags: str


# Backward-compatible alias
Lead = Referral


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
                    paid_amount REAL
                )
                """
            )
            for ddl in [
                "ALTER TABLE leads ADD COLUMN invoice_amount REAL",
                "ALTER TABLE leads ADD COLUMN invoice_sent_at TEXT",
                "ALTER TABLE leads ADD COLUMN invoice_paid INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE leads ADD COLUMN invoice_paid_at TEXT",
                "ALTER TABLE leads ADD COLUMN paid_amount REAL",
            ]:
                col = ddl.split("ADD COLUMN ", 1)[1].split()[0]
                if not self._column_exists(conn, col):
                    conn.execute(ddl)

    def _build_ref_code(self, referral_id: int, owner: str = DEFAULT_REF_OWNER) -> str:
        clean_owner = re.sub(r"[^A-Z0-9]", "", owner.upper())
        return f"{clean_owner}-REF-{referral_id:06d}"

    def add_referral(self, referral: Referral, owner: str = DEFAULT_REF_OWNER) -> int:
        created_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO leads(created_at, source, name, email, question, tags, ref_code, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'referred')
                """,
                (
                    created_at,
                    referral.source,
                    referral.name,
                    referral.email,
                    referral.question,
                    referral.tags,
                    "PENDING",
                ),
            )
            referral_id = cur.lastrowid
            ref_code = self._build_ref_code(referral_id, owner)
            conn.execute("UPDATE leads SET ref_code=? WHERE id=?", (ref_code, referral_id))
        return referral_id

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

    def mark_partner_closed(self, ref_code: str, sale_amount: float, finder_fee_amount: float) -> bool:
        sold_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE leads
                SET status='partner_closed', sale_amount=?, sold_at=?, invoice_amount=?, invoice_sent_at=?
                WHERE ref_code=?
                """,
                (sale_amount, sold_at, finder_fee_amount, sold_at, ref_code),
            )
            return cur.rowcount > 0

    # Backward-compatible wrapper
    def mark_sale(self, ref_code: str, sale_amount: float, invoice_amount: float = DEFAULT_FEE_AMOUNT) -> bool:
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
            closed = sum(1 for r in referrals if r["status"] in ("partner_closed", "fee_paid", "sold", "paid"))
            paid = sum(1 for r in referrals if r["invoice_paid"] == 1)
            unpaid = closed - paid

            rows = [
                f"- {r['ref_code']} | {r['name']} | {r['email']} | status={r['status']} | fee_paid={bool(r['invoice_paid'])}"
                for r in referrals
            ]

        return textwrap.dedent(
            f"""
            Referral Summary (last {days} day{'s' if days != 1 else ''})
            Generated: {dt.datetime.utcnow().isoformat()} UTC

            Total referred prospects: {total}
            Became partner customers: {closed}
            Finder's fees paid: {paid}
            Finder's fees unpaid: {unpaid}

            Referrals:
            {chr(10).join(rows) if rows else '- No referrals in period'}
            """
        ).strip()

    # Backward-compatible wrapper
    def summary(self, days: int = 7) -> str:
        return self.referral_summary(days=days)


def draft_partner_intro(referral: dict) -> str:
    return textwrap.dedent(
        f"""
        Hi {referral['name']},

        I’m connecting you with my friend for financial guidance.

        Partner Contact: {PARTNER_EMAIL}
        Partner Website: {PARTNER_WEBSITE}
        Referral code: {referral['ref_code']} (please include this code)

        Context:
        {PARTNER_CONTEXT}
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

        Referral {referral['ref_code']} has been confirmed as a partner-closed customer.

        Referred Prospect: {referral['name']}
        Referred Email: {referral['email']}
        Partner Sale Amount: ${referral['sale_amount']:.2f}
        Partner Closed At (UTC): {referral['sold_at']}

        Finder's Fee Due: ${finder_fee_amount:.2f}
        Terms: Net 7

        Follow-up schedule if unpaid:
        - Day 1: Invoice
        - Day 7: Reminder
        - Day 14: Reminder
        - Day 21: Final reminder
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


def cmd_add_referral(args: argparse.Namespace) -> None:
    bot = ReferralBot(args.db)
    referral_id = bot.add_referral(
        Referral(args.source, args.name, args.email, args.question, args.tags), owner=args.owner
    )
    referral = bot.get_referral(referral_id)
    print(f"Created referral #{referral_id} with code {referral['ref_code']}")
    print("\n--- Suggested referral intro ---")
    print(draft_partner_intro(referral))
    if args.notify_partner:
        send_email(
            PARTNER_EMAIL,
            f"New Referral: {referral['name']} ({referral['ref_code']})",
            f"New referred prospect from {referral['source']}\n\n{draft_partner_intro(referral)}",
        )


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
                Referral(row["source"], row["name"], row["email"], row["question"], row.get("tags", "")),
                owner=args.owner,
            )
            created += 1
    print(f"Imported {created} referrals from {args.csv_file}")


def cmd_mark_partner_closed(args: argparse.Namespace) -> None:
    bot = ReferralBot(args.db)
    if not bot.mark_partner_closed(args.ref_code, args.sale_amount, args.finders_fee_amount):
        raise SystemExit(f"No referral found for {args.ref_code}")
    referral = bot.get_referral_by_code(args.ref_code)
    invoice = finder_fee_invoice_text(referral, finder_fee_amount=args.finders_fee_amount)
    print(invoice)
    if args.send_invoice:
        send_email(PARTNER_EMAIL, f"Finder's Fee Invoice: {args.ref_code}", invoice)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Referral / finder's-fee tracker for prospects you send to your partner."
    )
    parser.add_argument("--db", default=DB_PATH, help="SQLite database path")
    sub = parser.add_subparsers(required=True)

    add = sub.add_parser("add-referral", help="Add referred prospect")
    add.add_argument("--source", required=True, help="Referral source (FB groups, Reddit, warm DM, etc.)")
    add.add_argument("--name", required=True)
    add.add_argument("--email", required=True)
    add.add_argument("--question", required=True)
    add.add_argument("--tags", default="")
    add.add_argument("--owner", default=DEFAULT_REF_OWNER)
    add.add_argument("--notify-partner", action="store_true", help="Email referral details to partner")
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

    bulk = sub.add_parser("bulk-import", help="Import referrals from CSV")
    bulk.add_argument("--csv-file", required=True)
    bulk.add_argument("--owner", default=DEFAULT_REF_OWNER)
    bulk.set_defaults(func=cmd_bulk_import)

    closed = sub.add_parser(
        "mark-partner-closed",
        help="Mark customer closed by partner (when friend confirms they became his customer)",
    )
    closed.add_argument("--ref-code", required=True)
    closed.add_argument("--sale-amount", type=float, required=True, help="Partner-reported sale amount")
    closed.add_argument("--finders-fee-amount", type=float, default=DEFAULT_FEE_AMOUNT)
    closed.add_argument("--send-invoice", action="store_true")
    closed.set_defaults(func=cmd_mark_partner_closed)

    sold_old = sub.add_parser("mark-sold", help="(legacy) Mark partner closed")
    sold_old.add_argument("--ref-code", required=True)
    sold_old.add_argument("--sale-amount", type=float, required=True)
    sold_old.add_argument("--invoice-amount", type=float, default=DEFAULT_FEE_AMOUNT)
    sold_old.add_argument("--send-invoice", action="store_true")
    sold_old.set_defaults(func=cmd_mark_sold)

    paid = sub.add_parser("mark-finders-fee-paid", help="Mark finder's fee paid")
    paid.add_argument("--ref-code", required=True)
    paid.add_argument("--paid-amount", type=float, default=DEFAULT_FEE_AMOUNT)
    paid.set_defaults(func=cmd_mark_finders_fee_paid)

    paid_old = sub.add_parser("mark-paid", help="(legacy) Mark finder's fee paid")
    paid_old.add_argument("--ref-code", required=True)
    paid_old.add_argument("--paid-amount", type=float, default=DEFAULT_FEE_AMOUNT)
    paid_old.set_defaults(func=cmd_mark_paid)

    summary = sub.add_parser("referral-summary", help="Generate referral summary")
    summary.add_argument("--days", type=int, default=7)
    summary.add_argument("--email", action="store_true", help="Email summary to report recipient")
    summary.add_argument("--to", default=DEFAULT_REPORT_TO)
    summary.set_defaults(func=cmd_referral_summary)

    weekly = sub.add_parser("weekly-summary", help="Generate weekly referral summary")
    weekly.add_argument("--days", type=int, default=7)
    weekly.add_argument("--email", action="store_true", help="Email summary to report recipient")
    weekly.add_argument("--to", default=DEFAULT_REPORT_TO)
    weekly.set_defaults(func=cmd_referral_summary)

    daily = sub.add_parser("daily-summary", help="Generate daily referral summary")
    daily.add_argument("--days", type=int, default=1)
    daily.add_argument("--email", action="store_true", help="Email summary to report recipient")
    daily.add_argument("--to", default=DEFAULT_REPORT_TO)
    daily.set_defaults(func=cmd_referral_summary)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
