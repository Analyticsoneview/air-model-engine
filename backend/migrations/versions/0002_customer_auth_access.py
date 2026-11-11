"""Customer authentication and device-access PostgreSQL schema.

Revision ID: 0002_customer_auth_access
Revises: 0001_admin_auth_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_customer_auth_access"
down_revision = "0001_admin_auth_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_customer_subscriptions",
        sa.Column("customer_id", sa.Text(), primary_key=True),
        sa.Column("plan_code", sa.String(16), nullable=False),
        sa.Column("starts_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP::text")),
        sa.CheckConstraint("plan_code IN ('DAILY','MONTHLY','SIX_MONTHS','YEARLY')", name="ck_air_customer_subscription_plan"),
        sa.CheckConstraint("status IN ('ACTIVE','CANCELLED','EXPIRED')", name="ck_air_customer_subscription_status"),
    )
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.Text(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_customers_email_lower", "customers", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "air_access_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("mobile_e164", sa.String(16), nullable=False),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_note", sa.String(500), nullable=True),
        sa.UniqueConstraint("mobile_e164", "device_id", name="uq_air_access_mobile_device"),
        sa.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','BLOCKED')", name="ck_air_access_status"),
    )
    op.create_index("ix_air_access_requests_status_created", "air_access_requests", ["status", "created_at"])

    op.create_table(
        "air_device_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("air_access_requests.request_id", ondelete="CASCADE"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_air_device_sessions_request_active", "air_device_sessions", ["request_id", "active"])


def downgrade() -> None:
    op.drop_table("air_customer_subscriptions")
    op.drop_index("ix_air_device_sessions_request_active", table_name="air_device_sessions")
    op.drop_table("air_device_sessions")
    op.drop_index("ix_air_access_requests_status_created", table_name="air_access_requests")
    op.drop_table("air_access_requests")
    op.drop_index("uq_customers_email_lower", table_name="customers")
    op.drop_table("customers")
