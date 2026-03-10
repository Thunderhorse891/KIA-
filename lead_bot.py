#!/usr/bin/env python3
"""Lead generator assistant for Primerica representative outreach.

Compliant workflow:
- Capture inbound leads with source context.
- Generate attribution ref codes.
- Notify Kia on new leads (optional SMTP).
- Track sold leads, invoice events, and referral payments.
- Send weekly lead summary emails.
"""

from __future__ import annotations

import argparse
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
KIA_EMAIL = "KIACONWELL@PRIMERICA.COM"
KIA_WEBSITE = "https://livemore.net/o/kia_conwell"
DEFAULT_REF_OWNER = os.getenv("LEADBOT_REF_OWNER", "REF_PARTNER")
DEFAULT_REPORT_TO = os.getenv("LEADBOT_REPORT_TO", "Erin067841@outlook.com")

PRIMERICA_CONTEXT = textwrap.dedent(
    """
    Primerica is a leading provider of financial products and services for middle-income
    households across the U.S. and Canada. Offerings include term life insurance,
    investments, mortgages, auto/home referrals, and legal protection services through
    strategic partners.
    """
).strip()


@dataclass
class Lead:
    source: str
    name: str
    email: str
    question: str
    tags: str


class LeadBot:
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
                    status TEXT NOT NULL DEFAULT 'new',
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

    def _build_ref_code(self, lead_id: int, owner: str = DEFAULT_REF_OWNER) -> str:
        clean_owner = re.sub(r"[^A-Z0-9]", "", owner.upper())
        return f"{clean_owner}-LEAD-{lead_id:06d}"

    def add_lead(self, lead: Lead, owner: str = DEFAULT_REF_OWNER) -> int:
        created_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO leads(created_at, source, name, email, question, tags, ref_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (created_at, lead.source, lead.name, lead.email, lead.question, lead.tags, "PENDING"),
            )
            lead_id = cur.lastrowid
            ref_code = self._build_ref_code(lead_id, owner)
            conn.execute("UPDATE leads SET ref_code=? WHERE id=?", (ref_code, lead_id))
        return lead_id

    def get_lead(self, lead_id: int) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
            return dict(row) if row else None

    def get_lead_by_ref(self, ref_code: str) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM leads WHERE ref_code=?", (ref_code,)).fetchone()
            return dict(row) if row else None

    def mark_sale(self, ref_code: str, sale_amount: float, invoice_amount: float = 50.0) -> bool:
        sold_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE leads
                SET status='sold', sale_amount=?, sold_at=?, invoice_amount=?, invoice_sent_at=?
                WHERE ref_code=?
                """,
                (sale_amount, sold_at, invoice_amount, sold_at, ref_code),
            )
            return cur.rowcount > 0

    def mark_paid(self, ref_code: str, paid_amount: float) -> bool:
        paid_at = dt.datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE leads
                SET invoice_paid=1, invoice_paid_at=?, paid_amount=?, status='paid'
                WHERE ref_code=?
                """,
                (paid_at, paid_amount, ref_code),
            )
            return cur.rowcount > 0

    def weekly_summary(self, days: int = 7) -> str:
        since = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            leads = conn.execute(
                "SELECT * FROM leads WHERE created_at >= ? ORDER BY created_at DESC", (since,)
            ).fetchall()

            total = len(leads)
            sold = sum(1 for r in leads if r["status"] in ("sold", "paid"))
            paid = sum(1 for r in leads if r["invoice_paid"] == 1)
            unpaid = sold - paid

            rows = []
            for r in leads:
                rows.append(
                    f"- {r['ref_code']} | {r['name']} | {r['email']} | status={r['status']} | paid={bool(r['invoice_paid'])}"
                )

        return textwrap.dedent(
            f"""
            Weekly Lead Summary (last {days} days)
            Generated: {dt.datetime.utcnow().isoformat()} UTC

            Total new leads: {total}
            Converted (sold): {sold}
            Referral invoices paid: {paid}
            Referral invoices unpaid: {unpaid}

            Leads:
            {chr(10).join(rows) if rows else '- No leads in period'}
            """
        ).strip()


def draft_reply(lead: dict) -> str:
    return textwrap.dedent(
        f"""
        Hi {lead['name']},

        Thanks for your question about financial protection/planning.
        Based on what you shared, a licensed Primerica representative can help
        you compare options in plain language and build a practical plan.

        Contact: {KIA_EMAIL}
        Website: {KIA_WEBSITE}
        Reference code: {lead['ref_code']} (please include this in your message)

        Why Primerica:
        {PRIMERICA_CONTEXT}
        """
    ).strip()


