"""Add append-only signed payment webhook receipt ledger.

Revision ID: 0024_payment_webhook_sandbox
Revises: 0023_usage_metering_quotas
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_payment_webhook_sandbox"
down_revision = "0023_usage_metering_quotas"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "air_payment_webhook_events",
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="RECEIVED"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("provider", "event_id", name="pk_air_payment_webhook_events"),
        sa.CheckConstraint("status = 'RECEIVED'", name="ck_air_payment_webhook_status"),
    )
    op.create_index("ix_air_payment_webhook_received", "air_payment_webhook_events", ["received_at"])
    # This is a global provider callback receipt ledger, not customer-readable data.
    # Only the service database role should access it; receipt rows are immutable.
    op.execute("REVOKE UPDATE, DELETE ON air_payment_webhook_events FROM PUBLIC")


def downgrade():
    op.drop_index("ix_air_payment_webhook_received", table_name="air_payment_webhook_events")
    op.drop_table("air_payment_webhook_events")
