"""Durable workflow definitions, event inbox and transactional outbox.

Revision ID: 0012_workflow_engine_foundation
Revises: 0011_admin_support_center
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_workflow_engine_foundation"
down_revision = "0011_admin_support_center"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "air_workflow_definitions",
        sa.Column("workflow_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("trigger_config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("workflow_spec_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("execution_mode", sa.String(24), nullable=False, server_default="RESEARCH_ONLY"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("trigger_type IN ('EVENT','TIME','STRATEGY','CONDITION')",
                           name="ck_air_workflow_trigger_type"),
        sa.CheckConstraint("execution_mode IN ('RESEARCH_ONLY','ALERT_NOTIFY','AUTHORIZED_EXECUTION')",
                           name="ck_air_workflow_execution_mode"),
        sa.CheckConstraint("version >= 1", name="ck_air_workflow_version"),
    )
    op.create_index("ix_air_workflow_enabled_trigger", "air_workflow_definitions",
                    ["enabled", "trigger_type"])

    op.create_table(
        "air_workflow_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("correlation_id", sa.String(36)),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_air_workflow_events_type_time", "air_workflow_events",
                    ["event_type", "occurred_at"])

    op.create_table(
        "air_workflow_outbox",
        sa.Column("outbox_id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.CheckConstraint("status IN ('PENDING','PUBLISHED','FAILED')",
                           name="ck_air_workflow_outbox_status"),
    )
    op.create_index("ix_air_workflow_outbox_pending", "air_workflow_outbox",
                    ["status", "available_at"])


def downgrade() -> None:
    op.drop_index("ix_air_workflow_outbox_pending", table_name="air_workflow_outbox")
    op.drop_table("air_workflow_outbox")
    op.drop_index("ix_air_workflow_events_type_time", table_name="air_workflow_events")
    op.drop_table("air_workflow_events")
    op.drop_index("ix_air_workflow_enabled_trigger", table_name="air_workflow_definitions")
    op.drop_table("air_workflow_definitions")
