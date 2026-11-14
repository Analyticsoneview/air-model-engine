"""PostgreSQL schema for provider-specific broker instrument masters.

Revision ID: 0005_market_instrument_directory
Revises: 0004_qoc_observations
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_market_instrument_directory"
down_revision = "0004_qoc_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_instruments",
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(128), nullable=False),
        sa.Column("underlying_symbol", sa.String(128)),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("segment", sa.String(32), nullable=False),
        sa.Column("expiry", sa.String(16)),
        sa.Column("strike", sa.String(32)),
        sa.Column("option_type", sa.String(2)),
        sa.Column("lot_size", sa.Integer()),
        sa.Column("instrument_type", sa.String(32)),
        sa.Column("tick_size", sa.String(32)),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.PrimaryKeyConstraint("provider", "account_id", "token", name="pk_market_instruments"),
    )
    op.create_index(
        "idx_market_instruments_symbol", "market_instruments",
        ["provider", "account_id", "symbol"],
    )
    op.create_table(
        "market_master_refresh",
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text()),
        sa.Column("refreshed_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("provider", "account_id", name="pk_market_master_refresh"),
    )


def downgrade() -> None:
    op.drop_table("market_master_refresh")
    op.drop_index("idx_market_instruments_symbol", table_name="market_instruments")
    op.drop_table("market_instruments")