def invoice_text(lead: dict, invoice_amount: float = 50.0) -> str:
    return textwrap.dedent(
        f"""
        Subject: Invoice for Converted Lead {lead['ref_code']}

        Hi Kia,

        A lead sourced under reference {lead['ref_code']} was marked as sold.

        Lead Name: {lead['name']}
        Lead Email: {lead['email']}
        Sale Amount: ${lead['sale_amount']:.2f}
        Sold At (UTC): {lead['sold_at']}

        Invoice Due: ${invoice_amount:.2f}
        Reason: Referral fee for converted lead.
        """
    ).strip()


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


def cmd_add(args: argparse.Namespace) -> None:
    bot = LeadBot(args.db)
    lead_id = bot.add_lead(
        Lead(args.source, args.name, args.email, args.question, args.tags), owner=args.owner
    )
    lead = bot.get_lead(lead_id)
    print(f"Created lead #{lead_id} with ref code {lead['ref_code']}")
    print("\n--- Suggested outreach reply ---")
    print(draft_reply(lead))
    if args.notify_kia:
        send_email(
            KIA_EMAIL,
            f"New Lead: {lead['name']} ({lead['ref_code']})",
            f"New lead captured from {lead['source']}\nWebsite: {KIA_WEBSITE}\n\n{draft_reply(lead)}",
        )


def cmd_mark_sold(args: argparse.Namespace) -> None:
    bot = LeadBot(args.db)
    if not bot.mark_sale(args.ref_code, args.sale_amount, args.invoice_amount):
        raise SystemExit(f"No lead found for {args.ref_code}")
    lead = bot.get_lead_by_ref(args.ref_code)
    invoice = invoice_text(lead, invoice_amount=args.invoice_amount)
    print(invoice)
    if args.send_invoice:
        send_email(KIA_EMAIL, f"Invoice: {args.ref_code} - ${args.invoice_amount:.2f}", invoice)


def cmd_mark_paid(args: argparse.Namespace) -> None:
    bot = LeadBot(args.db)
    if not bot.mark_paid(args.ref_code, args.paid_amount):
        raise SystemExit(f"No lead found for {args.ref_code}")
    print(f"Marked {args.ref_code} as PAID (${args.paid_amount:.2f}).")


def cmd_weekly_summary(args: argparse.Namespace) -> None:
    bot = LeadBot(args.db)
    report = bot.weekly_summary(days=args.days)
    print(report)
    if args.email:
        send_email(args.to, f"Weekly Leads Summary ({args.days} days)", report)
        print(f"Weekly summary email sent to {args.to}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compliant lead generator bot for Kia.")
    parser.add_argument("--db", default=DB_PATH, help="SQLite database path")
    sub = parser.add_subparsers(required=True)

    add = sub.add_parser("add", help="Add a new lead")
    add.add_argument("--source", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--email", required=True)
    add.add_argument("--question", required=True)
    add.add_argument("--tags", default="")
    add.add_argument("--owner", default=DEFAULT_REF_OWNER)
    add.add_argument("--notify-kia", action="store_true")
    add.set_defaults(func=cmd_add)

    sold = sub.add_parser("mark-sold", help="Mark a lead sold + invoice")
    sold.add_argument("--ref-code", required=True)
    sold.add_argument("--sale-amount", type=float, required=True)
    sold.add_argument("--invoice-amount", type=float, default=50.0)
    sold.add_argument("--send-invoice", action="store_true")
    sold.set_defaults(func=cmd_mark_sold)

    paid = sub.add_parser("mark-paid", help="Mark referral invoice as paid")
    paid.add_argument("--ref-code", required=True)
    paid.add_argument("--paid-amount", type=float, default=50.0)
    paid.set_defaults(func=cmd_mark_paid)

    weekly = sub.add_parser("weekly-summary", help="Generate weekly summary")
    weekly.add_argument("--days", type=int, default=7)
    weekly.add_argument("--email", action="store_true", help="Email summary")
    weekly.add_argument(
        "--to",
        default=DEFAULT_REPORT_TO or KIA_EMAIL,
        help="Recipient email for weekly summary (default LEADBOT_REPORT_TO or Kia)",
    )
    weekly.set_defaults(func=cmd_weekly_summary)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
