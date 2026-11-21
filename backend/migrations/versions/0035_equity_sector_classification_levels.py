"""Expand the symbol-keyed equity classification master to four NSE levels.

Revision ID: 0035_equity_sector_levels
Revises: 0034_market_reference_history
"""
from alembic import op
import sqlalchemy as sa

revision = "0035_equity_sector_levels"
down_revision = "0034_market_reference_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_equity_sector_history", sa.Column("company_name", sa.String(256)))
    op.add_column("market_equity_sector_history", sa.Column("macro_sector", sa.String(128)))
    op.add_column("market_equity_sector_history", sa.Column("industry", sa.String(128)))
    op.add_column("market_equity_sector_history", sa.Column("basic_industry", sa.String(160)))
    op.add_column("market_equity_sector_history", sa.Column(
        "classification_status", sa.String(24), nullable=False, server_default="UNVERIFIED"
    ))
    op.create_check_constraint(
        "ck_equity_sector_classification_status",
        "market_equity_sector_history",
        "classification_status IN ('VERIFIED','UNVERIFIED','PROVISIONAL')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_equity_sector_classification_status",
                       "market_equity_sector_history", type_="check")
    op.drop_column("market_equity_sector_history", "classification_status")
    op.drop_column("market_equity_sector_history", "basic_industry")
    op.drop_column("market_equity_sector_history", "industry")
    op.drop_column("market_equity_sector_history", "macro_sector")
    op.drop_column("market_equity_sector_history", "company_name")
