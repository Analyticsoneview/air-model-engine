"""Create PostgreSQL schema for customer access, sessions and marketing.

Revision ID: 0002_customer_access_schema
Revises: 0001_admin_auth_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_customer_access_schema"
down_revision = "0001_admin_auth_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_access_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("mobile_e164", sa.String(16), nullable=False),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP::text)")),
        sa.Column("reviewed_at", sa.Text(), nullable=True),
        sa.Column("reviewer_note", sa.String(500), nullable=True),
        sa.UniqueConstraint("mobile_e164", "device_id", name="uq_air_access_mobile_device"),
        sa.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','BLOCKED')", name="ck_air_access_status"),
    )
    op.create_index("ix_air_access_requests_created", "air_access_requests", ["created_at"])
    op.create_index("ix_air_access_requests_status", "air_access_requests", ["status"])
    op.create_table(
        "air_device_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("air_access_requests.request_id", ondelete="CASCADE"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP::text)")),
    )
    op.create_index("ix_air_device_sessions_request_active", "air_device_sessions", ["request_id", "active"])
    op.create_table(
        "air_customer_subscriptions",
        sa.Column("customer_id", sa.String(16), primary_key=True),
        sa.Column("plan_code", sa.String(16), nullable=False),
        sa.Column("starts_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP::text)")),
        sa.CheckConstraint("plan_code IN ('DAILY','MONTHLY','SIX_MONTHS','YEARLY')", name="ck_air_customer_subscription_plan"),
        sa.CheckConstraint("status IN ('ACTIVE','CANCELLED','EXPIRED')", name="ck_air_customer_subscription_status"),
    )
    op.create_table(
        "air_customer_marketing_preferences",
        sa.Column("customer_id", sa.String(16), primary_key=True),
        sa.Column("promotional_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consent_updated_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP::text)")),
    )
    op.create_table(
        "air_marketing_offers",
        sa.Column("offer_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("offer_code", sa.String(32), nullable=False, unique=True),
        sa.Column("plan_code", sa.String(16), nullable=False),
        sa.Column("discount_percent", sa.Float(), nullable=False),
        sa.Column("starts_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("terms", sa.String(1000), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("created_by", sa.String(254), nullable=False),
        sa.Column("approved_by", sa.String(254), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP::text)")),
        sa.Column("approved_at", sa.Text(), nullable=True),
        sa.CheckConstraint("plan_code IN ('DAILY','MONTHLY','SIX_MONTHS','YEARLY')", name="ck_air_marketing_offer_plan"),
        sa.CheckConstraint("discount_percent > 0 AND discount_percent <= 90", name="ck_air_marketing_offer_discount"),
        sa.CheckConstraint("status IN ('DRAFT','APPROVED','REVOKED')", name="ck_air_marketing_offer_status"),
    )
    op.create_index("ix_air_marketing_offers_status_created", "air_marketing_offers", ["status", "created_at"])
    op.create_table(
        "air_marketing_audit",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("actor_customer_id", sa.String(254), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(254), nullable=False),
        sa.Column("details", sa.String(1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP::text)")),
    )
    op.create_index("ix_air_marketing_audit_created", "air_marketing_audit", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_air_marketing_audit_created", table_name="air_marketing_audit")
    op.drop_table("air_marketing_audit")
    op.drop_index("ix_air_marketing_offers_status_created", table_name="air_marketing_offers")
    op.drop_table("air_marketing_offers")
    op.drop_table("air_customer_marketing_preferences")
    op.drop_table("air_customer_subscriptions")
    op.drop_index("ix_air_device_sessions_request_active", table_name="air_device_sessions")
    op.drop_table("air_device_sessions")
    op.drop_index("ix_air_access_requests_status", table_name="air_access_requests")
    op.drop_index("ix_air_access_requests_created", table_name="air_access_requests")
    op.drop_table("air_access_requests")
