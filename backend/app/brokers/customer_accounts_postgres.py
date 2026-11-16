"""PostgreSQL implementation of AIR customer broker-account ownership and entitlements."""
from __future__ import annotations
from app.brokers.customer_accounts import CustomerTradingAccount
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from app.tenant_context import install_tenant_context, tenant_scope, customer_tenant_scope
from functools import wraps

def _customer_scoped(method):
    @wraps(method)
    def wrapped(self, customer_id, *args, **kwargs):
        with customer_tenant_scope(self.engine, customer_id):
            return method(self, customer_id, *args, **kwargs)
    return wrapped


def _account_scoped(method):
    @wraps(method)
    def wrapped(self, account, *args, **kwargs):
        with customer_tenant_scope(self.engine, account.customer_id):
            return method(self, account, *args, **kwargs)
    return wrapped


def _admin_scoped(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with tenant_scope(is_admin=True):
            return method(self, *args, **kwargs)
    return wrapped


class PostgresCustomerAccountDirectory:
    def __init__(self, database_url: str, engine: Engine | None = None):
        if engine is None:
            if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise RuntimeError("AIR_ACCOUNT_DATABASE_URL must point to PostgreSQL")
            engine = create_engine(database_url, pool_pre_ping=True, future=True)
        install_tenant_context(engine)
        self.engine = engine

    @staticmethod
    def _account(row):
        return CustomerTradingAccount(row["customer_id"], row["broker"], row["account_id"], bool(row["enabled_for_orders"]))

    @_account_scoped
    def add(self, account: CustomerTradingAccount) -> None:
        customer, broker, account_id = account.customer_id.strip(), account.broker.strip().lower(), account.account_id.strip()
        if not customer or not broker or not account_id:
            raise ValueError("Customer, broker and account identifiers are required")
        from sqlalchemy.exc import IntegrityError
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""INSERT INTO customer_trading_accounts
                    (customer_id,broker,account_id,enabled_for_orders) VALUES(:customer,:broker,:account,:enabled)"""),
                    {"customer": customer, "broker": broker, "account": account_id, "enabled": bool(account.enabled_for_orders)})
        except IntegrityError as exc:
            raise ValueError("Broker account is already registered to a customer") from exc

    @_admin_scoped
    def list_all(self) -> list[CustomerTradingAccount]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT customer_id,broker,account_id,enabled_for_orders
                FROM customer_trading_accounts ORDER BY customer_id,broker,account_id""")).mappings().all()
        return [self._account(row) for row in rows]

    @_customer_scoped
    def list_for_customer(self, customer_id: str) -> list[CustomerTradingAccount]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("""SELECT customer_id,broker,account_id,enabled_for_orders
                FROM customer_trading_accounts WHERE customer_id=:customer ORDER BY broker,account_id"""),
                {"customer": customer_id.strip()}).mappings().all()
        return [self._account(row) for row in rows]

    @_customer_scoped
    def set_order_permission(self, customer_id: str, broker: str, account_id: str, enabled: bool) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(text("""UPDATE customer_trading_accounts SET enabled_for_orders=:enabled
                WHERE customer_id=:customer AND broker=:broker AND account_id=:account"""),
                {"enabled": bool(enabled), "customer": customer_id.strip(), "broker": broker.strip().lower(), "account": account_id.strip()})
        if result.rowcount != 1:
            raise PermissionError("Customer does not own this broker account")

    @_customer_scoped
    def remove(self, customer_id: str, broker: str, account_id: str) -> None:
        params = {"customer": customer_id.strip(), "broker": broker.strip().lower(), "account": account_id.strip()}
        with self.engine.begin() as conn:
            result = conn.execute(text("""DELETE FROM customer_trading_accounts
                WHERE customer_id=:customer AND broker=:broker AND account_id=:account"""), params)
            if result.rowcount != 1:
                raise PermissionError("Customer does not own this broker account")
            conn.execute(text("""DELETE FROM customer_market_data_selection
                WHERE customer_id=:customer AND provider=:broker AND account_id=:account"""), params)

    @_customer_scoped
    def authorize_order_target(self, customer_id: str, broker: str, account_id: str) -> None:
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT customer_id,enabled_for_orders FROM customer_trading_accounts
                WHERE broker=:broker AND account_id=:account"""),
                {"broker": broker.strip().lower(), "account": account_id.strip()}).mappings().first()
        if row is None or row["customer_id"] != customer_id.strip():
            raise PermissionError("Customer does not own this broker account")
        if not row["enabled_for_orders"]:
            raise PermissionError("Order placement is disabled for this customer account")

    @_customer_scoped
    def get_market_data_access(self, customer_id: str) -> dict:
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT customer_id,tier,broker_data_enabled,updated_at
                FROM customer_market_data_access WHERE customer_id=:customer"""),
                {"customer": customer_id.strip()}).mappings().first()
        if row is None:
            return {"customer_id": customer_id.strip(), "tier": "STANDARD", "broker_data_enabled": False, "updated_at": None}
        return {**dict(row), "broker_data_enabled": bool(row["broker_data_enabled"])}

    @_customer_scoped
    def set_market_data_access(self, customer_id: str, tier: str, broker_data_enabled: bool) -> dict:
        customer, tier = customer_id.strip(), tier.strip().upper()
        if not customer or tier not in {"STANDARD", "PAID"}:
            raise ValueError("Customer ID and STANDARD/PAID tier are required")
        enabled = bool(broker_data_enabled) if tier == "PAID" else False
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO customer_market_data_access
                (customer_id,tier,broker_data_enabled,updated_at) VALUES(:customer,:tier,:enabled,CURRENT_TIMESTAMP)
                ON CONFLICT(customer_id) DO UPDATE SET tier=EXCLUDED.tier,
                broker_data_enabled=EXCLUDED.broker_data_enabled,updated_at=CURRENT_TIMESTAMP"""),
                {"customer": customer, "tier": tier, "enabled": enabled})
            if tier == "STANDARD":
                conn.execute(text("DELETE FROM customer_market_data_selection WHERE customer_id=:customer"), {"customer": customer})
        return self.get_market_data_access(customer)

    @_customer_scoped
    def get_market_data_selection(self, customer_id: str) -> dict | None:
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT customer_id,provider,account_id,updated_at
                FROM customer_market_data_selection WHERE customer_id=:customer"""),
                {"customer": customer_id.strip()}).mappings().first()
        return dict(row) if row else None

    @_customer_scoped
    def set_market_data_selection(self, customer_id: str, provider: str, account_id: str) -> dict:
        customer, provider, account = customer_id.strip(), provider.strip().lower(), account_id.strip()
        if not customer or not provider or not account:
            raise ValueError("Customer, provider and account are required")
        with self.engine.begin() as conn:
            owned = conn.execute(text("""SELECT 1 FROM customer_trading_accounts
                WHERE customer_id=:customer AND broker=:provider AND account_id=:account"""),
                {"customer": customer, "provider": provider, "account": account}).first()
            if owned is None:
                raise PermissionError("Customer does not own this broker account")
            access = conn.execute(text("""SELECT tier,broker_data_enabled FROM customer_market_data_access
                WHERE customer_id=:customer"""), {"customer": customer}).mappings().first()
            if access is None or access["tier"] != "PAID" or not access["broker_data_enabled"]:
                raise PermissionError("Broker market data requires an enabled paid entitlement")
            conn.execute(text("""INSERT INTO customer_market_data_selection
                (customer_id,provider,account_id,updated_at) VALUES(:customer,:provider,:account,CURRENT_TIMESTAMP)
                ON CONFLICT(customer_id) DO UPDATE SET provider=EXCLUDED.provider,
                account_id=EXCLUDED.account_id,updated_at=CURRENT_TIMESTAMP"""),
                {"customer": customer, "provider": provider, "account": account})
        return self.get_market_data_selection(customer) or {}

    @_customer_scoped
    def clear_market_data_selection(self, customer_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM customer_market_data_selection WHERE customer_id=:customer"), {"customer": customer_id.strip()})

    def close(self) -> None:
        self.engine.dispose()
