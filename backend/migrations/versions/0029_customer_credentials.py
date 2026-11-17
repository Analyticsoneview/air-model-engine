"""Create the PostgreSQL customer credential store.

Revision ID: 0029_customer_credentials
Revises: 0028_enterprise_license
"""
from alembic import op
import sqlalchemy as sa

revision = "0029_customer_credentials"
down_revision = "0028_enterprise_license"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.String(128), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "uq_customers_email_lower",
        "customers",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_customers_email_lower", table_name="customers")
    op.drop_table("customers")
