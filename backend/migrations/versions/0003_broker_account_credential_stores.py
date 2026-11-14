"""Add PostgreSQL broker account, entitlement and encrypted credential stores.

Revision ID: 0003_broker_account_credential_stores
Revises: 0002_customer_access_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_broker_account_credential_stores"
down_revision = "0002_customer_access_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_trading_accounts",
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("broker", sa.String(40), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("enabled_for_orders", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("broker", "account_id", name="pk_customer_trading_accounts"),
        sa.UniqueConstraint("customer_id", "broker", "account_id", name="uq_customer_account_owner"),
    )
    op.create_index("ix_customer_accounts_customer", "customer_trading_accounts", ["customer_id"])
    op.create_table(
        "customer_market_data_access",
        sa.Column("customer_id", sa.String(128), primary_key=True),
        sa.Column("tier", sa.String(16), nullable=False, server_default="STANDARD"),
        sa.Column("broker_data_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("tier IN ('STANDARD','PAID')", name="ck_customer_market_data_tier"),
        sa.CheckConstraint("tier <> 'STANDARD' OR broker_data_enabled = false", name="ck_customer_standard_no_broker_data"),
    )
    op.create_table(
        "customer_market_data_selection",
        sa.Column("customer_id", sa.String(128), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["customer_id", "provider", "account_id"],
            ["customer_trading_accounts.customer_id", "customer_trading_accounts.broker", "customer_trading_accounts.account_id"],
            name="fk_market_selection_owned_account", ondelete="CASCADE"),
    )
    op.create_index("ix_customer_market_selection_provider", "customer_market_data_selection", ["provider", "account_id"])
    op.create_table(
        "broker_credentials",
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("broker", sa.String(40), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("customer_id", "broker", "account_id", name="pk_broker_credentials"),
        sa.ForeignKeyConstraint(
            ["customer_id", "broker", "account_id"],
            ["customer_trading_accounts.customer_id", "customer_trading_accounts.broker", "customer_trading_accounts.account_id"],
            name="fk_broker_credentials_owned_account", ondelete="CASCADE"),
    )
    op.create_index("ix_broker_credentials_broker_account", "broker_credentials", ["broker", "account_id"])


def downgrade() -> None:
    op.drop_index("ix_broker_credentials_broker_account", table_name="broker_credentials")
    op.drop_table("broker_credentials")
    op.drop_index("ix_customer_market_selection_provider", table_name="customer_market_data_selection")
    op.drop_table("customer_market_data_selection")
    op.drop_table("customer_market_data_access")
    op.drop_index("ix_customer_accounts_customer", table_name="customer_trading_accounts")
    op.drop_table("customer_trading_accounts")
