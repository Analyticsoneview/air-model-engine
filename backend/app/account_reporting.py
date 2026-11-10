"""Account-isolated broker P&L reports and verified-email delivery.

The collector is injected by the API layer so broker SDKs and credentials stay
outside this module. A report is marked partial when an account cannot be read.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import smtplib
import sqlite3
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class AccountReporting:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("AIR_REPORT_DB_PATH", "data/air_account_reports.sqlite3")
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS report_recipients (
                customer_id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                otp_hash TEXT,
                otp_expires_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS account_report_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                broker TEXT NOT NULL,
                account_id TEXT NOT NULL,
                report_date TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(customer_id, broker, account_id, report_date)
            )
        """)
        self.db.commit()

    def recipient(self, customer_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT email,verified,updated_at FROM report_recipients WHERE customer_id=?",
            (customer_id,),
        ).fetchone()
        return dict(row) if row else None

    def request_verification(self, customer_id: str, email: str) -> str:
        email = email.strip().lower()
        if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Enter a valid email address")
        code = f"{secrets.randbelow(1_000_000):06d}"
        digest = hashlib.sha256(f"{customer_id}:{email}:{code}".encode()).hexdigest()
        expires = (datetime.now(IST) + timedelta(minutes=10)).isoformat()
        with self.db:
            self.db.execute("""
                INSERT INTO report_recipients(customer_id,email,verified,otp_hash,otp_expires_at,updated_at)
                VALUES(?,?,0,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(customer_id) DO UPDATE SET email=excluded.email,verified=0,
                    otp_hash=excluded.otp_hash,otp_expires_at=excluded.otp_expires_at,
                    updated_at=CURRENT_TIMESTAMP
            """, (customer_id, email, digest, expires))
        self._send_email(email, "AIR email verification code",
                         f"Your AIR report email verification code is {code}. It expires in 10 minutes.")
        return email

    def confirm_verification(self, customer_id: str, code: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT email,otp_hash,otp_expires_at FROM report_recipients WHERE customer_id=?",
            (customer_id,),
        ).fetchone()
        if not row or not row["otp_hash"] or not row["otp_expires_at"]:
            raise ValueError("Request an email verification code first")
        try:
            expires = datetime.fromisoformat(row["otp_expires_at"])
        except ValueError:
            raise ValueError("Verification code is invalid; request a new code")
        digest = hashlib.sha256(f"{customer_id}:{row['email']}:{code.strip()}".encode()).hexdigest()
        if datetime.now(IST) > expires or not hmac.compare_digest(digest, row["otp_hash"]):
            raise ValueError("Verification code is invalid or expired")
        with self.db:
            self.db.execute("""
                UPDATE report_recipients SET verified=1,otp_hash=NULL,otp_expires_at=NULL,
                    updated_at=CURRENT_TIMESTAMP WHERE customer_id=?
            """, (customer_id,))
        return self.recipient(customer_id) or {}

    @staticmethod
    def _smtp_config() -> dict[str, Any]:
        host = os.getenv("AIR_SMTP_HOST", "").strip()
        username = os.getenv("AIR_SMTP_USERNAME", "").strip()
        password_file = os.getenv("AIR_SMTP_PASSWORD_FILE", "").strip()
        password = Path(password_file).read_text().strip() if password_file else os.getenv("AIR_SMTP_PASSWORD", "")
        sender = os.getenv("AIR_REPORT_FROM_EMAIL", username).strip()
        if not (host and username and password and sender):
            raise RuntimeError("AIR SMTP host, username, password secret and sender are not configured")
        return {"host": host, "port": int(os.getenv("AIR_SMTP_PORT", "587")),
                "username": username, "password": password, "sender": sender}

    @classmethod
    def _send_email(cls, recipient: str, subject: str, body: str,
                    attachments: list[tuple[str, bytes, str]] | None = None) -> None:
        cfg = cls._smtp_config()
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = cfg["sender"], recipient, subject
        message.set_content(body)
        for filename, payload, mime in attachments or []:
            maintype, subtype = mime.split("/", 1)
            message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as server:
            server.starttls()
            server.login(cfg["username"], cfg["password"])
            server.send_message(message)

    @staticmethod
    def _rows(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            for key in ("data", "netPositions", "net", "day", "positions",
                        "orders", "holdings", "orderBook", "result"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
                if isinstance(value, dict):
                    nested = AccountReporting._rows(value)
                    if nested:
                        return nested
            return [payload]
        return [x for x in payload if isinstance(x, dict)] if isinstance(payload, list) else []

    @staticmethod
    def _pnl_summary(positions: list[dict[str, Any]]) -> dict[str, float | None]:
        def total(keys: tuple[str, ...]) -> float | None:
            found = []
            for row in positions:
                value = next((row.get(k) for k in keys if row.get(k) is not None), None)
                try:
                    if value is not None:
                        found.append(float(value))
                except (TypeError, ValueError):
                    continue
            return round(sum(found), 2) if found else None

        realized = total(("realizedProfit", "realized_profit", "realized_pnl",
                          "realized", "realisedProfit", "realised_profit"))
        unrealized = total(("unrealizedProfit", "unrealized_profit", "unrealized_pnl",
                            "unrealized", "unrealisedProfit", "unrealised_profit", "mtm"))
        net = total(("netProfit", "net_pnl", "pnl", "pl"))
        if net is None and realized is not None and unrealized is not None:
            net = round(realized + unrealized, 2)
        return {
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "day_pnl": total(("dayProfit", "day_pnl", "dayPnL", "day_pnl_rupees")),
            "net_pnl": net,
        }

    @staticmethod
    def _artifacts(report_date: str, account: dict[str, str],
                   summary: dict[str, Any], positions: list[dict[str, Any]],
                   orders: list[dict[str, Any]], holdings: list[dict[str, Any]]) -> list[tuple[str, bytes, str]]:
        safe = "".join(c for c in account["account_id"] if c.isalnum() or c in "-_")[:40]
        base = f"AIR-{account['broker']}-{safe}-{report_date}"
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["section", "field", "value"])
        for key, value in summary.items():
            writer.writerow(["summary", key, value])
        for section, rows in (("positions", positions), ("orders", orders), ("holdings", holdings)):
            for index, row in enumerate(rows, 1):
                writer.writerow([section, index, json.dumps(row, default=str, sort_keys=True)])
        csv_bytes = output.getvalue().encode("utf-8-sig")
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            pdf_buffer = io.BytesIO()
            pdf = canvas.Canvas(pdf_buffer, pagesize=A4)
            width, height = A4
            y = height - 48
            pdf.setFont("Helvetica-Bold", 16)
            pdf.drawString(42, y, "AIR Broker Account P&L")
            y -= 28
            pdf.setFont("Helvetica", 10)
            for line in [f"Report date: {report_date}", f"Broker: {account['broker']}",
                         f"Account: {account['account_id']}", "Source: Broker account API",
                         *[f"{k.replace('_', ' ').title()}: {v if v is not None else 'Unavailable'}"
                           for k, v in summary.items()],
                         f"Positions: {len(positions)}", f"Orders: {len(orders)}",
                         f"Holdings: {len(holdings)}"]:
                pdf.drawString(42, y, line[:110])
                y -= 17
            pdf.setFont("Helvetica-Bold", 9)
            pdf.drawString(42, y - 4, "Position detail (raw broker fields retained in CSV)")
            pdf.save()
            pdf_bytes = pdf_buffer.getvalue()
        except ImportError as exc:
            raise RuntimeError("PDF reporting dependency reportlab is not installed") from exc
        return [(base + ".pdf", pdf_bytes, "application/pdf"),
                (base + ".csv", csv_bytes, "text/csv")]

    async def report_account(self, customer_id: str, account: Any,
                            collector: Callable[[str, str, str], Awaitable[dict[str, Any]]],
                            report_date: str, force: bool = False) -> dict[str, Any]:
        key = (customer_id, account.broker, account.account_id, report_date)
        existing = self.db.execute("""
            SELECT status,detail FROM account_report_runs
            WHERE customer_id=? AND broker=? AND account_id=? AND report_date=?
        """, key).fetchone()
        if existing and (existing["status"] == "SENT" or (existing["status"] == "FAILED" and not force)):
            return {"broker": account.broker, "account_id": account.account_id, "status": "already_attempted", "previous_status": existing["status"], "detail": existing["detail"]}
        try:
            payload = await collector(customer_id, account.broker, account.account_id)
            positions = self._rows(payload.get("positions"))
            orders = self._rows(payload.get("orders"))
            holdings = self._rows(payload.get("holdings"))
            summary = self._pnl_summary(positions)
            summary["pnl_status"] = ("BROKER_FIELDS_AVAILABLE" if any(
                summary.get(key) is not None
                for key in ("realized_pnl", "unrealized_pnl", "day_pnl", "net_pnl")
            ) else "BROKER_PNL_FIELDS_UNAVAILABLE")
            recipient = self.recipient(customer_id)
            if not recipient or not recipient["verified"]:
                raise RuntimeError("No verified report email is configured")
            attachments = self._artifacts(report_date,
                {"broker": account.broker, "account_id": account.account_id},
                summary, positions, orders, holdings)
            await asyncio.to_thread(self._send_email, recipient["email"],
                f"AIR daily P&L | {account.broker} | {account.account_id} | {report_date}",
                "Attached is your account-specific AIR broker report. P&L values are taken from "
                "the broker's returned position fields; unavailable values are not estimated. "
                "Review the CSV for raw broker records and reconciliation.",
                attachments)
            status, detail = "SENT", None
        except Exception as exc:
            status, detail = "FAILED", f"{type(exc).__name__}: {str(exc)[:400]}"
        with self.db:
            self.db.execute("""
                INSERT INTO account_report_runs(customer_id,broker,account_id,report_date,status,detail)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(customer_id,broker,account_id,report_date) DO UPDATE SET
                    status=excluded.status,detail=excluded.detail,created_at=CURRENT_TIMESTAMP
            """, (*key, status, detail))
        return {"broker": account.broker, "account_id": account.account_id,
                "status": status, "detail": detail}

    async def run_customer(self, customer_id: str, accounts: list[Any], collector,
                           report_date: str, force: bool = False) -> list[dict[str, Any]]:
        return await asyncio.gather(*[
            self.report_account(customer_id, account, collector, report_date, force=force)
            for account in accounts
        ])

    async def run_daily(self, account_directory, collector) -> None:
        now = datetime.now(IST)
        if now.weekday() >= 5 or (now.hour, now.minute) < (16, 0):
            return
        report_date = now.date().isoformat()
        customer_ids = sorted({a.customer_id for a in account_directory.list_all()})
        for customer_id in customer_ids:
            recipient = self.recipient(customer_id)
            if not recipient or not recipient["verified"]:
                continue
            accounts = account_directory.list_for_customer(customer_id)
            await self.run_customer(customer_id, accounts, collector, report_date)

    def history(self, customer_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.execute("""
            SELECT broker,account_id,report_date,status,detail,created_at
            FROM account_report_runs WHERE customer_id=?
            ORDER BY report_date DESC,created_at DESC LIMIT ?
        """, (customer_id, max(1, min(limit, 200)))).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.db.close()
