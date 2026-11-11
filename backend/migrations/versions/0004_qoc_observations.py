"""PostgreSQL schema for AIR QOC option-chain observations.

Revision ID: 0004_qoc_observations
Revises: 0003_postgres_domain_stores
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_qoc_observations"
down_revision = "0003_postgres_domain_stores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "option_observations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("underlying_scrip", sa.BigInteger(), nullable=False),
        sa.Column("underlying_segment", sa.String(32), nullable=False),
        sa.Column("expiry", sa.String(10), nullable=False),
        sa.Column("underlying_price", sa.Float()),
        sa.Column("strike", sa.String(32), nullable=False),
        sa.Column("option_type", sa.String(2), nullable=False),
        sa.Column("security_id", sa.String(64)),
        sa.Column("last_price", sa.Float()),
        sa.Column("previous_close", sa.Float()),
        sa.Column("volume", sa.BigInteger()),
        sa.Column("previous_volume", sa.BigInteger()),
        sa.Column("open_interest", sa.BigInteger()),
        sa.Column("previous_oi", sa.BigInteger()),
        sa.Column("bid_price", sa.Float()),
        sa.Column("bid_quantity", sa.BigInteger()),
        sa.Column("ask_price", sa.Float()),
        sa.Column("ask_quantity", sa.BigInteger()),
        sa.Column("implied_volatility", sa.Float()),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "provider", "account_id", "underlying_scrip", "expiry",
            "strike", "option_type", "observed_at",
            name="uq_qoc_option_observation",
        ),
        sa.CheckConstraint("option_type IN ('CE','PE')", name="ck_qoc_option_type"),
    )
    op.create_index(
        "idx_qoc_latest",
        "option_observations",
        ["provider", "account_id", "underlying_scrip", "expiry", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_qoc_latest", table_name="option_observations")
    op.drop_table("option_observations")
