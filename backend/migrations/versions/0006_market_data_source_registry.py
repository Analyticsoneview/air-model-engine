"""PostgreSQL schema for independent market-data source and failover selection.

Revision ID: 0006_market_data_source_registry
Revises: 0005_market_instrument_directory
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_market_data_source_registry"
down_revision = "0005_market_instrument_directory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_data_sources",
        sa.Column("channel", sa.String(16), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fallback_provider", sa.String(32)),
        sa.Column("fallback_account_id", sa.String(128)),
        sa.Column("failover_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.CheckConstraint("channel IN ('historical','live')", name="ck_market_data_source_channel"),
    )
    op.create_table(
        "market_data_failover",
        sa.Column("channel", sa.String(16), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("candidates_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.CheckConstraint("channel IN ('historical','live')", name="ck_market_data_failover_channel"),
    )


def downgrade() -> None:
    op.drop_table("market_data_failover")
    op.drop_table("market_data_sources")
