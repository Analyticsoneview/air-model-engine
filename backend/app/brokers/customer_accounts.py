"""Persistent customer-to-broker execution account ownership directory.

Only account identifiers and permissions are stored here. Broker credentials and
access tokens belong in a separate encrypted credential vault.
"""
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CustomerTradingAccount:
    customer_id: str
    broker: str
    account_id: str
    enabled_for_orders: bool = False


class CustomerAccountDirectory:
    """SQLite-backed ownership registry; safe to reopen across server restarts."""

    def __init__(self, db_path: str = "data/customer_accounts.sqlite3"):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_trading_accounts (
                customer_id TEXT NOT NULL,
                broker TEXT NOT NULL,
                account_id TEXT NOT NULL,
                enabled_for_orders INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (broker, account_id)
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_customer_accounts_customer "
            "ON customer_trading_accounts(customer_id)"
        )
        self._connection.commit()

    def add(self, account: CustomerTradingAccount) -> None:
        customer = account.customer_id.strip()
        broker = account.broker.strip().lower()
        account_id = account.account_id.strip()
        if not customer or not broker or not account_id:
            raise ValueError("Customer, broker and account identifiers are required")
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO customer_trading_accounts "
                    "(customer_id, broker, account_id, enabled_for_orders) VALUES (?, ?, ?, ?)",
                    (customer, broker, account_id, int(account.enabled_for_orders)),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Broker account is already registered to a customer") from exc

    def list_all(self) -> list[CustomerTradingAccount]:
        rows = self._connection.execute(
            "SELECT customer_id, broker, account_id, enabled_for_orders "
            "FROM customer_trading_accounts ORDER BY customer_id, broker, account_id"
        ).fetchall()
        return [
            CustomerTradingAccount(r["customer_id"], r["broker"], r["account_id"],
                                   bool(r["enabled_for_orders"]))
            for r in rows
        ]

    def list_for_customer(self, customer_id: str) -> list[CustomerTradingAccount]:
        rows = self._connection.execute(
            "SELECT customer_id, broker, account_id, enabled_for_orders "
            "FROM customer_trading_accounts WHERE customer_id = ? ORDER BY broker, account_id",
            (customer_id.strip(),),
        ).fetchall()
        return [
            CustomerTradingAccount(r["customer_id"], r["broker"], r["account_id"],
                                   bool(r["enabled_for_orders"]))
            for r in rows
        ]

    def set_order_permission(self, customer_id: str, broker: str, account_id: str, enabled: bool) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE customer_trading_accounts SET enabled_for_orders = ? "
                "WHERE customer_id = ? AND broker = ? AND account_id = ?",
                (int(enabled), customer_id.strip(), broker.strip().lower(), account_id.strip()),
            )
        if cursor.rowcount != 1:
            raise PermissionError("Customer does not own this broker account")

    def remove(self, customer_id: str, broker: str, account_id: str) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM customer_trading_accounts "
                "WHERE customer_id = ? AND broker = ? AND account_id = ?",
                (customer_id.strip(), broker.strip().lower(), account_id.strip()),
            )
        if cursor.rowcount != 1:
            raise PermissionError("Customer does not own this broker account")

    def authorize_order_target(self, customer_id: str, broker: str, account_id: str) -> None:
        row = self._connection.execute(
            "SELECT customer_id, enabled_for_orders FROM customer_trading_accounts "
            "WHERE broker = ? AND account_id = ?",
            (broker.strip().lower(), account_id.strip()),
        ).fetchone()
        if row is None or row["customer_id"] != customer_id.strip():
            raise PermissionError("Customer does not own this broker account")
        if not row["enabled_for_orders"]:
            raise PermissionError("Order placement is disabled for this customer account")

    def close(self) -> None:
        self._connection.close()
