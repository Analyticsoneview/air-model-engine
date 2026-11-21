"""Dated contract lot-size snapshots and effective-dated equity sector master.

Revision ID: 0034_market_reference_history
Revises: 0033_customer_pin_auth
"""
from alembic import op
import sqlalchemy as sa

revision = "0034_market_reference_history"
down_revision = "0033_customer_pin_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_instrument_lot_size_history",
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
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
        sa.Column("source", sa.Text()),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("provider", "account_id", "effective_date", "token",
                               name="pk_market_instrument_lot_size_history"),
        sa.CheckConstraint("lot_size IS NULL OR lot_size > 0", name="ck_lot_size_history_positive"),
    )
    op.create_index("ix_lot_size_history_contract_date",
                    "market_instrument_lot_size_history",
                    ["symbol", "expiry", "strike", "option_type", "effective_date"])

    op.create_table(
        "market_equity_sector_history",
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(128), nullable=False),
        sa.Column("sector", sa.String(96), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_through", sa.Date()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text()),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("exchange", "symbol", "effective_from",
                               name="pk_market_equity_sector_history"),
        sa.CheckConstraint("effective_through IS NULL OR effective_through >= effective_from",
                           name="ck_sector_effective_range"),
    )
    op.create_index("ix_equity_sector_symbol_effective",
                    "market_equity_sector_history",
                    ["exchange", "symbol", "effective_from"])


def downgrade() -> None:
    op.drop_index("ix_equity_sector_symbol_effective", table_name="market_equity_sector_history")
    op.drop_table("market_equity_sector_history")
    op.drop_index("ix_lot_size_history_contract_date", table_name="market_instrument_lot_size_history")
    op.drop_table("market_instrument_lot_size_history")
