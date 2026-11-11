"""PostgreSQL schema for broker credentials, customer accounts and execution state.

Revision ID: 0003_postgres_domain_stores
Revises: 0002_customer_auth_access
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_postgres_domain_stores"
down_revision = "0002_customer_auth_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # air_domain_store_imports is shared infrastructure created by 0001.
    # Do not recreate it here; later domain importers use the existing table.

    op.create_table(
        "broker_credentials",
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("broker", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.PrimaryKeyConstraint("customer_id", "broker", "account_id", name="pk_broker_credentials"),
    )

    op.create_table(
        "customer_trading_accounts",
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("broker", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("enabled_for_orders", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.PrimaryKeyConstraint("broker", "account_id", name="pk_customer_trading_accounts"),
    )
    op.create_index("idx_customer_accounts_customer", "customer_trading_accounts", ["customer_id"])

    op.create_table(
        "customer_market_data_access",
        sa.Column("customer_id", sa.Text(), primary_key=True),
        sa.Column("tier", sa.String(16), nullable=False, server_default="STANDARD"),
        sa.Column("broker_data_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.CheckConstraint("tier IN ('STANDARD','PAID')", name="ck_customer_market_data_tier"),
    )

    op.create_table(
        "customer_market_data_selection",
        sa.Column("customer_id", sa.Text(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
    )

    op.create_table(
        "execution_policy",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("master_auto_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("strategy_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_execution_policy_singleton"),
    )
    op.create_table(
        "order_ledger",
        sa.Column("broker", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("broker_order_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.PrimaryKeyConstraint("broker", "account_id", "idempotency_key", name="pk_order_ledger"),
    )
    op.create_index("idx_order_ledger_status", "order_ledger", ["status", "updated_at"])

    op.create_table(
        "order_ledger_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("broker", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("broker_order_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("event_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
    )
    op.create_index("idx_order_events_account", "order_ledger_events", ["broker", "account_id", "event_id"])


def downgrade() -> None:
    op.drop_index("idx_order_events_account", table_name="order_ledger_events")
    op.drop_table("order_ledger_events")
    op.drop_index("idx_order_ledger_status", table_name="order_ledger")
    op.drop_table("order_ledger")
    op.drop_table("execution_policy")
    op.drop_table("customer_market_data_selection")
    op.drop_table("customer_market_data_access")
    op.drop_index("idx_customer_accounts_customer", table_name="customer_trading_accounts")
    op.drop_table("customer_trading_accounts")
    op.drop_table("broker_credentials")
    # Keep air_domain_store_imports: migration 0001 owns its lifecycle.
