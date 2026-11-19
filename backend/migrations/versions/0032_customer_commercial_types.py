"""Classify customers as service or metered data-product consumers.

Revision ID: 0032_customer_commercial_types
Revises: 0031_admin_refresh_tokens
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_customer_commercial_types"
down_revision = "0031_admin_refresh_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_commercial_classification",
        sa.Column("customer_id", sa.String(128), primary_key=True),
        sa.Column("customer_type", sa.String(24), nullable=False),
        sa.Column("assigned_by_admin_id", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "customer_type IN ('SERVICE','DATA_PRODUCT')",
            name="ck_customer_commercial_classification_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("customer_commercial_classification")
